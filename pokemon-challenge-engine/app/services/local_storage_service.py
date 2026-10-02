"""Inspect and remove only recognised PCE cache files after explicit confirmation."""

import hashlib
import json
from pathlib import Path
import re

from app.core.game_detector import GAME_CODE_PREFIXES
from app.services.discovery_safety import file_signature, local_path
from app.services.rom_preparation_service import CACHE_OWNER
from app.services.config_service import _invalid_constant, _strict_pairs


class LocalStorageService:
    LABELS = {"extracted_roms": "ROM extraites", "downloads": "Cache téléchargements",
              "sessions": "Anciennes sessions Lua arrêtées"}

    def __init__(self, base_dir: Path, journal=None):
        self.base_dir = local_path(base_dir)
        self.runtime = local_path(self.base_dir / "runtime")
        self.journal = journal or (lambda event, **details: None)

    @staticmethod
    def _children(directory):
        directory = local_path(directory)
        if not directory.is_dir():
            return []
        result = []
        for index, path in enumerate(directory.iterdir()):
            if index >= 10000:
                raise ValueError("Trop de fichiers locaux ; nettoyage automatique interrompu.")
            result.append(local_path(path))
        return result

    @staticmethod
    def _hash(path):
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()

    def _entries(self, kind, active_session=""):
        entries = []  # (owned directory or None, exactly owned files)
        if kind == "extracted_roms":
            root = local_path(self.runtime / "extracted-roms")
            for game in GAME_CODE_PREFIXES.values():
                for archive_dir in self._children(root / game):
                    if not re.fullmatch(r"[a-f0-9]{64}", archive_dir.name) or not archive_dir.is_dir():
                        continue
                    for folder in self._children(archive_dir):
                        if not re.fullmatch(r"[a-f0-9]{16}", folder.name) or not folder.is_dir():
                            continue
                        manifest = local_path(folder / "manifest.json")
                        if not manifest.is_file() or manifest.stat().st_size > 65536:
                            continue
                        try:
                            data = json.loads(manifest.read_text(encoding="utf-8"), object_pairs_hook=_strict_pairs,
                                              parse_constant=_invalid_constant)
                            if (data.get("owner") != CACHE_OWNER or data.get("complete") is not True
                                    or type(data.get("schema_version")) is not int or data.get("schema_version") != 1 or data.get("game_id") != game
                                    or data.get("archive_sha256") != archive_dir.name
                                    or hashlib.sha256(data["archive_member"].encode("utf-8")).hexdigest()[:16] != folder.name
                                    or data.get("member_sha256") != hashlib.sha256(data["archive_member"].encode("utf-8")).hexdigest()):
                                continue
                            name = data["rom_filename"]
                            if not isinstance(name, str) or Path(name).name != name or Path(name).suffix.lower() != ".nds":
                                continue
                            rom = local_path(folder / name)
                            children = self._children(folder)
                            if set(children) != {rom, manifest} or not rom.is_file():
                                continue
                            if rom.stat().st_size != data["rom_size"] or self._hash(rom) != data["rom_sha256"]:
                                continue
                            entries.append((folder, [rom, manifest]))
                        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
                            continue
        elif kind == "downloads":
            from app.services.trusted_download_service import LUA_ARCHIVE_SHA256, archive_is_trusted
            archive = local_path(self.runtime / "downloads" / f"lua-{LUA_ARCHIVE_SHA256}.7z")
            if archive_is_trusted(archive):
                entries.append((None, [archive]))
        elif kind == "sessions":
            root = local_path(self.runtime / "bridge")
            active_name = Path(active_session).name if active_session else ""
            for folder in self._children(root):
                if not folder.is_dir() or not re.fullmatch(r"[a-f0-9]{32}", folder.name) or folder.name == active_name:
                    continue
                try:
                    files = self._children(folder)
                    script = folder / "connect.lua"
                    if not (folder / "stop").is_file() or not script.is_file() or script.stat().st_size > 32768:
                        continue
                    if not script.read_text(encoding="utf-8").startswith("-- Charger ce fichier dans DeSmuME"):
                        continue
                    # Never discard an unacknowledged observation, even in a stopped session.
                    if any(path.name.startswith("observation-") for path in files):
                        continue
                    config = folder / "config.lua"
                    if config.exists() and (config.stat().st_size > 262144 or not config.read_text(encoding="utf-8").startswith(
                            "-- Configuration locale générée ; ne pas versionner.")):
                        continue
                    allowed = re.compile(r"(?:connect\.lua|config\.lua|stop|ack\.txt|sequence\.txt|pending-index\.txt|pending-\d+\.txt|snapshot-\d+\.json)")
                    if all(path.is_file() and allowed.fullmatch(path.name) for path in files):
                        entries.append((folder, files))
                except (OSError, ValueError):
                    # An unreadable or concurrently edited script is not a recognised
                    # disposable session; leave the complete directory untouched.
                    continue
        else:
            raise ValueError("Catégorie de stockage inconnue.")
        return entries

    def summary(self):
        result = []
        for kind, label in self.LABELS.items():
            entries = self._entries(kind)
            files = [path for _, paths in entries for path in paths]
            result.append({"kind": kind, "label": label, "bytes": sum(path.stat().st_size for path in files),
                           "count": len(entries)})
        return {"items": result, "message": "Seuls les fichiers PCE reconnus et nettoyables sont comptés. Profils, sauvegardes et backups conservés."}

    def cleanup(self, kind, *, confirmed=False, active_session=""):
        if confirmed is not True:
            raise ValueError("Le nettoyage exige une confirmation explicite.")
        entries = self._entries(kind, active_session)
        # Validate absolute targets and their signatures before any deletion.
        targets = []
        for folder, files in entries:
            for path in files:
                resolved = local_path(path)
                if not resolved.is_relative_to(self.runtime) or resolved == self.runtime:
                    raise ValueError("Nettoyage hors du stockage PCE refusé.")
                targets.append((resolved, file_signature(resolved)))
        self.journal("storage_cleanup_requested", kind=kind, files=[str(path) for path, _ in targets])
        removed = []
        try:
            for path, signature in targets:
                if file_signature(local_path(path)) != signature:
                    raise ValueError("Un fichier de cache a changé ; nettoyage arrêté.")
                path.unlink()  # No recursive deletion or computed external target.
                removed.append(str(path))
            for folder, _ in entries:
                if folder and local_path(folder).is_dir():
                    folder.rmdir()  # Refuses if a concurrent writer added anything.
        except (OSError, ValueError) as exc:
            try:
                self.journal("storage_cleanup_failed", kind=kind, removed=removed, error=str(exc))
            except (OSError, ValueError):
                pass  # Preserve the actual cleanup error if the local journal also fails.
            raise
        self.journal("storage_cleanup_completed", kind=kind, removed=removed)
        return {"kind": kind, "removed": removed, "count": len(entries)}
