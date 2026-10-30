---
name: video-to-claude
description: Transforme un fichier vidéo (Reel, TikTok enregistré par le bouton natif, vidéo Wide Margin) en ce que Claude sait lire — transcript horodaté (sous-titres d'abord, Whisper sinon), planches 3x3 d'images numérotées, OCR recadrable, meta.json et prompt d'analyse prêt à coller. À utiliser pour analyser une vidéo concurrente ou une des nôtres.
---

# Vidéo -> fichiers lisibles par Claude

Claude ne lit ni la vidéo ni l'audio : ce skill produit du texte et des images à sa place.
Il part TOUJOURS d'un fichier local que Louis a le droit de garder (bouton de téléchargement natif de la plateforme, nos propres rendus). Il ne télécharge rien, n'utilise aucun cookie ni compte, et n'imite pas de navigateur : une URL passée en argument principal est refusée.

## 1. Lancer

```bash
python3 "$CLAUDE_PROJECT_DIR/.claude/skills/video-to-claude/video_to_claude.py" <video.mp4> [options]
```

Options utiles :
- `--out DOSSIER` : dossier de sortie (défaut `<nom>_for_claude/` à côté de la vidéo).
- `--subs fichier.srt|.vtt` : sous-titres fournis. Sans cette option, un `.srt`/`.vtt` de même nom posé à côté de la vidéo est pris automatiquement. `--no-subs` force Whisper.
- `--lang en|fr|auto` (défaut auto), `--model` (défaut : `/mnt/project-files/modeles/faster-whisper-small` s'il existe, sinon `small` téléchargé depuis Hugging Face).
- `--ocr-crop bottom|top|middle|x,y,w,h` : zone lue par l'OCR (pixels, ou fractions si toutes ≤ 1). `bottom` = tiers bas, là où sont les sous-titres incrustés. `--ocr-min-conf 70` : seuil de confiance des mots. `--no-ocr` pour sauter.
- `--min-frames 8 --max-frames 36 --every 4` : une image à l'accroche (0,5 s), une juste après chaque changement de plan, puis des images régulières pour qu'il n'y ait jamais plus de 4 s entre deux.
- `--url <lien TikTok>` : seulement les métadonnées oEmbed officielles. Au 30/10/2026, TikTok n'y renvoie plus ni titre ni auteur, seulement l'identifiant.

Durée : environ 35 s pour 90 s de vidéo sur 4 cœurs (Whisper small en int8 en prend la moitié).

Dépendances : ffmpeg, Python avec Pillow ; faster-whisper (dans ce Python, `$WM_PY_VOIX` ou `~/.widemargin/kt`) pour la transcription ; `tesseract-ocr` + `tesseract-ocr-fra` pour l'OCR. Sans Whisper ou sans Tesseract, le script continue et le signale dans `warnings` de meta.json.

## 2. Sorties

| Fichier | Contenu |
| --- | --- |
| `transcript.txt`, `transcript.srt` | Parole horodatée, source notée dans meta.json |
| `sheet_NN.jpg` | Planches 3x3, chaque case titrée `#NN mm:ss.s` au-dessus de l'image (rien n'est masqué) |
| `frames/frame_NN.jpg` | Images en pleine résolution, à ouvrir quand un détail est trop petit sur la planche |
| `ocr.txt` | Texte lu à l'écran par image, lignes identiques consécutives fusionnées |
| `meta.json` | Durée, format, liste des images (instant, raison : hook/scene/uniform, planche), source du transcript, versions |
| `analysis_prompt.md` | Prompt d'analyse en français, déjà rempli avec les noms de fichiers |

## 3. Analyser

- Dans Claude Code : lire `analysis_prompt.md`, puis `transcript.txt`, `ocr.txt` et chaque planche avec l'outil Read, et répondre au prompt.
- Dans l'app Claude (chat) : y glisser `analysis_prompt.md`, `transcript.txt`, `ocr.txt` et les planches (20 fichiers au plus par conversation).

L'OCR lit aussi le texte des graphismes : il reste du bruit, à croiser avec les planches avant de citer un chiffre.

## 4. Tests

```bash
python3 -m unittest discover -s "$CLAUDE_PROJECT_DIR/.claude/skills/video-to-claude/tests" -v
```

Une vidéo synthétique de 6 s (trois plans, « HELLO REEL » dans le tiers bas, un son de 440 Hz) vérifie les sous-titres, le choix des images, les planches, l'OCR et le prompt. Un test Whisper transcrit 12 s de `videos/2026-10-29-nuclear-clock.mp4` (ignoré si faster-whisper manque).

Piège connu : faster-whisper 1.2.1 plante avec PyAV 19 (constaté le 30/10/2026) quand on lui passe un chemin de fichier (`metadata_errors`). Le script lui passe donc le son déjà décodé en tableau.
