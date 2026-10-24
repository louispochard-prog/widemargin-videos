#!/usr/bin/env python3
"""PreToolUse (Bash, WebFetch, WebSearch) : bloque toute commande ou URL qui contient l'adresse e-mail du propriétaire.

L'adresse n'est pas écrite ici (dépôt public) : on compare l'empreinte SHA-256 de chaque adresse trouvée.
Bloque aussi, par prudence, toute adresse @icloud.com ou @gmail.com placée dans un en-tête User-Agent ou From.
Sortie 2 = appel refusé, le message sur stderr est renvoyé à Claude.
"""
import hashlib
import json
import re
import sys
from urllib.parse import unquote

# sha256 de l'adresse personnelle, en minuscules
EMPREINTES = {"52159cce952cd82faf1e8ef7b148ec0636fcd1d536245a595853b977a20f9a4e"}
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
RE_ENTETE = re.compile(r"(user-agent|from)\s*[:=][^\n]{0,200}?@(icloud|gmail)\.com", re.I)
RE_OPTION_UA = re.compile(r"(-A|--user-agent|-H|--header)\s+['\"]?[^'\"\n]{0,200}?@(icloud|gmail)\.com", re.I)
CONSEIL = ('Utiliser le User-Agent « WideMarginBot/1.0 (https://github.com/louispochard-prog/widemargin-videos) » '
           "et ne jamais mettre de donnée personnelle dans une requête (règle de RECETTE.md).")


def textes(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from textes(x)
    elif isinstance(v, list):
        for x in v:
            yield from textes(x)


def verdict(tool_input):
    for t in textes(tool_input):
        for brut in {t, unquote(t), unquote(unquote(t))}:
            for m in RE_EMAIL.findall(brut):
                if hashlib.sha256(m.lower().encode()).hexdigest() in EMPREINTES:
                    return "adresse e-mail personnelle du propriétaire détectée"
            if RE_ENTETE.search(brut) or RE_OPTION_UA.search(brut):
                return "adresse @icloud.com ou @gmail.com dans un en-tête User-Agent/From"
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    raison = verdict(data.get("tool_input", {}))
    if raison:
        print(f"Bloqué par garde_email : {raison}. {CONSEIL}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
