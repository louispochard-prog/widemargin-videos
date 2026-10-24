---
name: controle-video
description: Contrôle final d'une vidéo Wide Margin en une commande (durée 61-90 s, taille < 50 Mo, format 1080x1920 H.264/AAC/faststart, planche contact et masque de zone sûre TikTok, transcription faster-whisper comparée au script). À lancer sur chaque mp4 avant de le livrer, de le pousser ou de le programmer dans Buffer.
---

# Contrôle d'une vidéo Wide Margin

## 1. Lancer le contrôle

```bash
python3 "$CLAUDE_PROJECT_DIR/.claude/skills/controle-video/controle_video.py" <video.mp4> [script.json] [--sortie DOSSIER]
```

- `script.json` : le script de la vidéo (format `banque-sujets/scripts/*.json`). S'il n'est pas donné, le script cherche `script.json` à côté du mp4.
- `--sortie` : dossier du rapport (défaut `controle/` à côté du mp4). Il contient `rapport_controle.txt`, `planche_contact.png`, `zone_sure.png`, `transcription_controle.txt` et `images/` (20 images extraites).
- `--sans-transcription` : saute la transcription (ex. vidéo sans voix).
- Durée : environ 2 min pour 90 s de vidéo, la transcription prend presque tout ce temps.
- Code retour : 0 si tout est OK, 1 sinon.

Le script ne recopie rien : le masque vient de `/mnt/project-files/videos-v2/monty-hall/zone_sure_tiktok.py` et la transcription du modèle `/mnt/project-files/modeles/faster-whisper-small`. Les interpréteurs Python sont cherchés dans `$WM_PY_IMAGE`/`$WM_PY_VOIX`, puis dans `~/.widemargin/{venv,kt}`, puis dans les venvs des scratchpads. S'il en manque un, lancer `.claude/hooks/widemargin-tools.sh install`.

## 2. Lire le rapport

Chaque point est noté OK ou ÉCHEC :
1. Durée entre 61 et 90 s.
2. Taille sous 50 Mo. Sinon, réencoder avec un crf plus haut.
3. 1080x1920, H.264 yuv420p, audio AAC, faststart (atome moov avant mdat ; sinon `-movflags +faststart`).
4. Zone sûre : la planche et le masque sont produits, le jugement reste visuel (étape 3).
5. Transcription : similarité mot à mot avec le champ `text` du script, après conversion des nombres en lettres. Le seuil est 85 %. Les écarts listés sont souvent de l'orthographe (noms propres, sigles épelés) : juger s'il s'agit d'un vrai mot manquant ou mal prononcé.

## 3. Regarder soi-même (obligatoire)

Ouvrir avec l'outil Read :
- `planche_contact.png` : texte coupé, carrés à la place de glyphes, chevauchements, image vide ou trop sombre, modèle 3D raté, mascotte masquée.
- `zone_sure.png` : aucun texte dans les bandes rouges (270 px du haut, 450 px du bas, droite de x = 896 entre y = 860 et y = 1490, marges latérales de 60 px). La boîte de la mascotte (x 760-1015, y 275-425) ne contient rien d'autre.

Une vidéo n'est livrée que si le rapport est OK ET si ce contrôle visuel ne montre rien à corriger. Corriger, refaire le rendu des morceaux touchés, puis relancer le contrôle.
