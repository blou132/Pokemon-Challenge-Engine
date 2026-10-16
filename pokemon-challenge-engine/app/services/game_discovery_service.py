"""Catalogue d'en-têtes locaux dans des dossiers explicitement bornés."""

import json
from itertools import islice
import os
from pathlib import Path

from app.services.config_service import _invalid_constant, _strict_pairs
from app.services.discovery_models import GameCandidate
from app.services.discovery_safety import local_path
from app.services.rom_preparation_service import CACHE_OWNER, inspect_rom_source

MAX_SCAN_ENTRIES = 2048
MAX_SCAN_DIRECTORIES = 128


class GameDiscoveryService:
    def __init__(self, cache_root: Path | None = None) -> None:
        self.cache_root = local_path(cache_root) if cache_root is not None else None
        self.warnings: list[str] = []
        self.searched_directories: list[Path] = []

    def inspect(self, path: str | Path) -> tuple[GameCandidate, ...]:
        return inspect_rom_source(path)

    def _source_from_cache(self, path: Path) -> Path:
        if self.cache_root is None or not path.is_relative_to(self.cache_root):
            return path
        manifest_path = local_path(path.parent / "manifest.json")
        if not manifest_path.is_file() or manifest_path.stat().st_size > 65536:
            raise ValueError("Cache ROM sans manifeste : choisissez la source originale.")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"),
                                  object_pairs_hook=_strict_pairs, parse_constant=_invalid_constant)
            if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or \
                    manifest.get("schema_version") != 1 or manifest.get("owner") != CACHE_OWNER or manifest.get("complete") is not True or \
                    manifest.get("rom_filename") != path.name:
                raise ValueError("Manifeste de cache invalide")
            return local_path(manifest["source_path"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
            raise ValueError("Source du cache ROM inconnue ; sélectionnez la ROM ou le ZIP d'origine.") from exc

    def _scan_paths(self, directories, include_subdirectories):
        # All roots precede their children, so overlapping roots retain their own depth.
        pending = [(raw, include_subdirectories) for raw in islice(directories, 32)]
        visited = set()
        entry_count = 0
        for raw, visit_children in pending:
            try:
                folder = local_path(raw)
                if folder in visited or (self.cache_root is not None and folder.is_relative_to(self.cache_root)):
                    continue
                if not folder.is_dir():
                    self.warnings.append(f"Dossier de jeux introuvable : {folder}")
                    continue
                if len(visited) >= MAX_SCAN_DIRECTORIES:
                    self.warnings.append(f"Recherche de jeux limitée à {MAX_SCAN_DIRECTORIES} dossiers.")
                    return
                visited.add(folder)
                # Empty folders matter: adding a ROM later must invalidate AutoSetup's cache.
                self.searched_directories.append(folder)
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if entry_count >= MAX_SCAN_ENTRIES:
                            self.warnings.append(f"Recherche de jeux limitée à {MAX_SCAN_ENTRIES} entrées au total.")
                            return
                        entry_count += 1
                        try:
                            if entry.is_file(follow_symlinks=False):
                                path = local_path(entry.path)
                                if path.suffix.lower() in {".nds", ".zip"}:
                                    yield path
                            elif visit_children and entry.is_dir(follow_symlinks=False):
                                child = local_path(entry.path)
                                if self.cache_root is None or not child.is_relative_to(self.cache_root):
                                    pending.append((child, False))
                        except (OSError, ValueError) as exc:
                            self.warnings.append(str(exc))
            except (OSError, ValueError) as exc:
                self.warnings.append(str(exc))

    def discover(self, directories, *, explicit_paths=(), include_subdirectories=False) -> tuple[GameCandidate, ...]:
        self.warnings.clear()
        self.searched_directories.clear()
        paths: dict[Path, None] = {}
        for raw in islice(explicit_paths, 128):
            if not str(raw).strip():
                continue
            try:
                paths[self._source_from_cache(local_path(raw))] = None
            except (OSError, ValueError) as exc:
                self.warnings.append(str(exc))
        for path in self._scan_paths(directories, include_subdirectories):
            paths[path] = None
        found = []
        for path in paths:
            try:
                found.extend(inspect_rom_source(path))
            except (OSError, ValueError) as exc:
                self.warnings.append(f"{path.name} : {exc}")
        return tuple(found)
