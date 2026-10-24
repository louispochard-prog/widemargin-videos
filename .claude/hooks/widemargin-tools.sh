#!/bin/bash
# Outils de production Wide Margin : état ou installation.
#   widemargin-tools.sh status    -> une ligne d'état (rapide, n'installe rien)
#   widemargin-tools.sh install   -> installe ce qui manque (bloquant, idempotent, journal dans $WM_HOME/install.log)
#   widemargin-tools.sh wait      -> attend la fin d'une installation lancée en arrière-plan
# Emplacements :
#   WM_HOME  (défaut ~/.widemargin) : venv (image : skia-python, numpy, PIL…), kt (voix Kyutai + faster-whisper),
#            blender (4.2.3), node_modules (three r169 ; Playwright est global dans l'image)
#   WM_CACHE (défaut /mnt/project-files/cache) : archives et paquets pip réutilisés d'un conteneur à l'autre
set -uo pipefail

WM_HOME=${WIDEMARGIN_HOME:-$HOME/.widemargin}
WM_CACHE=${WIDEMARGIN_CACHE:-/mnt/project-files/cache}
[ -d "$(dirname "$WM_CACHE")" ] || WM_CACHE=$WM_HOME/cache
BLENDER_TAR=blender-4.2.3-linux-x64.tar.xz
BLENDER_URL=https://download.blender.org/release/Blender4.2/$BLENDER_TAR
LOG=$WM_HOME/install.log
LOCK=$WM_HOME/install.lock

# contrôles rapides (présence des paquets, sans les importer : torch met plusieurs secondes à charger)
paquets() { local env=$1; shift; local p; for p in "$@"; do compgen -G "$WM_HOME/$env/lib/python3*/site-packages/$p" >/dev/null || return 1; done; }
ok_image() { [ -x "$WM_HOME/venv/bin/python" ] && paquets venv "skia*" numpy PIL soundfile.py fontTools scipy; }
ok_voix() { [ -x "$WM_HOME/kt/bin/python" ] && paquets kt torch moshi sphn faster_whisper librosa soundfile.py; }
ok_blender() { [ -x "$WM_HOME/blender/blender" ]; }
ok_three() { [ -f "$WM_HOME/node_modules/three/package.json" ]; }
ok_modeles() { [ -d /mnt/project-files/modeles/kyutai-tts-1.6b-en_fr ] && [ -d /mnt/project-files/modeles/faster-whisper-small ]; }

etat() {
  local s=""
  for c in image voix blender three; do
    if ok_$c; then s="$s $c:ok"; else s="$s $c:absent"; fi
  done
  ok_modeles && s="$s modeles:ok" || s="$s modeles:absents"
  [ -f "$LOCK" ] && s="$s (installation en cours, voir $LOG)"
  echo "Outils Wide Margin ($WM_HOME) :$s"
}

etape() {  # etape <nom> <commande...> : chronomètre et journalise
  local nom=$1; shift
  local t0=$SECONDS
  echo "[$(date -u +%FT%TZ)] début $nom" >> "$LOG"
  if "$@" >> "$LOG" 2>&1; then
    echo "[$(date -u +%FT%TZ)] fin $nom : OK en $((SECONDS - t0)) s" >> "$LOG"
  else
    echo "[$(date -u +%FT%TZ)] fin $nom : ÉCHEC après $((SECONDS - t0)) s" >> "$LOG"
    return 1
  fi
}

installer_image() {
  rm -rf "$WM_HOME/venv" && python3 -m venv "$WM_HOME/venv" &&
  PIP_CACHE_DIR=$WM_CACHE/pip "$WM_HOME/venv/bin/pip" install -q skia-python numpy pillow soundfile fonttools scipy
}

installer_voix() {
  rm -rf "$WM_HOME/kt" && python3 -m venv "$WM_HOME/kt" &&
  PIP_CACHE_DIR=$WM_CACHE/pip "$WM_HOME/kt/bin/pip" install -q torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu &&
  PIP_CACHE_DIR=$WM_CACHE/pip "$WM_HOME/kt/bin/pip" install -q moshi soundfile librosa faster-whisper
}

installer_blender() {
  mkdir -p "$WM_CACHE" &&
  { [ -s "$WM_CACHE/$BLENDER_TAR" ] || { curl -fsSL -A "WideMarginBot/1.0 (https://github.com/louispochard-prog/widemargin-videos)" -o "$WM_CACHE/$BLENDER_TAR.part" "$BLENDER_URL" && mv "$WM_CACHE/$BLENDER_TAR.part" "$WM_CACHE/$BLENDER_TAR"; }; } &&
  rm -rf "$WM_HOME/blender" "$WM_HOME/blender-4.2.3-linux-x64" &&
  tar -xJf "$WM_CACHE/$BLENDER_TAR" -C "$WM_HOME" && mv "$WM_HOME/blender-4.2.3-linux-x64" "$WM_HOME/blender"
}

installer_three() {
  cd "$WM_HOME" && npm install --silent --no-audit --no-fund three@0.169.0
}

installer() {
  mkdir -p "$WM_HOME" "$WM_CACHE"
  exec 9>"$LOCK.flock"
  flock -n 9 || { echo "Installation déjà en cours (voir $LOG)"; return 0; }
  touch "$LOCK"
  local t0=$SECONDS err=0
  ok_image || etape image installer_image || err=1
  ok_voix || etape voix installer_voix || err=1
  ok_blender || etape blender installer_blender || err=1
  ok_three || etape three installer_three || err=1
  echo "[$(date -u +%FT%TZ)] installation terminée en $((SECONDS - t0)) s (erreurs : $err)" >> "$LOG"
  rm -f "$LOCK"
  etat
  return $err
}

case "${1:-status}" in
  status) etat ;;
  install) installer ;;
  wait) while [ -f "$LOCK" ]; do sleep 5; done; etat ;;
  *) echo "usage : $0 status|install|wait" >&2; exit 1 ;;
esac
