#!/bin/bash
# SessionStart : outils de production Wide Margin.
# Rapide et sans effet pour les fils qui ne produisent pas (veille, Gmail, analyse) : une ligne d'état, rien d'installé.
# Installation (en arrière-plan, journal ~/.widemargin/install.log) seulement si l'un de ces signaux est présent :
#   - variable WIDEMARGIN_PROD=1 ;
#   - fichier marqueur ~/.widemargin/PROD ;
#   - l'identifiant de la session figure dans /mnt/project-files/automatisation/sessions-production.txt.
# Le fil de production attend ensuite la fin avec : .claude/hooks/widemargin-tools.sh wait
set -uo pipefail
ICI=$(cd "$(dirname "$0")" && pwd)
WM_HOME=${WIDEMARGIN_HOME:-$HOME/.widemargin}
ENTREE=$(cat 2>/dev/null || true)
SESSION=$(printf '%s' "$ENTREE" | python3 -c "import json,sys
try: print(json.load(sys.stdin).get('session_id',''))
except Exception: print('')" 2>/dev/null)

PROD=0
[ "${WIDEMARGIN_PROD:-}" = "1" ] && PROD=1
[ -f "$WM_HOME/PROD" ] && PROD=1
LISTE=/mnt/project-files/automatisation/sessions-production.txt
[ -n "$SESSION" ] && [ -f "$LISTE" ] && grep -qxF "$SESSION" "$LISTE" 2>/dev/null && PROD=1

# chemins des outils pour toute la session (les scripts du dépôt les lisent)
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export WM_HOME=\"$WM_HOME\""
    echo "export WM_PY_IMAGE=\"$WM_HOME/venv/bin/python\""
    echo "export WM_PY_VOIX=\"$WM_HOME/kt/bin/python\""
    echo "export WM_BLENDER=\"$WM_HOME/blender/blender\""
    echo "export WM_NODE_MODULES=\"$WM_HOME/node_modules\""
  } >> "$CLAUDE_ENV_FILE"
fi

ETAT=$("$ICI/widemargin-tools.sh" status)
if [ "$PROD" = "1" ] && echo "$ETAT" | grep -q "absent"; then
  mkdir -p "$WM_HOME"
  nohup setsid "$ICI/widemargin-tools.sh" install > /dev/null 2>&1 < /dev/null &
  echo "$ETAT"
  echo "Fil de production : installation des outils manquants lancée en arrière-plan. Attendre avec .claude/hooks/widemargin-tools.sh wait"
elif [ "$PROD" = "1" ]; then
  echo "$ETAT"
else
  echo "$ETAT (fil hors production : rien installé ; installer avec WIDEMARGIN_PROD=1 ou .claude/hooks/widemargin-tools.sh install)"
fi
exit 0
