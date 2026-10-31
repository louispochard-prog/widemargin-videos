#!/usr/bin/env python3
"""Turn a video file into what Claude can read: timed transcript, numbered frame sheets, OCR, metadata.

usage: python3 video_to_claude.py VIDEO [options]

Outputs (in --out, default <video stem>_for_claude/ next to the video):
  transcript.txt / transcript.srt   timed transcript (platform subtitles first, Whisper otherwise)
  frames/frame_NN.jpg               full-resolution frames, numbered in time order
  sheet_NN.jpg                      3x3 contact sheets of those frames, each cell labelled "#NN mm:ss.s"
  ocr.txt                           on-screen text per frame (Tesseract), optionally cropped
  meta.json                         source, duration, format, frame list, transcript source, tool versions
  analysis_prompt.md                prompt to paste into Claude together with the files above

The input is always a local file the user is allowed to keep (native download button, our own renders).
A TikTok URL given with --url is only used for official oEmbed metadata: no download, no cookies,
no browser impersonation.
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCAL_WHISPER = Path("/mnt/project-files/modeles/faster-whisper-small")
OEMBED_HOSTS = {"www.tiktok.com", "tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}
SUB_EXTS = (".srt", ".vtt")
CROPS = {"top": (0, 0, 1, 1 / 3), "middle": (0, 1 / 3, 1, 1 / 3), "bottom": (0, 2 / 3, 1, 1 / 3)}
CELL_W = 360  # sheet cell width in px; a 3x3 portrait sheet is 1080 px wide
LABEL_H = 34


# ---------- small helpers ----------

def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def fmt_clock(t):
    m, s = divmod(max(t, 0.0), 60)
    return f"{int(m):02d}:{s:04.1f}"


def fmt_srt_time(t):
    ms = int(round(max(t, 0.0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_time(stamp):
    """'00:01:02,500', '01:02.500' or '62.5' -> seconds."""
    parts = stamp.strip().replace(",", ".").split(":")
    secs = 0.0
    for p in parts:
        secs = secs * 60 + float(p)
    return secs


# ---------- subtitles ----------

CUE_RE = re.compile(r"((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})")


def parse_subtitles(text):
    """Parse SRT or WebVTT text into [{'start', 'end', 'text'}], dropping tags and repeated rolling lines."""
    segments = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("﻿", "")):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = CUE_RE.search(line)
            if m:
                body = " ".join(lines[i + 1:])
                body = re.sub(r"<[^>]+>|\{[^}]+\}", "", body)
                body = re.sub(r"\s+", " ", body).strip()
                if body and not (segments and segments[-1]["text"] == body):
                    segments.append({"start": parse_time(m.group(1)), "end": parse_time(m.group(2)), "text": body})
                break
    return segments


def find_sidecar_subtitles(video):
    """Subtitles saved next to the video: <stem>.srt, <stem>.vtt or <stem>.<lang>.vtt (yt-dlp naming)."""
    video = Path(video)
    for ext in SUB_EXTS:
        exact = video.with_suffix(ext)
        if exact.exists():
            return exact
    for cand in sorted(video.parent.glob(f"{glob_escape(video.stem)}.*")):
        if cand.suffix.lower() in SUB_EXTS:
            return cand
    return None


def glob_escape(s):
    return re.sub(r"([*?\[])", r"[\1]", s)


# ---------- probing ----------

def probe(video):
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "format=duration,size:stream=codec_type,codec_name,width,height,avg_frame_rate",
             "-of", "json", str(video)])
    if r.returncode != 0:
        raise SystemExit(f"ffprobe failed on {video}: {r.stderr.strip()}")
    info = json.loads(r.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if v is None:
        raise SystemExit(f"{video} has no video stream")
    num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den) if den and float(den) else 0.0
    return {
        "duration": float(info["format"].get("duration", 0.0)),
        "size_bytes": int(info["format"].get("size", 0)),
        "width": v.get("width"),
        "height": v.get("height"),
        "fps": round(fps, 3),
        "video_codec": v.get("codec_name"),
        "audio_codec": a.get("codec_name") if a else None,
    }


# ---------- frame selection ----------

def scene_changes(video, threshold):
    """Timestamps where ffmpeg's scene score exceeds threshold."""
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-an",
             "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"])
    return [float(t) for t in re.findall(r"pts_time:([0-9.]+)", r.stderr)]


