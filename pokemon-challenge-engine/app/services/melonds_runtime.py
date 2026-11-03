"""Verified local melonDS PCE distribution and per-adventure configuration.

Config keys/portable directory/CLI follow melonDS 1.1 b86390e4428bf38ce4c1ce0e9ca446d6d25955e8,
src/frontend/qt_sdl/{main,CLI,Config,EmuInstance}.cpp. No GDB or RAM writing.
"""

import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tomllib

from app.services.config_service import _strict_pairs
from app.services.discovery_safety import file_hash, local_path
from app.services.run_isolation_service import _regular
from app.services.external_process import child_environment, external_dll_search

UPSTREAM_COMMIT = "b86390e4428bf38ce4c1ce0e9ca446d6d25955e8"
# Native PCE builds, official signed MSYS2 dependencies and corresponding
# sources, verified 2026-10-20 / 2026-11-03. A manifest cannot authorize itself.
VERIFIED_MANIFEST_SHA256 = frozenset({
    "ae761a26559aa9fb4d1eb4552f9a16a9644a115d0f0d6379b9b03262986b2cdf",
    "eb1b83aacadd11d79fe760f1477fd784ac36172a2e81adec6dca04148beb9ff9",
})


def verify_installation(executable: Path) -> dict:
    executable = _regular(local_path(executable))
    marker = _regular(executable.parent / "pce-bridge.json")
    if marker.stat().st_size > 1024 * 1024:
        raise ValueError("Manifeste melonDS trop volumineux.")
    if file_hash(marker) not in VERIFIED_MANIFEST_SHA256:
        raise ValueError("Distribution melonDS non vérifiée ; utilisez le composant PCE publié.")
    data = json.loads(marker.read_text(encoding="utf-8"), object_pairs_hook=_strict_pairs)
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or data.get("bridge_version") not in {"1.1-pce.1", "1.1-pce.2"} or data.get("upstream_commit") != UPSTREAM_COMMIT
            or data.get("executable") != executable.name):
        raise ValueError("Cette version melonDS ne fournit pas le pont PCE vérifié.")
    files = data.get("files")
    if not isinstance(files, dict) or not 1 <= len(files) <= 4096 or executable.name not in files:
        raise ValueError("Liste des fichiers melonDS invalide.")
    names = set()
    for name, digest in files.items():
        if not isinstance(name, str) or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Empreinte melonDS invalide.")
        relative = PurePosixPath(name)
        if (relative.is_absolute() or any(part in {"", ".", ".."} for part in name.split("/"))
                or "\\" in name or ":" in name or name.casefold() in names
                or name.split("/")[0].casefold() == "portable"):
            raise ValueError("Chemin du manifeste melonDS invalide.")
        names.add(name.casefold())
        path = _regular(local_path(executable.parent / name))
        if file_hash(path) != digest:
            raise ValueError("Un fichier melonDS a changé ; réinstallez le composant vérifié.")
    return data


def find_installation(base_dir: Path) -> Path | None:
    """Only known PCE locations; no recursive drive scan or arbitrary first EXE."""
    installation = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    for root in (installation / "third-party/melonDS", Path(base_dir) / "tools/melonDS"):
        marker = root / "pce-bridge.json"
        if marker.is_file():
            if marker.stat().st_size > 1024 * 1024:
                continue
            try:
                name = json.loads(marker.read_text(encoding="utf-8"))["executable"]
                if not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name:
                    continue
                exe = root / name
                verify_installation(exe)
                return exe
            except (OSError, ValueError, KeyError, TypeError):
                continue
    return None


def initial_config(root: Path) -> str:
    quote = lambda value: json.dumps(str(value), ensure_ascii=False)
    # Generated from scratch: external BIOS/firmware and writable disk images
    # are disabled. Keyboard values are Qt::Key, as used by InputConfigDialog.
    return f'''LimitFPS = true
TargetFPS = 60.0
FastForwardFPS = 240.0
[Emu]
ConsoleType = 0
DirectBoot = true
ExternalBIOSEnable = false
[JIT]
Enable = true
[Savestate]
RelocSRAM = false
[DLDI]
Enable = false
[DSi]
[DSi.SD]
Enable = false
["3D"]
Renderer = 0
[Instance0]
SaveFilePath = {quote(root / "saves")}
SavestatePath = {quote(root / "states")}
[Instance0.Gdb]
Enabled = false
[Instance0.Firmware]
Language = 2
[Instance0.Window0]
Width = 512
Height = 768
ScreenLayout = 0
[Instance0.Keyboard]
A = 88
B = 90
X = 83
Y = 65
L = 81
R = 87
Start = 16777220
Select = 16777219
Up = 16777235
Down = 16777237
Left = 16777234
Right = 16777236
'''


def validate_config(path: Path, root: Path) -> dict:
    path = _regular(local_path(path))
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Configuration melonDS trop volumineuse.")
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    try:
        instance = config["Instance0"]
        if (local_path(instance["SaveFilePath"]) != root / "saves"
                or local_path(instance["SavestatePath"]) != root / "states"
                or config.get("Emu", {}).get("ExternalBIOSEnable", False) is not False
                or config.get("Emu", {}).get("ConsoleType", 0) != 0
                or config.get("DLDI", {}).get("Enable", False) is not False
                or config.get("DSi", {}).get("SD", {}).get("Enable", False) is not False
                or config.get("Savestate", {}).get("RelocSRAM", False) is not False
                or instance.get("Gdb", {}).get("Enabled", False) is not False):
            raise ValueError("Les chemins ou fonctions externes melonDS sortent de l'espace de cette partie.")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Configuration melonDS incomplète ; lancement refusé.") from exc
    return config


class MelonDSLauncher:
    def __init__(self, options: dict, *, bridge_environment=None):
        self.options = options
        self.bridge_environment = bridge_environment

    def validate(self, game_id: str) -> list[str]:
        try:
            if self.options["game_id"] != game_id:
                raise ValueError("Le jeu melonDS ne correspond pas à la partie.")
            verify_installation(Path(self.options["emulator_path"]))
            _regular(Path(self.options["rom_path"]))
            root = Path(self.options["rom_path"]).parent.parent
            validate_config(Path(self.options["ini_path"]), root)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return [str(exc)]
        return []

    def launch(self, game_id: str):
        errors = self.validate(game_id)
        if errors:
            raise ValueError("\n".join(errors))
        if not self.bridge_environment or set(self.bridge_environment) != {"PCE_BRIDGE_DIR", "PCE_BRIDGE_SESSION"}:
            raise ValueError("Préparez le suivi melonDS avant de lancer cette partie.")
        executable = Path(self.options["emulator_path"])
        with external_dll_search():
            return subprocess.Popen([str(executable), self.options["rom_path"]], cwd=executable.parent,
                                    env=child_environment(self.bridge_environment), shell=False,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
