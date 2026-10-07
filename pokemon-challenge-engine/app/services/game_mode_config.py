"""Versioned local frontend preferences, independent of challenges and Lua."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from app.core.game_detector import GAME_CODE_PREFIXES
from app.models.profile import validate_json_data, validate_profile_id
from app.services.config_service import AppConfig, _invalid_constant, _strict_pairs

GAME_IDS = tuple(GAME_CODE_PREFIXES.values())
BLOCKS = ("controls", "team", "challenge", "zone", "capture", "deaths", "badges", "level_cap",
          "seed", "speed", "saves", "logs", "debug")
SHORTCUTS = ("speed_x1", "speed_x2", "speed_x4", "speed_max", "fullscreen", "game_mode",
             "manual_backup", "next_panel", "toggle_panels")
SPEEDS = ("x1", "x2", "x4", "MAX")


def launch_defaults(game: str, legacy: AppConfig, base: Path) -> dict:
    return {"game_id": game, "rom_path": legacy.rom_paths.get(game, ""), "emulator_path": legacy.desmume_path,
            "ini_path": "", "controls_profile": "default", "graphics_preset": "original", "speed": "x1",
            "game_mode": True, "apply_settings": False, "challenge_profile_id": None, "lua_connection": "ask",
            "save_path": "", "save_state_directory": "", "save_state_stem": "",
            "backup_directory": str(base / "backups"), "backup_on_launch": False, "backup_on_close": False,
            "backup_periodic": False, "backup_interval_minutes": 10, "backup_retention": 10,
            "save_state_policy": "unmanaged"}


def defaults(legacy: AppConfig, base: Path) -> dict:
    return {"schema_version": 1, "launch_profiles": {game: launch_defaults(game, legacy, base) for game in GAME_IDS},
            "interface": {"density": "standard", "visible": {key: key not in {"logs", "debug"} for key in BLOCKS},
                          "sides": {key: "left" if key in {"controls", "speed", "saves"} else "right" for key in BLOCKS},
                          "monitor_name": "", "auto_arrange": False}, "shortcuts": dict.fromkeys(SHORTCUTS, "")}


def validate_config(data: dict, legacy: AppConfig, base: Path) -> dict:
    validate_json_data(data)
    if not isinstance(data, dict) or set(data) - {"schema_version", "launch_profiles", "interface", "shortcuts"}:
        raise ValueError("Configuration Mode Jeu invalide.")
    if type(data.get("schema_version", 1)) is not int or data.get("schema_version", 1) != 1:
        raise ValueError("Version de configuration Mode Jeu inconnue.")
    result = defaults(legacy, base)
    profiles = data.get("launch_profiles", {})
    if not isinstance(profiles, dict) or set(profiles) - set(GAME_IDS):
        raise ValueError("Profils de lancement invalides.")
    for game, values in profiles.items():
        template = result["launch_profiles"][game]
        if not isinstance(values, dict) or set(values) - set(template):
            raise ValueError("Champs du profil de lancement invalides.")
        profile = template | values
        if profile["game_id"] != game or profile["speed"] not in SPEEDS:
            raise ValueError("Jeu ou vitesse du profil invalide.")
        if profile["lua_connection"] not in ("ask", "auto", "manual"):
            raise ValueError("Mode de connexion Lua invalide.")
        for key in ("game_mode", "apply_settings", "backup_on_launch", "backup_on_close", "backup_periodic"):
            if type(profile[key]) is not bool:
                raise ValueError(f"Option {key} invalide.")
        for key in ("rom_path", "emulator_path", "ini_path", "controls_profile", "graphics_preset", "save_path",
                    "save_state_directory", "save_state_stem", "backup_directory"):
            if not isinstance(profile[key], str) or len(profile[key]) > 4096 or "\0" in profile[key]:
                raise ValueError(f"Chemin ou réglage {key} invalide.")
        if profile["challenge_profile_id"] is not None:
            validate_profile_id(profile["challenge_profile_id"])
        for key, maximum in (("backup_interval_minutes", 1440), ("backup_retention", 10000)):
            if type(profile[key]) is not int or not 1 <= profile[key] <= maximum:
                raise ValueError(f"Valeur {key} invalide.")
        if profile["save_state_policy"] not in ("allowed", "forbidden", "outside_battle", "read_only", "unmanaged"):
            raise ValueError("Politique de save states inconnue.")
        result["launch_profiles"][game] = profile
    interface = data.get("interface", {})
    if not isinstance(interface, dict) or set(interface) - set(result["interface"]):
        raise ValueError("Interface en jeu invalide.")
    options = result["interface"] | interface
    if options["density"] not in ("compact", "standard", "large") or type(options["auto_arrange"]) is not bool:
        raise ValueError("Disposition du Mode Jeu invalide.")
    if not isinstance(options["monitor_name"], str) or len(options["monitor_name"]) > 256:
        raise ValueError("Écran sélectionné invalide.")
    for key, allowed in (("visible", (True, False)), ("sides", ("left", "right"))):
        values = options[key]
        if not isinstance(values, dict) or set(values) - set(BLOCKS):
            raise ValueError("Blocs du Mode Jeu invalides.")
        for value in values.values():
            if value not in allowed or (key == "visible" and type(value) is not bool):
                raise ValueError("Option de bloc invalide.")
        options[key] = result["interface"][key] | values
    result["interface"] = options
    shortcuts = data.get("shortcuts", {})
    if not isinstance(shortcuts, dict) or set(shortcuts) - set(SHORTCUTS):
        raise ValueError("Raccourcis application invalides.")
    for value in shortcuts.values():
        if not isinstance(value, str) or len(value) > 100 or "\0" in value:
            raise ValueError("Raccourci application invalide.")
    result["shortcuts"] |= shortcuts
    active = [value.casefold().replace(" ", "") for value in result["shortcuts"].values() if value]
    if len(active) != len(set(active)):
        raise ValueError("Deux raccourcis application utilisent la même combinaison.")
    return deepcopy(result)


class GameModeConfigStore:
    def __init__(self, base_dir: Path, legacy: AppConfig):
        self.base_dir = Path(base_dir).resolve()
        self.path = self.base_dir / "game-mode.local.json"
        self.legacy = legacy
        self.warnings = []
        self._loaded = None

    def load(self) -> dict:
        self.warnings.clear()
        try:
            self._loaded = self.path.read_bytes() if self.path.exists() else None
            if self._loaded is None:
                return defaults(self.legacy, self.base_dir)
            data = json.loads(self._loaded.decode("utf-8-sig"), object_pairs_hook=_strict_pairs, parse_constant=_invalid_constant)
            return validate_config(data, self.legacy, self.base_dir)
        except (OSError, ValueError, UnicodeError, RecursionError):
            self.warnings.append("Configuration Mode Jeu illisible ; fichier conservé et réglages par défaut utilisés.")
            return defaults(self.legacy, self.base_dir)

    def save(self, data: dict) -> dict:
        validated = validate_config(data, self.legacy, self.base_dir)
        content = (json.dumps(validated, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("La configuration ne peut pas être un lien symbolique.")
        current = self.path.read_bytes() if self.path.exists() else None
        if current != self._loaded:
            raise ValueError("La configuration a changé dans un autre outil ; rechargez-la avant de sauvegarder.")
        if self.warnings and current is not None:
            backup = self.path.with_name(self.path.name + ".invalid-" + uuid4().hex + ".bak")
            with backup.open("xb") as handle:
                handle.write(current)
                handle.flush()
                os.fsync(handle.fileno())
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.base_dir, prefix=".game-mode.local.", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        self._loaded = content
        self.warnings.clear()
        return validated