def pick_timestamps(duration, cuts, min_frames, max_frames, every=None, hook=0.5):
    """Choose frame times: the hook frame, one frame just after each cut, then even fill or thinning.

    The fill adds frames in the widest gaps until there are min_frames and, when every is set,
    no gap longer than every seconds (animations with few hard cuts still get regular frames).

    Returns a sorted list of (time, reason) with reason in {'hook', 'scene', 'uniform'}.
    """
    end = max(duration - 0.1, 0.0)
    hook = min(hook, end)
    gap = max(duration / (max_frames * 2), 0.2)  # closer frames than this are near-duplicates
    picked = [(hook, "hook")]
    for c in sorted(cuts):
        t = min(c + 0.15, end)  # just after the cut, once the new shot is drawn
        if all(abs(t - p) >= gap for p, _ in picked):
            picked.append((t, "scene"))
    if len(picked) > max_frames:
        scenes = [p for p in picked if p[1] == "scene"]
        keep = max_frames - 1
        step = len(scenes) / keep if keep else 0
        picked = [picked[0]] + [scenes[int(i * step)] for i in range(keep)]
    while len(picked) < max_frames:
        # add the midpoint of the widest empty stretch
        times = sorted([p for p, _ in picked] + [0.0, duration])
        a, b = max(zip(times, times[1:]), key=lambda ab: ab[1] - ab[0])
        if b - a < 0.1 or (len(picked) >= min_frames and (not every or b - a <= every)):
            break
        picked.append(((a + b) / 2, "uniform"))
    return sorted(picked)


def extract_frames(video, times, frames_dir):
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("frame_*.jpg"):
        old.unlink()
    paths = []
    for i, t in enumerate(times, 1):
        out = frames_dir / f"frame_{i:02d}.jpg"
        r = run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video),
                 "-frames:v", "1", "-q:v", "3", str(out)])
        if r.returncode != 0 or not out.exists():
            raise SystemExit(f"could not extract frame at {t:.2f}s: {r.stderr.strip()}")
        paths.append(out)
    return paths


