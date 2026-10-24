#!/usr/bin/env python3
"""PreToolUse (Bash) : avant un `git commit` ou un `git push`, refuse si un mp4 qu'on s'apprête à envoyer dépasse 50 Mo.

Contrôlés :
- commit : les mp4 indexés (ajoutés ou modifiés), ceux passés à `git add` dans la même commande
  (y compris la destination d'un `cp`/`mv` fait juste avant), et les mp4 suivis modifiés si `commit -a` ;
- push : les mp4 ajoutés ou modifiés par les commits pas encore envoyés.
Les mp4 déjà publiés (même au-delà de 50 Mo) ne bloquent rien : on ne réécrit pas l'historique.
Sortie 2 = commande refusée, le message sur stderr est renvoyé à Claude.
"""
import json
import os
import re
import shlex
import subprocess
import sys

LIMITE = 50_000_000  # octets ; GitHub avertit au-delà de 50 Mo et refuse à 100 Mo
RE_GIT = re.compile(r"\bgit\b(?:\s+-C\s+\S+)?[^|;&]*?\b(commit|push)\b")


def git(rep, *args):
    r = subprocess.run(["git", "-C", rep, *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def morceaux(cmd):
    """Découpe une commande shell en sous-commandes (&&, ;, ||, |), chacune en liste de mots."""
    for bout in re.split(r"&&|\|\||;|\||\n", cmd):
        try:
            mots = shlex.split(bout)
        except ValueError:
            mots = bout.split()
        if mots:
            yield mots


def depot(cmd, cwd):
    """Répertoire du dépôt visé : dernier `cd` ou `git -C` avant le commit/push, sinon cwd."""
    rep = cwd
    for mots in morceaux(cmd):
        if mots[0] == "cd" and len(mots) > 1:
            rep = os.path.join(rep, os.path.expanduser(mots[1]))
        if mots[0] == "git" and len(mots) > 2 and mots[1] == "-C":
            rep = os.path.join(rep, os.path.expanduser(mots[2]))
        if mots[0] == "git" and any(m in ("commit", "push") for m in mots):
            break
    return rep


def taille_fichier(chemin):
    try:
        return os.path.getsize(chemin)
    except OSError:
        return None


def trop_gros(cmd, cwd):
    rep = depot(cmd, cwd)
    racine = git(rep, "rev-parse", "--show-toplevel").strip()
    if not racine:
        return []
    fautifs = {}
    copies = {}
    cwd_courant = cwd
    for mots in morceaux(cmd):
        if mots[0] == "cd" and len(mots) > 1:
            cwd_courant = os.path.join(cwd_courant, os.path.expanduser(mots[1]))
        if mots[0] in ("cp", "mv"):
            args = [m for m in mots[1:] if not m.startswith("-")]
            if len(args) == 2 and args[1].lower().endswith(".mp4"):
                copies[os.path.normpath(os.path.join(cwd_courant, args[1]))] = os.path.join(cwd_courant, args[0])
        if mots[0] == "git" and "add" in mots:
            for m in mots[mots.index("add") + 1:]:
                if m.lower().endswith(".mp4"):
                    p = os.path.normpath(os.path.join(cwd_courant, m))
                    t = taille_fichier(copies.get(p, p))
                    if t is None:
                        t = taille_fichier(p)
                    if t and t > LIMITE:
                        fautifs[os.path.relpath(p, racine)] = t
    if re.search(r"\bcommit\b", cmd):
        noms = git(racine, "diff", "--cached", "--name-only", "--diff-filter=AM", "--", "*.mp4").split()
        if re.search(r"\bcommit\b[^|;&]*\s(-a|--all|-[a-zA-Z]*a[a-zA-Z]*)\b", cmd):
            noms += git(racine, "diff", "--name-only", "--diff-filter=M", "--", "*.mp4").split()
        for n in noms:
            t = taille_fichier(os.path.join(racine, n))
            if t and t > LIMITE:
                fautifs[n] = t
    if re.search(r"\bpush\b", cmd):
        amont = git(racine, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").strip()
        if not amont:
            branche = git(racine, "rev-parse", "--abbrev-ref", "HEAD").strip()
            for c in (f"origin/{branche}", "origin/main"):
                if git(racine, "rev-parse", "--verify", "--quiet", c).strip():
                    amont = c
                    break
        plage = f"{amont}..HEAD" if amont else "HEAD"
        for n in git(racine, "diff", "--name-only", "--diff-filter=AM", plage, "--", "*.mp4").split() if amont else []:
            t = git(racine, "cat-file", "-s", f"HEAD:{n}").strip()
            if t.isdigit() and int(t) > LIMITE:
                fautifs[n] = int(t)
    return sorted(fautifs.items())


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    cmd = data.get("tool_input", {}).get("command", "")
    if not isinstance(cmd, str) or not RE_GIT.search(cmd):
        return 0
    fautifs = trop_gros(cmd, data.get("cwd") or os.getcwd())
    if fautifs:
        liste = ", ".join(f"{n} ({t / 1e6:.1f} Mo)" for n, t in fautifs)
        print(f"Bloqué par garde_mp4 : mp4 au-delà de 50 Mo : {liste}. "
              "Réencoder avec un crf plus haut (ex. -crf 23 ou 24, même chaîne audio), "
              "vérifier la taille avec ffprobe, puis recommencer le commit/push.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
