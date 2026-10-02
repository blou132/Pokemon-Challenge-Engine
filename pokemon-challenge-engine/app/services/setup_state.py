"""Local setup provenance, kept separate from the legacy configuration format."""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile

from app.services.config_service import _strict_pairs, _invalid_constant
from app.models.profile import validate_json_data
from app.services.discovery_safety import local_path


class SetupStateStore:
    def __init__(self, base_dir: Path):
        self.path = local_path(Path(base_dir) / "setup.local.json")
        self._loaded = None
        self._valid_loaded = False

    def load(self):
        local_path(self.path)
        self._valid_loaded = False
        if self.path.exists() and self.path.stat().st_size > 4_000_000:
            raise ValueError("Le diagnostic enregistré est trop volumineux ; fichier conservé.")
        self._loaded = self.path.read_bytes() if self.path.exists() else None
        if self._loaded is None:
            self._valid_loaded = True
            return {"schema_version": 1, "first_run_done": False, "retrobat_root": "", "games": {}}
        try:
            if len(self._loaded) > 4_000_000:
                raise ValueError("Fichier trop volumineux")
            data = json.loads(self._loaded.decode("utf-8"), object_pairs_hook=_strict_pairs,
                              parse_constant=_invalid_constant)
            self._validate(data)
            self._valid_loaded = True
            return data
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            raise ValueError("Le diagnostic enregistré est illisible ; fichier conservé. Vérifiez setup.local.json.") from exc

    @staticmethod
    def _validate(data):
        validate_json_data(data)
        if (not isinstance(data, dict) or set(data) != {"schema_version", "first_run_done", "retrobat_root", "games"}
                or type(data["schema_version"]) is not int or data["schema_version"] != 1
                or type(data["first_run_done"]) is not bool or not isinstance(data["retrobat_root"], str)
                or not isinstance(data["games"], dict)):
            raise ValueError("Format du diagnostic inconnu.")
        from app.core.game_detector import GAME_CODE_PREFIXES
        if set(data["games"]) - set(GAME_CODE_PREFIXES.values()):
            raise ValueError("Jeu inconnu dans le diagnostic.")
        if len(data["retrobat_root"]) > 4096 or "\0" in data["retrobat_root"]:
            raise ValueError("Chemin RetroBat invalide.")
        for entry in data["games"].values():
            required = {"source_path", "archive_member", "prepared_path", "emulator_path", "save_path", "fingerprints"}
            if (not isinstance(entry, dict) or set(entry) != required
                    or any(not isinstance(entry[key], str) for key in required - {"fingerprints", "archive_member"})
                    or not (entry["archive_member"] is None or isinstance(entry["archive_member"], str))
                    or not isinstance(entry["fingerprints"], dict)):
                raise ValueError("Provenance de jeu invalide.")
            for key in required - {"fingerprints"}:
                value = entry[key]
                if value is not None and (len(value) > 4096 or "\0" in value):
                    raise ValueError("Chemin de provenance invalide.")
            if len(entry["fingerprints"]) > 64:
                raise ValueError("Trop d'empreintes dans le diagnostic.")
            for path, fingerprint in entry["fingerprints"].items():
                if not isinstance(path, str) or not path or len(path) > 4096 or "\0" in path:
                    raise ValueError("Chemin d'empreinte invalide.")
                if fingerprint is None:
                    continue
                if (not isinstance(fingerprint, dict) or set(fingerprint) != {"size", "mtime_ns", "sha256"}
                        or any(type(fingerprint[key]) is not int or fingerprint[key] < 0 for key in ("size", "mtime_ns"))
                        or not isinstance(fingerprint["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint["sha256"])):
                    raise ValueError("Empreinte de fichier invalide.")

    def save(self, data):
        self._validate(data)
        local_path(self.path)
        if self.path.exists() and not self._valid_loaded:
            raise ValueError("Diagnostic existant non validé : fichier conservé, rechargez ou rétablissez-le avant enregistrement.")
        raw = self.path.read_bytes() if self.path.exists() else None
        if raw != self._loaded:
            raise ValueError("Le diagnostic a changé dans une autre instance ; relancez la détection.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".setup.local.", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if (self.path.read_bytes() if self.path.exists() else None) != raw:
                raise ValueError("Le diagnostic a changé pendant l'enregistrement.")
            temporary.replace(self.path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        self._loaded = payload
        self._valid_loaded = True
        return deepcopy(data)