def build_sheets(frames, times, out_dir, cols=3, rows=3):
    """3x3 sheets; each cell has a label band above the image so nothing in the frame is hidden."""
    from PIL import Image, ImageDraw, ImageFont

    for old in out_dir.glob("sheet_*.jpg"):
        old.unlink()
    font = load_font(ImageFont, 22)
    per_sheet = cols * rows
    sheets = []
    with Image.open(frames[0]) as first:
        cell_h = int(round(CELL_W * first.height / first.width))
    for s in range(math.ceil(len(frames) / per_sheet)):
        chunk = list(range(s * per_sheet, min(len(frames), (s + 1) * per_sheet)))
        n_rows = math.ceil(len(chunk) / cols)
        sheet = Image.new("RGB", (cols * CELL_W, n_rows * (cell_h + LABEL_H)), (18, 18, 18))
        draw = ImageDraw.Draw(sheet)
        for k, i in enumerate(chunk):
            x, y = (k % cols) * CELL_W, (k // cols) * (cell_h + LABEL_H)
            with Image.open(frames[i]) as im:
                sheet.paste(im.convert("RGB").resize((CELL_W, cell_h)), (x, y + LABEL_H))
            draw.text((x + 8, y + 5), f"#{i + 1:02d}  {fmt_clock(times[i])}", fill=(255, 220, 0), font=font)
        path = out_dir / f"sheet_{s + 1:02d}.jpg"
        sheet.save(path, quality=88)
        sheets.append(path)
    return sheets


def load_font(ImageFont, size):
    for name in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


# ---------- OCR ----------

def parse_crop(spec):
    """'none' | 'top' | 'middle' | 'bottom' | 'x,y,w,h' (pixels, or fractions when all <= 1)."""
    if spec in (None, "", "none"):
        return None
    if spec in CROPS:
        return CROPS[spec]
    try:
        vals = tuple(float(v) for v in spec.split(","))
    except ValueError:
        vals = ()
    if len(vals) != 4 or min(vals) < 0 or vals[2] == 0 or vals[3] == 0:
        raise argparse.ArgumentTypeError(f"bad crop '{spec}': use none, top, middle, bottom or x,y,w,h")
    return vals


def crop_box(crop, width, height):
    x, y, w, h = crop
    if max(crop) <= 1:
        x, y, w, h = x * width, y * height, w * width, h * height
    x0, y0 = max(0, int(x)), max(0, int(y))
    return x0, y0, min(width, int(x + w)), min(height, int(y + h))


def tesseract_langs(wanted):
    if not shutil.which("tesseract"):
        return None
    r = run(["tesseract", "--list-langs"])
    have = set(r.stdout.split()) | set(r.stderr.split())
    langs = [l for l in wanted.split("+") if l in have]
    return "+".join(langs) or ("eng" if "eng" in have else None)


def confident_words(tsv, min_conf):
    """Words from Tesseract TSV output with confidence >= min_conf (drops noise read in graphics)."""
    words = []
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) == 12 and cols[11].strip():
            try:
                conf = float(cols[10])
            except ValueError:
                continue
            word = cols[11].strip()
            if conf >= min_conf and re.search(r"[A-Za-z0-9À-ÿ]{2,}|^[A-Za-z0-9]$", word):
                words.append(word)
    return words


def ocr_frames(frames, times, crop, langs, out_path, min_conf=70):
    from PIL import Image

    lines, previous = [], None
    with tempfile.TemporaryDirectory() as tmp:
        for i, (f, t) in enumerate(zip(frames, times), 1):
            with Image.open(f) as im:
                im = im.convert("L")
                if crop:
                    im = im.crop(crop_box(crop, *im.size))
                if im.width < 1000:  # Tesseract reads small subtitles better when upscaled
                    im = im.resize((im.width * 2, im.height * 2))
                src = Path(tmp) / f"ocr_{i:02d}.png"
                im.save(src)
            r = run(["tesseract", str(src), "stdout", "-l", langs, "--psm", "11", "tsv"])
            text = " ".join(confident_words(r.stdout, min_conf))
            if text and text != previous:
                lines.append(f"#{i:02d} {fmt_clock(t)}  {text}")
            previous = text or previous
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)


# ---------- Whisper ----------

WHISPER_CODE = r"""
import json, sys, wave
import numpy as np
from faster_whisper import WhisperModel
wav, model, lang = sys.argv[1], sys.argv[2], sys.argv[3]
with wave.open(wav) as w:
    audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
# an array, not a path: faster-whisper 1.2.1 crashes when it decodes a path with PyAV 19
m = WhisperModel(model, device="cpu", compute_type="int8")
segs, info = m.transcribe(audio, language=None if lang == "auto" else lang, vad_filter=True)
out = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segs]
print(json.dumps({"language": info.language, "probability": info.language_probability, "segments": out}))
"""


def whisper_python():
    """An interpreter that can import faster_whisper: this one, $WM_PY_VOIX, then ~/.widemargin/kt."""
    wm = os.environ.get("WM_HOME", os.path.expanduser("~/.widemargin"))
    for cand in (sys.executable, os.environ.get("WM_PY_VOIX", ""), f"{wm}/kt/bin/python"):
        if cand and os.path.exists(cand) and run([cand, "-c", "import faster_whisper, numpy"]).returncode == 0:
            return cand
    return None


