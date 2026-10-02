"""Prépare uniquement les fichiers locaux Lua ; ne modifie jamais l'émulateur."""

import json
import os
from pathlib import Path

from app.bridge.protocol import GAME_IDS, SCRIPT_VERSION
from app.core.game_detector import GAME_CODE_PREFIXES
from app.services.bridge_service import BridgeService

RESOURCE_DIR = Path(__file__).resolve().parents[2]


def lua_literal(value: object) -> str:
    """Sérialise des données en Lua 5.1 sans permettre l'injection de code."""
    if value is None:
        return "nil"
    if isinstance(value, Path):
        # Les fonctions C io de Lua 5.1 utilisent la page de codes Windows.
        raw = value.resolve().as_posix().encode("mbcs" if os.name == "nt" else "utf-8")
        return '"' + "".join(f"\\{byte:03d}" for byte in raw) + '"'
    if isinstance(value, str):
        return '"' + "".join(f"\\{byte:03d}" for byte in value.encode("utf-8")) + '"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if isinstance(value, list):
        return "{" + ",".join(lua_literal(item) for item in value) + "}"
    if isinstance(value, dict):
        return "{" + ",".join(f"[{lua_literal(key)}]={lua_literal(item)}" for key, item in value.items()) + "}"
    raise ValueError("Type non pris en charge dans la configuration Lua.")


def _atomic_text(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


class EmulatorService:
    """Sépare les ressources installées du répertoire local de la session."""

    def __init__(self, base_dir: Path, bridge: BridgeService) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.bridge = bridge

    def prepare(self, game_id: str, rom_path: str = "") -> Path:
        if game_id not in GAME_IDS:
            raise ValueError("Sélectionnez Pokémon Noir, Blanc, Noir 2 ou Blanc 2.")
        code, revision = None, None
        if rom_path:
            rom = Path(rom_path)
            if rom.suffix.lower() != ".nds":
                raise ValueError("Sélectionnez une ROM .nds extraite, pas une archive.")
            with rom.open("rb") as handle:
                header = handle.read(512)
            if len(header) < 512:
                raise ValueError("En-tête de ROM incomplet.")
            code = header[12:16].decode("ascii", errors="replace")
            if len(code) != 4 or not code.isascii() or not code.isalnum() or GAME_CODE_PREFIXES.get(code[:3]) != game_id:
                raise ValueError("L'en-tête de ROM ne correspond pas au jeu sélectionné.")
            revision = header[30]
        profiles = json.loads((RESOURCE_DIR / "data/memory_profiles.json").read_text(encoding="utf-8"))
        tracking_profiles = json.loads((RESOURCE_DIR / "data/tracking_profiles.json").read_text(encoding="utf-8"))
        capture_zones = json.loads((RESOURCE_DIR / "data/capture_zones.json").read_text(encoding="utf-8"))
        for profile in tracking_profiles:
            table = capture_zones["tables"].get(profile.get("capture_zone_table"), {})
            profile["capture_zones"] = table.get("entries", {})
        common = RESOURCE_DIR / "lua/common"
        for name in ("bridge.lua", "protocol.lua", "gen5_reader.lua", "gen5_tracking_reader.lua"):
            if not (common / name).is_file():
                raise ValueError(f"Ressource Lua absente : {name}.")
        state = self.bridge.start(game_id, code, revision)
        if state.status == "error":
            raise ValueError(state.last_error)
        session = self.bridge.session_dir
        assert session is not None
        config_path = session / "config.lua"
        config = {
            "session_id": self.bridge.session_id, "session_dir": session,
            "expected_game": game_id, "expected_code": code, "expected_revision": revision,
            "script_version": SCRIPT_VERSION, "common_dir": common, "profiles": profiles,
            "tracking_profiles": tracking_profiles,
        }
        try:
            config_text = "-- Configuration locale générée ; ne pas versionner.\nreturn " + lua_literal(config) + "\n"
            _atomic_text(config_path, config_text)
            # Legacy entrypoints keep their current-game lookup. A session's own
            # connect.lua must always retain its original ID and stop marker.
            _atomic_text(self.bridge.root / f"current-{game_id}.lua", config_text)
            script = session / "connect.lua"
            _atomic_text(script, "-- Charger ce fichier dans DeSmuME > Tools > Lua Scripting.\n"
                         + "dofile(" + lua_literal(common / "bridge.lua") + ").run("
                         + lua_literal(config_path) + ")\n")
        except (OSError, UnicodeError):
            self.bridge.stop()
            raise
        return script
