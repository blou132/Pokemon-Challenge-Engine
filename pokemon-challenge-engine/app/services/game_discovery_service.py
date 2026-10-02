"""Catalogue d'en-têtes locaux dans des dossiers explicitement bornés."""

import json
from pathlib import Path

from app.services.config_service import _invalid_constant, _strict_pairs
from app.services.discovery_models import GameCandidate
from app.services.discovery_safety import bounded_files, local_path
from app.services.rom_preparation_service import CACHE_OWNER, inspect_rom_source


class GameDiscoveryService:
    def __init__(self, cache_root: Path | None = None) -> None:
        self.cache_root = local_path(cache_root) if cache_root is not None else None
        self.warnings: list[str] = []

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

    def discover(self, directories, *, explicit_paths=()) -> tuple[GameCandidate, ...]:
        self.warnings.clear()
        paths: dict[Path, None] = {}
        for raw in tuple(explicit_paths)[:128]:
            if not str(raw).strip():
                continue
            try:
                paths[self._source_from_cache(local_path(raw))] = None
            except (OSError, ValueError) as exc:
                self.warnings.append(str(exc))
        for raw in tuple(directories)[:32]:
            try:
                folder = local_path(raw)
                if self.cache_root is not None and folder.is_relative_to(self.cache_root):
                    continue
                if not folder.is_dir():
                    self.warnings.append(f"Dossier de jeux introuvable : {folder}")
                    continue
                for path in bounded_files(folder):
                    if path.suffix.lower() in {".nds", ".zip"}:
                        paths[self._source_from_cache(path)] = None
            except (OSError, ValueError) as exc:
                self.warnings.append(str(exc))
        found = []
        for path in paths:
            try:
                found.extend(inspect_rom_source(path))
            except (OSError, ValueError) as exc:
                self.warnings.append(f"{path.name} : {exc}")
        return tuple(found)