def whisper_transcribe(video, model, lang, workdir):
    py = whisper_python()
    if not py:
        return None, "faster-whisper not found (pip install faster-whisper)"
    wav = Path(workdir) / "audio_16k.wav"
    r = run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", str(wav)])
    if r.returncode != 0:
        return None, f"audio extraction failed: {r.stderr.strip()[-300:]}"
    r = run([py, "-c", WHISPER_CODE, str(wav), str(model), lang])
    if r.returncode != 0:
        return None, f"whisper failed: {r.stderr.strip()[-500:]}"
    return json.loads(r.stdout.strip().splitlines()[-1]), None


def write_transcript(segments, out_dir):
    txt = [f"[{fmt_clock(s['start'])} -> {fmt_clock(s['end'])}] {s['text']}" for s in segments]
    (out_dir / "transcript.txt").write_text("\n".join(txt) + ("\n" if txt else ""), encoding="utf-8")
    srt = [f"{i}\n{fmt_srt_time(s['start'])} --> {fmt_srt_time(s['end'])}\n{s['text']}\n"
           for i, s in enumerate(segments, 1)]
    (out_dir / "transcript.srt").write_text("\n".join(srt), encoding="utf-8")


# ---------- oEmbed (official metadata only) ----------

def tiktok_oembed(url, timeout=15):
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host not in OEMBED_HOSTS:
        return None, f"--url only accepts TikTok links for oEmbed, got host '{host}'"
    api = "https://www.tiktok.com/oembed?" + urllib.parse.urlencode({"url": url})
    try:
        with urllib.request.urlopen(urllib.request.Request(api, headers={"Accept": "application/json"}), timeout=timeout) as r:
            data = json.load(r)
    except Exception as e:  # metadata is optional: report and carry on
        return None, f"oEmbed failed: {e}"
    # as of 2026-10-30 TikTok's oEmbed returns no title or author any more, only the embed id
    keep = ("title", "author_name", "author_url", "thumbnail_url", "provider_name", "embed_product_id")
    return {k: data.get(k) for k in keep if data.get(k)}, None


# ---------- prompt ----------

def write_prompt(out_dir, meta):
    template = (HERE / "analysis_prompt.md").read_text(encoding="utf-8")
    sheets = ", ".join(meta["sheets"]) or "(aucune)"
    filled = (template
              .replace("{{SOURCE}}", meta["source"]["file"])
              .replace("{{DURATION}}", f"{meta['video']['duration']:.1f}")
              .replace("{{N_FRAMES}}", str(len(meta["frames"])))
              .replace("{{SHEETS}}", sheets)
              .replace("{{TRANSCRIPT_SOURCE}}", meta["transcript"]["source"])
              .replace("{{OCR}}", "ocr.txt" if meta["ocr"]["lines"] else "aucun texte lu (ou OCR désactivé)"))
    (out_dir / "analysis_prompt.md").write_text(filled, encoding="utf-8")


# ---------- main ----------

def tool_version(cmd):
    r = run(cmd) if shutil.which(cmd[0]) else None
    out = (r.stdout or r.stderr).strip().splitlines() if r else []
    return out[0] if out else None


def default_model():
    return str(LOCAL_WHISPER) if LOCAL_WHISPER.exists() else "small"


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("video", help="local video file")
    p.add_argument("--out", help="output folder (default: <stem>_for_claude next to the video)")
    p.add_argument("--subs", help="subtitle file (.srt/.vtt); default: a sidecar file next to the video")
    p.add_argument("--no-subs", action="store_true", help="ignore subtitle files, always use Whisper")
    p.add_argument("--no-transcript", action="store_true", help="skip the transcript")
    p.add_argument("--lang", default="auto", help="Whisper language: auto, en, fr... (default auto)")
    p.add_argument("--model", default=default_model(), help="Whisper model name or folder")
    p.add_argument("--min-frames", type=int, default=8)
    p.add_argument("--max-frames", type=int, default=36)
    p.add_argument("--every", type=float, default=4.0,
                   help="at most this many seconds between two frames, within --max-frames (default 4)")
    p.add_argument("--scene", type=float, default=0.30, help="ffmpeg scene-change threshold (0-1)")
    p.add_argument("--ocr-crop", type=parse_crop, default=None,
                   help="OCR area: none, top, middle, bottom or x,y,w,h (px or fractions)")
    p.add_argument("--ocr-lang", default="eng+fra")
    p.add_argument("--ocr-min-conf", type=float, default=70, help="Tesseract word confidence 0-100 (default 70)")
    p.add_argument("--no-ocr", action="store_true")
    p.add_argument("--url", help="TikTok URL of the same video, for official oEmbed metadata only")
    a = p.parse_args(argv)
    if re.match(r"^[a-z]+://", a.video, re.I):
        p.error("give a local file: this tool does not download videos (use --url for metadata)")
    if not 1 <= a.min_frames <= a.max_frames:
        p.error("need 1 <= --min-frames <= --max-frames")
    return a


