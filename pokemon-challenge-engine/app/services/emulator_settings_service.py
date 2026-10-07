"""Documented DeSmuME INI edits, preserving unknown data and making a backup first."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable

from app.services.emulator_capabilities import EmulatorCapabilities, detect_capabilities


CONTROL_LABELS = {"Up": "Haut", "Down": "Bas", "Left": "Gauche", "Right": "Droite",
                  "A": "A", "B": "B", "X": "X", "Y": "Y", "L": "L", "R": "R",
                  "Start": "Start", "Select": "Select"}
DEFAULT_CONTROLS = {"Up": 38, "Down": 40, "Left": 37, "Right": 39, "A": 88, "B": 90,
                    "X": 83, "Y": 65, "L": 81, "R": 87, "Start": 13, "Select": 161}
DEFAULT_HOTKEYS = {"FastForward": 9, "FastForwardToggle": 0, "IncreaseSpeed": 187,
                   "DecreaseSpeed": 189, "Pause": 19, "FrameLimitToggle": 0}
OTHER_HOTKEYS = {"FrameAdvance": 78, "CpuMode": 145, "PrintScreen": 123,
                 "ToggleFrameDisplay": 190, "ToggleInputDisplay": 188, "LCDsLayoutMode": 35,
                 "LCDsSwap": 34, "ToggleRasterizer": 109, "QuickSave": 73, "QuickLoad": 80,
                 **{f"LoadFromSlot{i}": 121 if i == 0 else 111 + i for i in range(10)},
                 **{f"SelectSlot{i}": 48 + i for i in range(10)}}
SPEEDS = ("x1", "x2", "x4", "MAX")
# All entries correspond to the pinned Windows source, see docs/emulator-settings.md.
GRAPHICS_KEYS = {
    "internal_resolution": ("3D", "PrescaleHD", 1, tuple(range(1, 17))),
    "vsync": ("Video", "VSync", 0, (0, 1)),
    "output_filter": ("Video", "Display Method Filter", 0, (0, 1)),
    "aspect_ratio": ("Video", "Window Force Ratio", 1, (0, 1)),
    "integer_scaling": ("Video", "Window Pad To Integer", 0, (0, 1)),
    "layout": ("Video", "LCDsLayout", 0, (0, 1, 2)),
    "rotation": ("Video", "Window Rotate", 0, (0, 90, 180, 270)),
}
GRAPHICS_PRESETS = {
    "original": {"internal_resolution": 1, "output_filter": 0, "aspect_ratio": 1},
    "sharp": {"internal_resolution": 1, "output_filter": 0, "integer_scaling": 1, "aspect_ratio": 1},
    "hd": {"internal_resolution": 2, "output_filter": 0, "aspect_ratio": 1},
    "performance": {"internal_resolution": 1, "output_filter": 0, "vsync": 0},
}


def key_label(code: int) -> str:
    names = {0: "Non affectée", 9: "Tab", 13: "Entrée", 19: "Pause", 27: "Désactivée",
             32: "Espace", 37: "←", 38: "↑", 39: "→", 40: "↓", 160: "Maj gauche",
             161: "Maj droite", 162: "Ctrl gauche", 163: "Ctrl droite", 164: "Alt gauche",
             165: "Alt droite", 187: "+ / =", 189: "−"}
    if code in names:
        return names[code]
    if 48 <= code <= 57 or 65 <= code <= 90:
        return chr(code)
    if 112 <= code <= 135:
        return f"F{code - 111}"
    if code & 0x8000:
        return f"Manette (code DeSmuME {code}, périphérique non vérifié)"
    return f"VK {code}"


def validate_controls(controls: dict) -> dict[str, int]:
    if not isinstance(controls, dict) or set(controls) != set(DEFAULT_CONTROLS):
        raise ValueError("Le profil doit contenir les douze commandes DS.")
    if any(type(value) is not int or not 0 <= value <= 65535 for value in controls.values()):
        raise ValueError("Code de touche DeSmuME invalide.")
    return dict(controls)


def control_conflicts(controls: dict[str, int], hotkeys: dict[str, int] | None = None) -> list[str]:
    assignments: dict[int, list[str]] = {}
    for name, code in controls.items():
        if code not in (0, 27):
            assignments.setdefault(code, []).append(CONTROL_LABELS.get(name, name))
    for name, code in (hotkeys or {}).items():
        if code not in (0, 27):
            assignments.setdefault(code, []).append(name)
    return [f"{key_label(code)} : {', '.join(names)}" for code, names in assignments.items() if len(names) > 1]


class IniDocument:
    """Small lossless editor: untouched lines, comments, BOM and newlines stay intact."""

    def __init__(self, raw: bytes):
        if len(raw) > 1024 * 1024:
            raise ValueError("Configuration DeSmuME trop volumineuse.")
        self.bom = b""
        if raw.startswith(b"\xff\xfe"):
            self.encoding, self.bom = "utf-16-le", raw[:2]
        elif raw.startswith(b"\xfe\xff"):
            self.encoding, self.bom = "utf-16-be", raw[:2]
        elif raw.startswith(b"\xef\xbb\xbf"):
            self.encoding, self.bom = "utf-8", raw[:3]
        else:
            # Windows profile APIs interpret an INI without a BOM using the ANSI code page.
            self.encoding = "mbcs" if os.name == "nt" else "cp1252"
        try:
            text = raw[len(self.bom):].decode(self.encoding)
        except UnicodeError as exc:
            raise ValueError("Encodage du fichier DeSmuME invalide.") from exc
        if "\x00" in text:
            raise ValueError("Configuration DeSmuME invalide.")
        self.lines = text.splitlines(keepends=True)
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self._index()

    def _index(self):
        self.entries: dict[tuple[str, str], int] = {}
        self.sections: dict[str, int] = {}
        section = ""
        for index, line in enumerate(self.lines):
            stripped = line.strip()
            if not stripped or stripped.startswith((";", "#")):
                continue
            if stripped.startswith("["):
                # Windows GetPrivateProfileInt accepts comments after the closing
                # bracket, and even a missing closing bracket. Never append a
                # second effective section because of a merely annotated header.
                section = stripped[1:].split("]", 1)[0].strip().casefold()
                if not section:
                    raise ValueError("Section INI vide : modification ambiguë refusée.")
                if section in self.sections:
                    raise ValueError("Section INI dupliquée : modification ambiguë refusée.")
                self.sections[section] = index
            elif "=" in stripped:
                key = stripped.split("=", 1)[0].strip().casefold()
                if (section, key) in self.entries:
                    raise ValueError("Clé INI dupliquée : modification ambiguë refusée.")
                self.entries[section, key] = index

    def get_int(self, section: str, key: str, default: int) -> int:
        index = self.entries.get((section.casefold(), key.casefold()))
        if index is None:
            return default
        value = self.lines[index].split("=", 1)[1].strip()
        match = re.fullmatch(r"([+-]?\d+)\s*(?:[;#].*)?", value)
        if not match:
            raise ValueError(f"Valeur INI invalide : {section}/{key}.")
        return int(match.group(1))

    def set_int(self, section: str, key: str, value: int):
        index = self.entries.get((section.casefold(), key.casefold()))
        if index is not None:
            line = self.lines[index]
            match = re.fullmatch(r"([^=]+=[^\S\r\n]*)([^\r\n]*?)(\r?\n)?", line)
            assert match
            tail = re.search(r"(\s*[;#].*)$", match.group(2))
            self.lines[index] = match.group(1) + str(value) + (tail.group(1) if tail else "") + (match.group(3) or "")
        else:
            start = self.sections.get(section.casefold())
            if start is None:
                if self.lines and not self.lines[-1].endswith(("\n", "\r")):
                    self.lines[-1] += self.newline
                self.lines.extend([f"[{section}]{self.newline}", f"{key}={value}{self.newline}"])
            else:
                insert = min((i for i in self.sections.values() if i > start), default=len(self.lines))
                if insert and not self.lines[insert - 1].endswith(("\n", "\r")):
                    self.lines[insert - 1] += self.newline
                self.lines.insert(insert, f"{key}={value}{self.newline}")
        self._index()

    def get_text(self, section: str, key: str, default: str = "") -> str:
        """String profile values include semicolons; unlike integers, they are not comments."""
        line = self.entry_line(section, key)
        if line is None:
            return default
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        return value

    def entry_line(self, section: str, key: str) -> str | None:
        index = self.entries.get((section.casefold(), key.casefold()))
        return self.lines[index] if index is not None else None

    def set_text(self, section: str, key: str, value: str):
        if not isinstance(value, str) or any(char in value for char in "\r\n\0"):
            raise ValueError("Valeur texte INI invalide.")
        index = self.entries.get((section.casefold(), key.casefold()))
        if index is None:
            self.set_int(section, key, 0)
            index = self.entries[section.casefold(), key.casefold()]
        match = re.fullmatch(r"([^=]+=[^\S\r\n]*)([^\r\n]*?)(\r?\n)?", self.lines[index])
        assert match
        self.lines[index] = match.group(1) + value + (match.group(3) or "")
        self._index()

    def restore_entry(self, section: str, key: str, line: str | None):
        """Restore exactly one captured line, or remove a key originally absent."""
        if line is not None:
            if (not isinstance(line, str) or "\0" in line
                    or re.fullmatch(r"[^\r\n]+(?:\r?\n)?", line) is None
                    or "=" not in line or line.lstrip().startswith((";", "#", "["))
                    or line.split("=", 1)[0].strip().casefold() != key.casefold()):
                raise ValueError("Ligne INI de restauration invalide.")
        index = self.entries.get((section.casefold(), key.casefold()))
        if line is None:
            if index is not None:
                self.lines.pop(index)
        else:
            if index is None:
                self.set_text(section, key, "")
                index = self.entries[section.casefold(), key.casefold()]
            self.lines[index] = line
            if index < len(self.lines) - 1 and not line.endswith(("\n", "\r")):
                self.lines[index] += self.newline
        self._index()

    def to_bytes(self) -> bytes:
        return self.bom + "".join(self.lines).encode(self.encoding)

    def require_windows_profile_encoding(self):
        # Confirmed with GetPrivateProfileIntW on temporary files: UTF-8 BOM
        # and UTF-16 BE are not read as the same INI by this Windows frontend.
        if self.bom not in (b"", b"\xff\xfe"):
            raise ValueError("Encodage INI non pris en charge par DeSmuME : ANSI ou UTF-16 LE requis. Fichier conservé.")


@dataclass(frozen=True)
class SettingsSnapshot:
    capabilities: EmulatorCapabilities
    ini_path: Path | None = None
    controls: dict[str, int] = field(default_factory=dict)
    hotkeys: dict[str, int] = field(default_factory=dict)
    graphics: dict[str, int] = field(default_factory=dict)
    speed: str | None = None
    source: str = "Non disponible"


@dataclass(frozen=True)
class SettingsChange:
    backup_path: Path
    requested_speed: str | None = None
    confirmed_speed: str | None = None
    message: str = "Configuration enregistrée pour le prochain lancement."


def _running_default(executable: Path) -> bool:
    from app.services.emulator_window_manager import EmulatorWindowManager
    return EmulatorWindowManager().running_executable(executable)


class EmulatorSettingsService:
    def __init__(self, executable: str | Path = "", running_probe: Callable | None = None):
        self.executable = str(executable)
        self.running_probe = running_probe or _running_default

    def set_executable(self, executable: str | Path):
        self.executable = str(executable)

    def _path(self) -> Path:
        exe = Path(self.executable)
        if not exe.is_file() or exe.suffix.lower() != ".exe" or exe.is_symlink():
            raise ValueError("Exécutable DeSmuME introuvable ou non régulier.")
        if os.name == "nt" and exe.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise ValueError("DeSmuME est dans le dossier temporaire : emplacement INI ambigu.")
        path = exe.parent / "desmume.ini"
        if not path.is_file() or path.is_symlink():
            raise ValueError("desmume.ini absent : lancez puis fermez DeSmuME une fois.")
        return path

    def inspect(self) -> SettingsSnapshot:
        capabilities = detect_capabilities(self.executable)
        if not capabilities.known_build:
            return SettingsSnapshot(capabilities)
        path = self._path()
        document = IniDocument(path.read_bytes())
        document.require_windows_profile_encoding()
        controls = {key: document.get_int("Controls", key, value) for key, value in DEFAULT_CONTROLS.items()}
        validate_controls(controls)
        hotkeys = {key: document.get_int("Hotkeys", key, value)
                   for key, value in (DEFAULT_HOTKEYS | OTHER_HOTKEYS).items()
                   if document.get_int("Hotkeys", key + " MOD", 0) == 0}
        for (section, key), index in document.entries.items():
            if section == "hotkeys" and not key.endswith(" mod") and key not in {name.casefold() for name in hotkeys}:
                if document.get_int("Hotkeys", key + " MOD", 0) == 0:
                    hotkeys[key] = document.get_int("Hotkeys", key, 0)
        graphics = {key: document.get_int(section, name, default)
                    for key, (section, name, default, allowed) in GRAPHICS_KEYS.items()}
        for key, value in graphics.items():
            if value not in GRAPHICS_KEYS[key][3]:
                raise ValueError(f"Option graphique hors plage : {key}.")
        limiter = document.get_int("FrameLimit", "FrameLimit", 1)
        scaler = document.get_int("Video", "FPS Scaler Index", 5)
        if limiter not in (0, 1) or not 0 <= scaler <= 12:
            raise ValueError("Réglage de vitesse DeSmuME hors plage.")
        speed = "MAX" if limiter == 0 else {5: "x1", 1: "x2", 0: "x4"}.get(scaler)
        return SettingsSnapshot(capabilities, path, controls, hotkeys, graphics, speed,
                                "Configuration DeSmuME ; état en cours non mesuré")

    def import_controls(self) -> dict[str, int]:
        return self.inspect().controls

    def _guard_stopped(self):
        try:
            try:
                running = self.running_probe(Path(self.executable))
            except TypeError:
                running = self.running_probe()
        except (OSError, RuntimeError) as exc:
            raise ValueError("Impossible de vérifier si DeSmuME est fermé.") from exc
        if running is not False:
            raise ValueError("Fermez DeSmuME avant de modifier sa configuration.")

    def backup_config(self) -> Path:
        """Copy before an explicitly requested runtime change; never overwrite a backup."""
        if not detect_capabilities(self.executable).known_build:
            raise ValueError("Cette version de DeSmuME n'est pas vérifiée.")
        path = self._path()
        return self._backup(path, path.read_bytes())

    @staticmethod
    def _backup(path: Path, raw: bytes) -> Path:
        for number in range(100000):
            suffix = "" if number == 0 else f".{number}"
            backup = path.with_name(path.name + ".pce-backup" + suffix)
            created = False
            try:
                with backup.open("xb") as handle:
                    created = True
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                return backup
            except FileExistsError:
                continue
            except OSError:
                if created:
                    backup.unlink(missing_ok=True)
                raise
        raise ValueError("Trop de backups de configuration.")

    def apply(self, *, controls: dict | None = None, graphics: dict | None = None,
              speed: str | None = None, hotkeys: dict | None = None) -> SettingsChange:
        snapshot = self.inspect()
        if not snapshot.capabilities.known_build or snapshot.ini_path is None:
            raise ValueError("Cette version de DeSmuME n'est pas vérifiée : export indisponible.")
        self._guard_stopped()
        path = snapshot.ini_path
        raw = path.read_bytes()
        document = IniDocument(raw)
        document.require_windows_profile_encoding()
        if controls is not None:
            controls = validate_controls(controls)
            if any(value > 255 for value in controls.values()):
                raise ValueError("L'export des codes manette n'est pas vérifié.")
            conflicts = control_conflicts(controls, hotkeys or snapshot.hotkeys)
            if conflicts:
                raise ValueError("Conflit de touches : " + "; ".join(conflicts))
            for key, value in controls.items():
                document.set_int("Controls", key, value)
        if hotkeys is not None:
            if not isinstance(hotkeys, dict) or set(hotkeys) - set(DEFAULT_HOTKEYS):
                raise ValueError("Raccourci DeSmuME inconnu.")
            if any(type(value) is not int or not 0 <= value <= 255 for value in hotkeys.values()):
                raise ValueError("Raccourci clavier invalide.")
            if control_conflicts(controls or snapshot.controls, snapshot.hotkeys | hotkeys):
                raise ValueError("Conflit de raccourcis DeSmuME.")
            for key, value in hotkeys.items():
                document.set_int("Hotkeys", key, value)
                document.set_int("Hotkeys", key + " MOD", 0)
        for key, value in (graphics or {}).items():
            if key not in GRAPHICS_KEYS or type(value) is not int or value not in GRAPHICS_KEYS[key][3]:
                raise ValueError("Option graphique non vérifiée ou invalide.")
            section, name, _, _ = GRAPHICS_KEYS[key]
            document.set_int(section, name, value)
            if key == "rotation":
                document.set_int("Video", "Window Rotate Set", value)
        if speed is not None:
            if speed not in SPEEDS:
                raise ValueError("Vitesse inconnue.")
            if speed in ("x2", "x4"):
                raise ValueError("x2/x4 : utilisez les raccourcis DeSmuME ; l'application au lancement n'est pas vérifiée.")
            document.set_int("FrameLimit", "FrameLimit", 0 if speed == "MAX" else 1)
            if speed == "x1":
                document.set_int("Video", "FPS Scaler Index", 5)
        backup = self.replace_config(path, raw, document.to_bytes())
        return SettingsChange(backup, speed)

    def replace_config(self, path: Path, original: bytes, updated: bytes, *, before_replace=None) -> Path:
        """Common guarded transaction for documented settings and Lua autoload.

        before_replace may persist a recovery journal, after the complete backup
        exists but before the atomic INI replacement. A failed callback leaves
        the configuration untouched.
        """
        if path != self._path() or not detect_capabilities(self.executable).known_build:
            raise ValueError("Configuration DeSmuME non vérifiée.")
        self._guard_stopped()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pce_ini_", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
            if path.read_bytes() != original:
                raise ValueError("La configuration a changé pendant l'édition ; recommencez.")
            backup = self._backup(path, original)
            if before_replace is not None:
                before_replace(backup)
            self._guard_stopped()
            if path.read_bytes() != original:
                raise ValueError("La configuration a changé pendant l'édition ; recommencez.")
            temporary.replace(path)
        except OSError as exc:
            raise ValueError("Configuration non enregistrée : accès refusé ou fichier verrouillé.") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return backup

    def apply_launch_profile(self, options: dict, base_dir: Path) -> SettingsChange:
        if options.get("emulator_path"):
            self.set_executable(options["emulator_path"])
        if options.get("ini_path") and Path(options["ini_path"]).resolve() != self._path().resolve():
            raise ValueError("Le fichier INI choisi ne correspond pas à cet exécutable.")
        profile = options.get("controls_profile", "")
        controls = None
        if profile:
            profiles = ControlProfileStore(Path(base_dir) / "controls.local.json").load()
            if profile in profiles:
                controls = profiles[profile]
            elif profile == "default":
                controls = dict(DEFAULT_CONTROLS)
            else:
                raise ValueError("Profil de contrôles introuvable.")
        preset = options.get("graphics_preset", "")
        if preset and preset not in GRAPHICS_PRESETS:
            raise ValueError("Preset graphique inconnu.")
        return self.apply(controls=controls, graphics=GRAPHICS_PRESETS.get(preset), speed=options.get("speed"))


class ControlProfileStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict[str, dict[str, int]]:
        if not self.path.exists():
            return {}
        try:
            raw = self.path.read_bytes()
            if len(raw) > 1024 * 1024:
                raise ValueError("Profils de contrôles trop volumineux.")
            def unique_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Clé JSON dupliquée.")
                    result[key] = value
                return result
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
            if (not isinstance(value, dict) or set(value) != {"schema_version", "profiles"}
                    or type(value.get("schema_version")) is not int or value["schema_version"] != 1
                    or not isinstance(value.get("profiles"), dict)):
                raise ValueError("Format invalide.")
            profiles = value["profiles"]
            for name, controls in profiles.items():
                if (not isinstance(name, str) or not name.strip() or len(name) > 80
                        or any(ord(ch) < 32 for ch in name)):
                    raise ValueError("Nom de profil invalide.")
                name.encode("utf-8")
                validate_controls(controls)
            return profiles
        except (OSError, ValueError, UnicodeError, RecursionError) as exc:
            raise ValueError("Profils de contrôles illisibles ; fichier conservé.") from exc

    def save(self, name: str, controls: dict):
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(ch) < 32 for ch in name):
            raise ValueError("Nom de profil invalide.")
        try:
            name.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("Nom de profil invalide.") from exc
        profiles = self.load()
        profiles[name] = validate_controls(controls)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".controls.local.", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({"schema_version": 1, "profiles": profiles}, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        except OSError as exc:
            raise ValueError("Impossible d'enregistrer le profil de contrôles.") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
