"""Bornes et primitives communes aux recherches locales, sans écriture externe."""

import hashlib
import os
from pathlib import Path


def local_path(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip() or "\0" in str(value):
        raise ValueError("Chemin local invalide.")
    path = Path(os.path.abspath(value))
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("Chemin avec lien ou jonction : sélection directe nécessaire.")
    return path


def file_signature(path: Path) -> tuple[int, int, int, int, int]:
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def bounded_files(folder: Path, limit: int = 2048):
    """Seulement les enfants directs. Une bibliothèque volumineuse reste bornée."""
    with os.scandir(folder) as entries:
        for count, entry in enumerate(entries):
            if count >= limit:
                raise ValueError(f"Dossier trop volumineux : recherche limitée à {limit} entrées.")
            if entry.is_file(follow_symlinks=False):
                yield local_path(entry.path)
