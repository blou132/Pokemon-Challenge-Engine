"""Résultats de découverte locale : identité d'en-tête, jamais preuve d'intégrité."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RetroBatInstallation:
    root: Path
    roms_directory: Path
    emulators_directory: Path


@dataclass(frozen=True, slots=True)
class GameCandidate:
    source_path: Path
    archive_member: str | None
    game_id: str
    game_code: str
    region: str
    revision: int
    size: int
    source_kind: str
    requires_choice: bool = False

    @property
    def candidate_id(self) -> str:
        value = os.path.normcase(str(self.source_path)) + "\0" + (self.archive_member or "")
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedRom:
    path: Path
    game_id: str
    game_code: str
    region: str
    revision: int
    source_path: Path
    archive_member: str | None
    archive_sha256: str | None
    rom_sha256: str
    reused: bool
    manifest_path: Path | None


@dataclass(frozen=True, slots=True)
class SaveCandidate:
    path: Path
    size: int
    modified_at: str
    confidence: str
    reason: str
    compatible: bool = True
