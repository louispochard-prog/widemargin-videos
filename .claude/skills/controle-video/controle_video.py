#!/usr/bin/env python3
"""Contrôle d'une vidéo Wide Margin en une commande.

usage : python3 controle_video.py <video.mp4> [script.json] [--sortie DOSSIER] [--sans-transcription]

Points vérifiés (rapport OK/ÉCHEC, aussi écrit dans <sortie>/rapport_controle.txt) :
  1. durée entre 61 et 90 s (ffprobe)
  2. taille < 50 Mo
  3. format 1080x1920, H.264 yuv420p, AAC, faststart (moov avant mdat)
  4. zone sûre : 20 images extraites -> planche_contact.png + zone_sure.png
     (masque fait par /mnt/project-files/videos-v2/monty-hall/zone_sure_tiktok.py)
  5. transcription faster-whisper (modèle /mnt/project-files/modeles/faster-whisper-small) comparée au script
Le point 4 se juge à l'œil : ouvrir planche_contact.png et zone_sure.png.
Code retour : 0 si tout est OK, 1 sinon.
"""
import glob
import json
import os
import re
import struct
import subprocess
import sys
from difflib import SequenceMatcher

ICI = os.path.dirname(os.path.abspath(__file__))
ZONE_SURE = "/mnt/project-files/videos-v2/monty-hall/zone_sure_tiktok.py"
WHISPER = "/mnt/project-files/modeles/faster-whisper-small"
LIMITE_TAILLE = 50_000_000
SEUIL_TRANSCRIPTION = 0.85  # similarité mot à mot minimale entre transcription et script


def interpreteur(nom_venv, test):
    """Python d'un venv de production : $WM_PY_*, puis ~/.widemargin, puis les venvs des scratchpads."""
    env = {"venv": "WM_PY_IMAGE", "kt": "WM_PY_VOIX"}[nom_venv]
    wm = os.environ.get("WM_HOME", os.path.expanduser("~/.widemargin"))
    cands = [os.environ.get(env, ""), f"{wm}/{nom_venv}/bin/python"]
    cands += sorted(glob.glob(f"/tmp/claude-0/*/*/scratchpad/{nom_venv}/bin/python"))
    for c in cands:
        if c and os.path.exists(c):
            if subprocess.run([c, "-c", test], capture_output=True).returncode == 0:
                return c
    return None


def ffprobe(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration,size:stream=codec_type,codec_name,width,height,pix_fmt,sample_rate",
                        "-of", "json", video], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def faststart(video):
    """Vrai si l'atome moov précède mdat au premier niveau du fichier."""
    with open(video, "rb") as f:
        pos, taille_fichier = 0, os.path.getsize(video)
        while pos < taille_fichier:
            f.seek(pos)
            tete = f.read(16)
            if len(tete) < 8:
                return False
            taille, typ = struct.unpack(">I4s", tete[:8])
            if taille == 1:
                taille = struct.unpack(">Q", tete[8:16])[0]
            elif taille == 0:
                taille = taille_fichier - pos
            if typ == b"moov":
                return True
            if typ == b"mdat":
                return False
            pos += taille
    return False


