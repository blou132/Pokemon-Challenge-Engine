"""Détecte des structures RetroBat à des emplacements précis, sans parcours récursif."""

import ctypes
import os
from pathlib import Path
from string import ascii_uppercase

from app.services.discovery_models import RetroBatInstallation
from app.services.discovery_safety import local_path


class RetroBatDiscoveryService:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    @staticmethod
    def _drives() -> tuple[Path, ...]:
        if os.name != "nt":
            return ()
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return tuple(Path(f"{letter}:/") for index, letter in enumerate(ascii_uppercase) if mask & (1 << index))

    def discover(self, configured_paths=(), *, drive_roots=None) -> tuple[RetroBatInstallation, ...]:
        self.warnings.clear()
        candidates: dict[Path, None] = {}
        for value in tuple(configured_paths)[:64]:
            if not str(value).strip():
                continue
            try:
                path = local_path(value)
                # Un chemin ROM ou émulateur enregistré peut retrouver son installation.
                start = path if path.is_dir() else path.parent
                for parent in (start, *tuple(start.parents)[:4]):
                    candidates[parent] = None
            except (OSError, ValueError) as exc:
                self.warnings.append(str(exc))
        for drive in (self._drives() if drive_roots is None else tuple(drive_roots)[:26]):
            try:
                candidates[local_path(Path(drive) / "RetroBat")] = None
            except (OSError, ValueError) as exc:
                self.warnings.append(str(exc))
        found = []
        for root in candidates:
            try:
                roms = local_path(root / "roms")
                emulators = local_path(root / "emulators")
                if root.is_dir() and roms.is_dir() and emulators.is_dir():
                    found.append(RetroBatInstallation(root, roms, emulators))
            except (OSError, ValueError) as exc:
                self.warnings.append(str(exc))
        return tuple(found)
