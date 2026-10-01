"""Vérifie les exclusions Git et repère les formats de secrets usuels.

Ne journalise jamais le contenu détecté : uniquement les noms de fichiers.
Ce contrôle complète la revue humaine ; aucun détecteur ne couvre tous les secrets.
"""

from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PROBES = (
    ".venv/test.txt", "nested/.venv/test.txt", "__pycache__/module.pyc",
    "nested/__pycache__/module.pyc", "game.nds", "nested/game.NDS",
    "game.nds.zip", "game.gba", "game.sav", "game.SAV", "game.dsv",
    "game.dsv.bak", "game.ds0", "config.json", "nested/config.json",
    "logs/app.log", "nested/logs/app.log", ".env", "nested/.env.production",
    "secrets.json", "nested/credentials.json", "private.pem",
    "diagnostic.log", "nested/debug.log.1", "settings.local.toml", "desmume.ini",
    "archive.ZIP", "game.7z", "game.rar", "DeSmuME.exe", "lua51.dll",
    "runtime/bridge/session/snapshot-0000000001.json",
    "pokemon-challenge-engine/profiles/run_001/challenge.json",
    "backups/pce-backups.json", "nested/backups/index.json", "desmume.ini.pce-backup.1",
    "game-mode.local.json", "controls.local.json", ".game-mode.local.example.tmp",
)
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{50,}"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}"),
)


def audit() -> list[str]:
    errors: list[str] = []
    for probe in PROBES:
        result = subprocess.run(["git", "check-ignore", "--quiet", "--", probe], cwd=ROOT, check=False)
        if result.returncode != 0:
            errors.append(f"Exclusion manquante : {probe}")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    for relative in filter(None, tracked):
        ignored = subprocess.run(["git", "check-ignore", "--no-index", "--quiet", "--", relative], cwd=ROOT, check=False)
        if ignored.returncode == 0:
            errors.append(f"Fichier local déjà versionné : {relative}")
        path = ROOT / relative
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".ico"}:
            continue
        if any(pattern.search(path.read_bytes()) for pattern in SECRET_PATTERNS):
            errors.append(f"Format de secret potentiel : {relative}")
    return errors


if __name__ == "__main__":
    problems = audit()
    print("\n".join(problems) if problems else "Audit Git : exclusions vérifiées, aucun fichier local interdit ni format de secret usuel détecté.")
    raise SystemExit(bool(problems))