UNITES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
DIZAINES = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def en_lettres(n):
    if n < 20:
        return UNITES[n]
    if n < 100:
        return DIZAINES[n // 10] + ("" if n % 10 == 0 else " " + UNITES[n % 10])
    for v, mot in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand"), (100, "hundred")):
        if n >= v:
            reste = n % v
            return en_lettres(n // v) + " " + mot + ("" if reste == 0 else " " + en_lettres(reste))
    return str(n)


def mots(texte):
    texte = texte.lower().replace("’", "'")
    texte = re.sub(r"(?<=\d),(?=\d{3})", "", texte)
    texte = re.sub(r"\d+", lambda m: en_lettres(int(m.group())) if len(m.group()) < 12 else m.group(), texte)
    texte = texte.replace("-", " ").replace("%", " percent")
    return re.findall(r"[a-z0-9']+", texte)


def texte_script(chemin):
    data = json.load(open(chemin, encoding="utf-8"))
    segs = data if isinstance(data, list) else data.get("segments", [])
    return " ".join(s.get("text") or s.get("tts", "") for s in segs)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    video = os.path.abspath(args[0])
    script = next((a for a in args[1:] if a.endswith(".json")), None)
    if script is None:
        cand = os.path.join(os.path.dirname(video), "script.json")
        script = cand if os.path.exists(cand) else None
    sortie = args[args.index("--sortie") + 1] if "--sortie" in args else os.path.join(os.path.dirname(video), "controle")
    os.makedirs(sortie, exist_ok=True)
    rapport = []

    def note(ok, point, detail):
        rapport.append((ok, point, detail))

    info = ffprobe(video)
    duree = float(info["format"]["duration"])
    taille = int(info["format"]["size"])
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), {})
    note(61 <= duree <= 90, "Durée 61-90 s", f"{duree:.1f} s")
    note(taille < LIMITE_TAILLE, "Taille < 50 Mo", f"{taille / 1e6:.1f} Mo")
    fmt_ok = (v.get("width"), v.get("height"), v.get("codec_name"), v.get("pix_fmt"), a.get("codec_name")) == (1080, 1920, "h264", "yuv420p", "aac")
    fs = faststart(video)
    note(fmt_ok and fs, "Format 1080x1920 H.264 yuv420p + AAC + faststart",
         f"{v.get('width')}x{v.get('height')} {v.get('codec_name')} {v.get('pix_fmt')} / audio {a.get('codec_name')} {a.get('sample_rate')} Hz / faststart {'oui' if fs else 'NON'}")

    # 4. images, planche contact, masque de zone sûre
    images = os.path.join(sortie, "images")
    os.makedirs(images, exist_ok=True)
    for f in glob.glob(os.path.join(images, "*.png")):
        os.remove(f)
    for i in range(20):
        t = 0.6 + i * (duree - 1.2) / 19
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
                        os.path.join(images, f"f_{i:02d}_{t:05.2f}s.png")], check=True)
    py_image = interpreteur("venv", "import PIL")
    if py_image:
        planche = os.path.join(sortie, "planche_contact.png")
        masque = os.path.join(sortie, "zone_sure.png")
        r1 = subprocess.run([py_image, os.path.join(ICI, "planche.py"), os.path.join(images, "*.png"), planche, "10"], capture_output=True, text=True)
        r2 = subprocess.run([py_image, ZONE_SURE, os.path.join(images, "*.png"), masque, "10"], capture_output=True, text=True)
        ok = r1.returncode == 0 and r2.returncode == 0
        note(ok, "Zone sûre (à juger à l'œil)", f"{planche} et {masque}" if ok else (r1.stderr + r2.stderr)[-300:])
    else:
        note(False, "Zone sûre (à juger à l'œil)", "aucun Python avec PIL trouvé (lancer .claude/hooks/widemargin-tools.sh install)")

    # 5. transcription
    if "--sans-transcription" in args:
        note(True, "Transcription", "non faite (--sans-transcription)")
    elif not script:
        note(False, "Transcription", "script.json introuvable : passer son chemin en 2e argument")
    else:
        py_voix = interpreteur("kt", "import faster_whisper")
        if not py_voix:
            note(False, "Transcription", "faster-whisper introuvable (lancer .claude/hooks/widemargin-tools.sh install)")
        else:
            wav = os.path.join(sortie, "controle.wav")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", video, "-ac", "1", "-ar", "16000", wav], check=True)
            code = ("import sys, soundfile as sf\nfrom faster_whisper import WhisperModel\n"
                    f"m = WhisperModel({WHISPER!r}, device='cpu', compute_type='int8')\n"
                    "a, sr = sf.read(sys.argv[1], dtype='float32')\nsegs, _ = m.transcribe(a, language='en')\n"
                    "print(' '.join(s.text.strip() for s in segs))")
            r = subprocess.run([py_voix, "-c", code, wav], capture_output=True, text=True)
            transcrit = r.stdout.strip()
            open(os.path.join(sortie, "transcription_controle.txt"), "w").write(transcrit + "\n")
            attendu = mots(texte_script(script))
            obtenu = mots(transcrit)
            sm = SequenceMatcher(None, attendu, obtenu, autojunk=False)
            sim = sm.ratio()
            ecarts = []
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op != "equal" and len(ecarts) < 12:
                    ecarts.append(f"« {' '.join(attendu[i1:i2])} » -> « {' '.join(obtenu[j1:j2])} »")
            note(sim >= SEUIL_TRANSCRIPTION, f"Transcription (similarité ≥ {SEUIL_TRANSCRIPTION:.0%})",
                 f"{sim:.1%} de mots concordants, écart {1 - sim:.1%}" + (" ; écarts : " + " ; ".join(ecarts) if ecarts else ""))

    lignes = [f"Contrôle de {video}"]
    lignes += [f"[{'OK' if ok else 'ÉCHEC'}] {p} : {d}" for ok, p, d in rapport]
    tout_ok = all(ok for ok, _, _ in rapport)
    lignes.append("RÉSULTAT : " + ("OK" if tout_ok else "ÉCHEC") + " (la zone sûre reste à vérifier à l'œil sur la planche et le masque)")
    texte = "\n".join(lignes)
    open(os.path.join(sortie, "rapport_controle.txt"), "w").write(texte + "\n")
    print(texte)
    return 0 if tout_ok else 1


if __name__ == "__main__":
    sys.exit(main())
