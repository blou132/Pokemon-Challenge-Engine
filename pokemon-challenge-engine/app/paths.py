"""Installed resources are immutable; adventures live outside the application bundle."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import tempfile

from app.services.discovery_safety import local_path


APP_DIRECTORY = "Pokemon-Challenge-Engine"
PORTABLE_MARKER = "pce-portable.json"


def resource_dir() -> Path:
    # PyInstaller sets package __file__ below its resource directory as well.
    return Path(__file__).resolve().parent.parent


def installation_dir() -> Path:
    """Locate adjacent optional components without creating any user data."""
    return local_path(Path(sys.executable).parent) if getattr(sys, "frozen", False) else resource_dir()


@dataclass(frozen=True)
class AppPaths:
    resources: Path
    data: Path
    installation: Path
    portable: bool


def resolve_app_paths(data_dir: Path | None = None) -> AppPaths:
    resources = resource_dir()
    frozen = bool(getattr(sys, "frozen", False))
    installation = installation_dir()
    marker = installation / PORTABLE_MARKER
    portable = False
    if data_dir is not None:
        if not Path(data_dir).is_absolute():
            raise ValueError("Le dossier de données doit être un chemin absolu.")
        data = local_path(data_dir)
    elif marker.exists():
        marker = local_path(marker)
        if marker.stat().st_size > 1024 or json.loads(marker.read_text(encoding="utf-8-sig")) != {"schema_version": 1}:
            raise ValueError("Le marqueur portable est invalide. Restaurez pce-portable.json depuis l'archive.")
        data = local_path(installation / "user-data")
        portable = True
    elif frozen:
        folder = os.environ.get("LOCALAPPDATA")
        if not folder or not Path(folder).is_absolute():
            raise ValueError("Le dossier Windows LOCALAPPDATA est introuvable. Choisissez un dossier avec --data-dir.")
        data = local_path(Path(folder) / APP_DIRECTORY)
    else:
        # Preserve existing python -m app.main installations and their data.
        data = resources
    if frozen and (data == resources or data.is_relative_to(resources)):
        raise ValueError("Les données personnelles ne peuvent pas être enregistrées dans les ressources de l'application.")
    data.mkdir(parents=True, exist_ok=True)
    # Fail visibly instead of silently selecting another store and hiding runs.
    with tempfile.TemporaryFile(dir=data):
        pass
    return AppPaths(resources, data, installation, portable)
