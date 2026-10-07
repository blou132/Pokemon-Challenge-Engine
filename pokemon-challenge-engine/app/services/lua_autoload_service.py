"""Consent-based, reversible use of the documented Windows DeSmuME Lua autoload.

Only PCE's loader and two INI values are written. This service never launches a
process, runs Lua, reads ROM contents, or claims that a heartbeat was received.
"""

from dataclasses import dataclass
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from app.services.discovery_safety import local_path
from app.services.emulator_capabilities import detect_capabilities
from app.services.emulator_service import lua_literal
from app.services.emulator_settings_service import EmulatorSettingsService, IniDocument
from app.services.lua_runtime_installer import LuaRuntimeInstaller


_SESSION = re.compile(r"[0-9a-f]{32}\Z")
_KEYS = (("Scripting", "AutoLoad"), ("PathSettings", "Lua"))


@dataclass(frozen=True)
class LuaAutoLoadResult:
    enabled: bool = False
    loader_path: Path | None = None
    ini_path: Path | None = None
    backup_path: Path | None = None
    message: str = "Mode manuel conservé."


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Clé JSON dupliquée.")
        result[key] = value
    return result


def _manual_on_io_error(method):
    @wraps(method)
    def guarded(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (OSError, UnicodeError) as exc:
            raise ValueError("Accès aux fichiers Lua impossible ; mode manuel requis. "
                             "La configuration et les backups existants sont conservés.") from exc
    return guarded


class LuaAutoLoadService:
    def __init__(self, base_dir: Path, *, running_probe=None):
        self.base_dir = local_path(base_dir)
        self.state_path = local_path(self.base_dir / "lua-autoload.local.json")
        self.loader_root = local_path(self.base_dir / "runtime" / "lua-autoload")
        self.running_probe = running_probe

    @staticmethod
    def _identity(executable) -> tuple[Path, str, str]:
        exe = local_path(executable)
        if not exe.is_file() or exe.suffix.lower() != ".exe":
            raise ValueError("Exécutable DeSmuME introuvable.")
        capabilities = detect_capabilities(exe)
        fingerprint = capabilities.fingerprint
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError("Empreinte DeSmuME indisponible.")
        identity = os.path.normcase(str(exe)) + "\n" + fingerprint
        return exe, fingerprint, hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _read_state(self):
        path = local_path(self.state_path)
        if not path.exists():
            return {"schema_version": 1, "executables": {}}, None
        try:
            raw = path.read_bytes()
            if len(raw) > 1024 * 1024:
                raise ValueError("Journal trop volumineux.")
            data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
            if (not isinstance(data, dict) or set(data) != {"schema_version", "executables"}
                    or type(data["schema_version"]) is not int or data["schema_version"] != 1
                    or not isinstance(data["executables"], dict) or len(data["executables"]) > 512):
                raise ValueError("Format de journal invalide.")
            for key, entry in data["executables"].items():
                if (not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{64}", key) is None
                        or not isinstance(entry, dict) or set(entry) != {"path", "fingerprint", "consent", "managed"}
                        or type(entry["consent"]) is not bool or not isinstance(entry["path"], str)
                        or not entry["path"] or any(c in entry["path"] for c in "\r\n\0")
                        or not isinstance(entry["fingerprint"], str)
                        or re.fullmatch(r"[0-9a-f]{64}", entry["fingerprint"]) is None):
                    raise ValueError("Consentement invalide.")
                identity = os.path.normcase(entry["path"]) + "\n" + entry["fingerprint"]
                if hashlib.sha256(identity.encode("utf-8")).hexdigest() != key:
                    raise ValueError("Identité du consentement invalide.")
                managed = entry["managed"]
                if managed is not None:
                    if (not isinstance(managed, dict) or set(managed) != {"original", "folders", "backup"}
                            or not isinstance(managed["original"], list) or len(managed["original"]) != 2
                            or not isinstance(managed["folders"], list) or not 1 <= len(managed["folders"]) <= 2
                            or not isinstance(managed["backup"], str)):
                        raise ValueError("Restauration invalide.")
                    for (section, name), line in zip(_KEYS, managed["original"]):
                        IniDocument(b"").restore_entry(section, name, line)
                    for folder in managed["folders"]:
                        if not isinstance(folder, str):
                            raise ValueError("Dossier géré invalide.")
                        candidate = local_path(folder)
                        if candidate.parent != self.loader_root or _SESSION.fullmatch(candidate.name) is None:
                            raise ValueError("Dossier de restauration hors de PCE.")
            return data, raw
        except (OSError, ValueError, UnicodeError, RecursionError) as exc:
            raise ValueError("Journal Lua illisible ; fichier conservé, mode manuel requis.") from exc

    @staticmethod
    def _atomic_write(path: Path, content: bytes, *, expected: bytes | None = None, compare=False):
        path = local_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".lua-autoload.local.",
                                             suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if compare:
                current = path.read_bytes() if path.exists() else None
                if current != expected:
                    raise ValueError("Le journal Lua a changé ; recommencez.")
            local_path(path)
            temporary.replace(path)
        except OSError as exc:
            raise ValueError("Fichier Lua non enregistré : accès refusé ou fichier verrouillé.") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _save_state(self, data, original):
        raw = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        self._atomic_write(self.state_path, raw, expected=original, compare=True)

    @_manual_on_io_error
    def consent_status(self, executable) -> bool | None:
        _, _, key = self._identity(executable)
        data, _ = self._read_state()
        entry = data["executables"].get(key)
        return entry["consent"] if entry is not None else None

    @_manual_on_io_error
    def record_consent(self, executable, accepted: bool):
        if type(accepted) is not bool:
            raise ValueError("Consentement Lua invalide.")
        exe, fingerprint, key = self._identity(executable)
        data, raw = self._read_state()
        entry = data["executables"].setdefault(key, {
            "path": str(exe), "fingerprint": fingerprint, "consent": accepted, "managed": None,
        })
        entry["consent"] = accepted
        self._save_state(data, raw)

    def _loader(self, rom_path, connect_script, session_id) -> tuple[Path, bytes]:
        rom, script = local_path(rom_path), local_path(connect_script)
        identifier = script.parent.name if session_id is None else session_id
        if not isinstance(identifier, str) or _SESSION.fullmatch(identifier) is None:
            raise ValueError("Identifiant de session Lua invalide.")
        expected = local_path(self.base_dir / "runtime" / "bridge" / identifier / "connect.lua")
        if script != expected or not script.is_file() or not (script.parent / "config.lua").is_file():
            raise ValueError("Le script ne correspond pas à la session Bridge préparée.")
        local_path(script.parent / "config.lua")
        if local_path(script.parent / "stop").exists():
            raise ValueError("Cette ancienne session Lua est arrêtée ; préparez une nouvelle connexion.")
        if not rom.is_file() or rom.suffix.lower() != ".nds" or not rom.stem.strip():
            raise ValueError("La ROM préparée .nds est introuvable.")
        loader = local_path(self.loader_root / identifier / (rom.stem + ".lua"))
        if loader.parent.parent != self.loader_root:
            raise ValueError("Dossier de loader invalide.")
        try:
            # path.cpp uses MAX_PATH and narrow fopen; refuse silent truncation.
            if any(len(str(path).encode("mbcs" if os.name == "nt" else "utf-8")) >= 260
                   or len(str(path).encode("utf-16-le")) // 2 >= 260 for path in (loader, script)):
                raise ValueError("Chemin Lua trop long pour cet autoload DeSmuME ; mode manuel requis.")
            content = ("-- Pokemon Challenge Engine : loader local de session.\n"
                       + "dofile(" + lua_literal(script) + ")\n").encode("ascii")
        except UnicodeError as exc:
            raise ValueError("Chemin Lua non représentable par ce DeSmuME ; mode manuel requis.") from exc
        if loader.exists() and (not loader.is_file() or loader.read_bytes() != content):
            raise ValueError("Un autre fichier existe à la place du loader PCE ; fichier conservé.")
        return loader, content

    @staticmethod
    def _original_matches(document, managed):
        original = IniDocument(b"")
        for (section, name), line in zip(_KEYS, managed["original"]):
            original.restore_entry(section, name, line)
        return (document.get_int("Scripting", "AutoLoad", 0) == original.get_int("Scripting", "AutoLoad", 0)
                and document.get_text("PathSettings", "Lua") == original.get_text("PathSettings", "Lua"))

    @classmethod
    def _managed_matches(cls, document, managed):
        if cls._original_matches(document, managed):
            return True  # Previous preparation/restoration interrupted before INI commit.
        return (document.get_int("Scripting", "AutoLoad", 0) == 1
                and document.get_text("PathSettings", "Lua") in managed["folders"])

    def _settings(self, exe):
        service = EmulatorSettingsService(exe, running_probe=self.running_probe)
        if not detect_capabilities(exe).known_build:
            raise ValueError("Autoload non vérifié pour ce build DeSmuME ; mode manuel requis.")
        path = local_path(service._path())
        service._guard_stopped()
        raw = path.read_bytes()
        document = IniDocument(raw)
        document.require_windows_profile_encoding()
        return service, path, raw, document

    @_manual_on_io_error
    def prepare(self, executable, rom_path, connect_script, session_id=None, *, configure_ini=True) -> LuaAutoLoadResult:
        exe, _, key = self._identity(executable)
        loader, content = self._loader(rom_path, connect_script, session_id)
        if not configure_ini:
            if not loader.exists():
                self._atomic_write(loader, content, expected=None, compare=True)
            return LuaAutoLoadResult(loader_path=loader, message=(
                "Nouveau loader préparé sans modifier DeSmuME. Chargez manuellement le nouveau connect.lua ; "
                "l'autoload se déclenche au prochain chargement de ROM, pas pendant la session active."))
        data, original_state = self._read_state()
        entry = data["executables"].get(key)
        if entry is None or entry["consent"] is not True:
            raise ValueError("L'autoload Lua nécessite votre accord ; mode manuel conservé.")
        settings, ini, raw, document = self._settings(exe)
        diagnostic = LuaRuntimeInstaller(self.base_dir / "runtime" / "lua-cache").diagnose(exe)
        if not diagnostic.ready:
            raise ValueError("Support Lua non vérifié : " + diagnostic.message)
        managed = entry["managed"]
        if managed is not None and not self._managed_matches(document, managed):
            raise ValueError("Les réglages Lua ont été modifiés hors de PCE ; configuration conservée, mode manuel requis.")
        original_lines = managed["original"] if managed is not None else [
            document.entry_line(section, name) for section, name in _KEYS]
        # Validate the value before making a recovery snapshot or writing a loader.
        document.get_int("Scripting", "AutoLoad", 0)
        previous = document.get_text("PathSettings", "Lua")
        folder = str(loader.parent)
        document.set_int("Scripting", "AutoLoad", 1)
        document.set_text("PathSettings", "Lua", folder)
        updated = document.to_bytes()
        if not loader.exists():
            self._atomic_write(loader, content, expected=None, compare=True)

        def journal(backup):
            folders = [folder]
            if managed is not None and previous in managed["folders"] and previous != folder:
                folders.append(previous)
            entry["managed"] = {"original": original_lines, "folders": folders,
                                "backup": managed["backup"] if managed else str(backup)}
            self._save_state(data, original_state)

        backup = settings.replace_config(ini, raw, updated, before_replace=journal)
        return LuaAutoLoadResult(True, loader, ini, backup,
                                 "Autoload configuré pour ce lancement. Connexion en attente du heartbeat Lua.")

    @_manual_on_io_error
    def restore(self, executable) -> LuaAutoLoadResult:
        exe, _, key = self._identity(executable)
        data, original_state = self._read_state()
        entry = data["executables"].get(key)
        if entry is None or entry["managed"] is None:
            return LuaAutoLoadResult(message="Aucun réglage Lua PCE à restaurer ; mode manuel conservé.")
        settings, ini, raw, document = self._settings(exe)
        managed = entry["managed"]
        if not self._managed_matches(document, managed):
            raise ValueError("Les réglages Lua ont été modifiés hors de PCE ; restauration automatique refusée. "
                             "Votre configuration et son backup sont conservés.")
        for (section, name), line in zip(_KEYS, managed["original"]):
            document.restore_entry(section, name, line)
        updated = document.to_bytes()
        backup = settings.replace_config(ini, raw, updated) if updated != raw else None
        entry["managed"] = None
        self._save_state(data, original_state)
        return LuaAutoLoadResult(ini_path=ini, backup_path=backup,
                                 message="Réglages Lua précédents restaurés ; scripts personnels conservés.")
