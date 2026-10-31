"""Tests for video_to_claude.py.  Run: python3 -m unittest discover -s .claude/skills/video-to-claude/tests -v

The end-to-end tests build a 6 s synthetic video with ffmpeg (three coloured shots, "HELLO REEL" in the
lower third, a 440 Hz tone).  The Whisper test cuts 12 s from one of our own videos and is skipped when
faster-whisper is not installed.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
SCRIPT = SKILL / "video_to_claude.py"
REPO = SKILL.parents[2]
OWN_VIDEO = REPO / "videos" / "2026-10-29-nuclear-clock.mp4"
sys.path.insert(0, str(SKILL))
import video_to_claude as v2c  # noqa: E402

SRT = """1
00:00:00,500 --> 00:00:02,000
Hello <i>reel</i>

2
00:00:02,000 --> 00:00:04,250
Second line
"""

VTT = """WEBVTT

00:00.500 --> 00:02.000 align:start
Hello reel

00:02.000 --> 00:04.250
Hello reel

00:04.250 --> 00:05.000
<c.colorE5E5E5>Third</c> line
"""


def font_option():
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"):
        if Path(f).exists():
            return f":fontfile='{f.replace(':', chr(92) + ':')}'"
    return ""


def make_synthetic_video(path):
    text = f"drawtext=text='HELLO REEL':fontsize=72:fontcolor=white:x=(w-tw)/2:y=h*0.80{font_option()}"
    inputs = []
    for colour in ("red", "navy", "darkgreen"):
        inputs += ["-f", "lavfi", "-i", f"color=c={colour}:s=540x960:r=30:d=2,{text}"]
    inputs += ["-f", "lavfi", "-i", "sine=frequency=440:duration=6"]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs,
                    "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-map", "3:a",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)


def run_script(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


class TestHelpers(unittest.TestCase):
    def test_parse_srt(self):
        segs = v2c.parse_subtitles(SRT)
        self.assertEqual([s["text"] for s in segs], ["Hello reel", "Second line"])
        self.assertAlmostEqual(segs[1]["end"], 4.25)

    def test_parse_vtt_drops_tags_and_rolling_repeats(self):
        segs = v2c.parse_subtitles(VTT)
        self.assertEqual([s["text"] for s in segs], ["Hello reel", "Third line"])
        self.assertAlmostEqual(segs[0]["start"], 0.5)

    def test_time_formats(self):
        self.assertEqual(v2c.fmt_srt_time(3725.5), "01:02:05,500")
        self.assertEqual(v2c.fmt_clock(75.25), "01:15.2")
        self.assertAlmostEqual(v2c.parse_time("01:02:05,500"), 3725.5)

    def test_pick_fills_up_to_min_frames(self):
        picked = v2c.pick_timestamps(60.0, [], min_frames=8, max_frames=36)
        self.assertEqual(len(picked), 8)
        self.assertEqual(picked[0][1], "hook")
        times = [t for t, _ in picked]
        self.assertEqual(times, sorted(times))
        self.assertTrue(all(0 <= t < 60 for t in times))

    def test_pick_every_limits_gaps(self):
        picked = v2c.pick_timestamps(60.0, [], min_frames=8, max_frames=36, every=4.0)
        times = [0.0] + [t for t, _ in picked] + [60.0]
        self.assertLessEqual(max(b - a for a, b in zip(times, times[1:])), 4.0)
        self.assertLessEqual(len(picked), 36)

    def test_confident_words(self):
        tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
               "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t96.1\tHELLO\n"
               "5\t1\t1\t1\t1\t2\t0\t0\t10\t10\t31.0\tWwW\n"
               "5\t1\t1\t1\t1\t3\t0\t0\t10\t10\t88.0\tREEL\n")
        self.assertEqual(v2c.confident_words(tsv, 70), ["HELLO", "REEL"])

    def test_pick_caps_at_max_frames_and_keeps_hook(self):
        cuts = [i * 0.9 for i in range(1, 100)]
        picked = v2c.pick_timestamps(90.0, cuts, min_frames=8, max_frames=12)
        self.assertEqual(len(picked), 12)
        self.assertEqual(picked[0], (0.5, "hook"))
        self.assertEqual({r for _, r in picked[1:]}, {"scene"})

    def test_pick_skips_near_duplicate_cuts(self):
        picked = v2c.pick_timestamps(10.0, [2.0, 2.05, 2.1, 6.0], min_frames=1, max_frames=36)
        self.assertEqual([r for _, r in picked], ["hook", "scene", "scene"])

    def test_parse_crop(self):
        self.assertIsNone(v2c.parse_crop("none"))
        self.assertEqual(v2c.crop_box(v2c.parse_crop("bottom"), 1080, 1920), (0, 1280, 1080, 1920))
        self.assertEqual(v2c.crop_box(v2c.parse_crop("100,200,300,400"), 1080, 1920), (100, 200, 400, 600))
        with self.assertRaises(Exception):
            v2c.parse_crop("1,2,3")

    def test_refuses_urls(self):
        r = run_script("https://www.tiktok.com/@someone/video/1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("local file", r.stderr)

    def test_oembed_host_allowlist(self):
        data, err = v2c.tiktok_oembed("https://evil.example.com/@x/video/1")
        self.assertIsNone(data)
        self.assertIn("evil.example.com", err)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.video = cls.tmp / "synth.mp4"
        make_synthetic_video(cls.video)
        (cls.tmp / "synth.srt").write_text(SRT, encoding="utf-8")  # sidecar subtitles
        cls.out = cls.tmp / "out"
        cls.result = run_script(cls.video, "--out", cls.out, "--ocr-crop", "bottom", "--min-frames", "4", "--max-frames", "9")
        cls.meta = json.loads((cls.out / "meta.json").read_text(encoding="utf-8")) if (cls.out / "meta.json").exists() else None

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_runs(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_sidecar_subtitles_win_over_whisper(self):
        self.assertTrue(self.meta["transcript"]["source"].startswith("subtitles"))
        self.assertIn("Hello reel", (self.out / "transcript.txt").read_text(encoding="utf-8"))
        self.assertIn("-->", (self.out / "transcript.srt").read_text(encoding="utf-8"))

    def test_frames_cover_each_shot(self):
        frames = self.meta["frames"]
        self.assertTrue(4 <= len(frames) <= 9)
        self.assertGreaterEqual(self.meta["scene_cuts"], 2)
        for shot_start in (0.0, 2.0, 4.0):
            self.assertTrue(any(shot_start <= f["time"] < shot_start + 2 for f in frames), shot_start)
        for f in frames:
            self.assertTrue((self.out / f["file"]).exists())

    def test_sheets(self):
        from PIL import Image
        n = len(self.meta["frames"])
        self.assertEqual(len(self.meta["sheets"]), (n + 8) // 9)
        with Image.open(self.out / self.meta["sheets"][0]) as im:
            self.assertEqual(im.width, 3 * v2c.CELL_W)

    @unittest.skipUnless(shutil.which("tesseract"), "tesseract not installed")
    def test_ocr_reads_lower_third(self):
        self.assertEqual(self.meta["ocr"]["crop"], [0, 2 / 3, 1, 1 / 3])
        self.assertIn("HELLO", (self.out / "ocr.txt").read_text(encoding="utf-8").upper())

    def test_prompt_is_filled(self):
        prompt = (self.out / "analysis_prompt.md").read_text(encoding="utf-8")
        self.assertIn("synth.mp4", prompt)
        self.assertNotIn("{{", prompt)


@unittest.skipUnless(shutil.which("ffmpeg") and OWN_VIDEO.exists() and v2c.whisper_python(),
                     "needs ffmpeg, faster-whisper and videos/2026-10-29-nuclear-clock.mp4")
class TestWhisper(unittest.TestCase):
    def test_transcribes_our_own_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            clip = Path(tmp) / "clip.mp4"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(OWN_VIDEO), "-t", "12",
                            "-c", "copy", str(clip)], check=True)
            r = run_script(clip, "--out", Path(tmp) / "out", "--no-ocr", "--max-frames", "8")
            self.assertEqual(r.returncode, 0, r.stderr)
            meta = json.loads((Path(tmp) / "out" / "meta.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["transcript"]["source"].startswith("whisper"), meta["warnings"])
            self.assertEqual(meta["transcript"]["language"], "en")
            text = (Path(tmp) / "out" / "transcript.txt").read_text(encoding="utf-8").lower()
            self.assertIn("atomic clocks", text)


if __name__ == "__main__":
    unittest.main()