def main(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    video = Path(a.video).resolve()
    if not video.exists():
        raise SystemExit(f"no such file: {video}")
    out = Path(a.out).resolve() if a.out else video.parent / f"{video.stem}_for_claude"
    out.mkdir(parents=True, exist_ok=True)
    info = probe(video)
    warnings = []

    # transcript: subtitles first, then Whisper
    transcript = {"source": "none", "language": None, "segments": 0}
    segments = []
    if not a.no_transcript:
        subs = None if a.no_subs else (Path(a.subs) if a.subs else find_sidecar_subtitles(video))
        if subs:
            segments = parse_subtitles(subs.read_text(encoding="utf-8", errors="replace"))
            transcript.update(source=f"subtitles ({subs.name})")
        if not segments and info["audio_codec"]:
            with tempfile.TemporaryDirectory() as tmp:
                res, err = whisper_transcribe(video, a.model, a.lang, tmp)
            if err:
                warnings.append(err)
            else:
                segments = res["segments"]
                transcript.update(source=f"whisper ({Path(a.model).name})", language=res["language"],
                                  language_probability=round(res["probability"], 3))
        elif not segments:
            warnings.append("no audio stream and no subtitles: no transcript")
        transcript["segments"] = len(segments)
        write_transcript(segments, out)

    # frames and sheets
    cuts = scene_changes(video, a.scene)
    picked = pick_timestamps(info["duration"], cuts, a.min_frames, a.max_frames, a.every)
    times = [t for t, _ in picked]
    frames = extract_frames(video, times, out / "frames")
    sheets = build_sheets(frames, times, out)

    # OCR
    ocr = {"lines": 0, "crop": None, "langs": None}
    if not a.no_ocr:
        langs = tesseract_langs(a.ocr_lang)
        if langs:
            ocr.update(lines=ocr_frames(frames, times, a.ocr_crop, langs, out / "ocr.txt", a.ocr_min_conf),
                       crop=list(a.ocr_crop) if a.ocr_crop else None, langs=langs)
        else:
            warnings.append("tesseract not found: no OCR")

    meta = {
        "source": {"file": video.name, "path": str(video)},
        "video": info,
        "transcript": transcript,
        "scene_cuts": len(cuts),
        "frames": [{"index": i, "time": round(t, 2), "clock": fmt_clock(t), "reason": r,
                    "file": f"frames/{f.name}", "sheet": f"sheet_{(i - 1) // 9 + 1:02d}.jpg"}
                   for i, ((t, r), f) in enumerate(zip(picked, frames), 1)],
        "sheets": [s.name for s in sheets],
        "ocr": ocr,
        "tools": {"ffmpeg": tool_version(["ffmpeg", "-version"]), "tesseract": tool_version(["tesseract", "--version"])},
        "warnings": warnings,
    }
    if a.url:
        oembed, err = tiktok_oembed(a.url)
        meta["oembed"] = oembed
        if err:
            warnings.append(err)
    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_prompt(out, meta)

    print(f"{video.name}: {info['duration']:.1f} s, {len(frames)} frames on {len(sheets)} sheet(s), "
          f"transcript {transcript['source']} ({transcript['segments']} segments), OCR {ocr['lines']} line(s)")
    for w in warnings:
        print(f"warning: {w}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
