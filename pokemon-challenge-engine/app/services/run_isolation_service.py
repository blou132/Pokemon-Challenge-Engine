"""Own one immutable ROM and one DeSmuME environment per persistent adventure.

Windows DeSmuME resolves its INI beside its executable, not from cwd. Its
Battery and StateSlots targets use the ROM basename (official source pinned
in emulator_capabilities). A separate executable/INI avoids changing RetroBat.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from uuid import uuid4

from app.models.run import Run, utc_now
from app.services.discovery_safety import file_hash, file_signature, local_path
from app.services.emulator_capabilities import detect_capabilities
from app.services.emulator_settings_service import IniDocument
from app.services.emulator_window_manager import EmulatorWindowManager
from app.services.lua_runtime_installer import LuaRuntimeInstaller
from app.services.rom_preparation_service import identity


OWNER = "pokemon-challenge-engine-run"
PATHS = {"Battery": "saves", "States": "states", "StateSlots": "state-slots",
         "Roms": "game", "SramImportExport": "exports", "Screenshots": "screenshots",
         "AviFiles": "videos", "Cheats": "cheats", "SoundSamples": "sounds",
         "Firmware": "firmware", "Slot1D": "slot1", "Lua": "lua"}
SAFE_SECTIONS = frozenset({"controls", "hotkeys", "video", "display", "framelimit",
                           "sound", "3d", "focus", "emulation"})


def _regular(path: Path) -> Path:
    path = local_path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Fichier partagé par lien ou fichier spécial : isolation refusée.")
    return path


def _copy(source: Path, target: Path) -> str:
    """Exclusive byte copy, checked against a stable source and reread destination."""
    source = _regular(source)
    before = file_signature(source)
    with source.open("rb") as reader, target.open("xb") as writer:
        shutil.copyfileobj(reader, writer, 1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    digest = file_hash(target)
    if file_signature(source) != before or file_hash(source) != digest or file_signature(source) != before:
        raise ValueError("Le fichier source a changé pendant la copie ; association conservée.")
    _regular(target)
    return digest


class RunIsolationService:
    def __init__(self, manager, *, running_probe=None):
        self.manager = manager
        self.running_probe = running_probe or EmulatorWindowManager().running_executable

    def directory(self, run: Run) -> Path:
        return local_path(self.manager._directory(run.run_id) / "play")

    def _paths(self, run: Run) -> dict[str, Path]:
        root = self.directory(run)
        stem = f"{run.game_id}-{run.run_id}"
        return {"rom_path": root / "game" / (stem + ".nds"),
                "emulator_path": root / "emulator" / "DeSmuME.exe",
                "ini_path": root / "emulator" / "desmume.ini",
                "save_path": root / "saves" / (stem + ".dsv"),
                "save_state_directory": root / "state-slots",
                "backup_directory": root / "backups"}

    def expected_save_path(self, run: Run) -> Path:
        return self._paths(run)["save_path"]

    def save_may_be_missing(self, run: Run) -> bool:
        """Called after validate: an imported or previously seen save is required."""
        root = self.directory(run)
        data = json.loads(_regular(root / "isolation.json").read_text(encoding="utf-8"))
        target = self.expected_save_path(run).relative_to(root).as_posix()
        imports = data.get("imports")
        if not isinstance(imports, list) or any(not isinstance(item, dict) for item in imports):
            raise ValueError("Provenance des sauvegardes invalide ; reprise refusée.")
        return not any(Path(item.get("target", "")).as_posix() == target for item in imports) and not local_path(root / "save-observed.json").exists()

    def mark_save_observed(self, run: Run) -> None:
        """Remember presence, never write the game save or replace a prior marker."""
        _regular(self.expected_save_path(run))
        marker = local_path(self.directory(run) / "save-observed.json")
        if marker.exists():
            _regular(marker)
            return
        try:
            with marker.open("x", encoding="utf-8") as handle:
                json.dump({"schema_version": 1, "run_id": run.run_id, "observed_at": utc_now()}, handle)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            _regular(marker)

    def is_isolated(self, run: Run) -> bool:
        root = self.directory(run)
        # A missing/corrupt manifest must never turn an isolated run into a
        # legacy run that could accidentally rediscover the shared source save.
        return root.exists() or any(
            isinstance(value, str) and value and local_path(value).is_relative_to(root)
            for key, value in (run.launch_profile or {}).items()
            if key in {"rom_path", "emulator_path", "save_path"})

    @staticmethod
    def _check_location(root: Path):
        if os.name == "nt" and root.is_relative_to(local_path(tempfile.gettempdir())):
            raise ValueError("Déplacez PCE hors du dossier temporaire Windows avant de préparer une partie. "
                             "DeSmuME y partagerait sa configuration.")
        if len(str(root / "state-slots" / ("white2-" + "0" * 36 + ".ds9")).encode("utf-8")) >= 250:
            raise ValueError("Chemin de partie trop long pour DeSmuME ; utilisez un dossier PCE plus court.")

    @staticmethod
    def _identity(rom: Path, run: Run):
        if rom.suffix.lower() != ".nds":
            raise ValueError("Préparez d'abord la ROM .nds de cette partie.")
        with _regular(rom).open("rb") as reader:
            found = identity(reader.read(512))
        if found[0] != run.game_id or any(expected is not None and expected != actual for expected, actual in
                zip((run.game_code, run.region, run.revision), found[1:])):
            raise ValueError("L'identité de la ROM ne correspond pas à cette partie.")
        return found

    @staticmethod
    def _ini(source: Path, root: Path) -> bytes:
        original = IniDocument(_regular(source).read_bytes())
        original.require_windows_profile_encoding()
        # Copy only user controls/display/emulation settings. Never adopt recent
        # ROMs, scripts, watches, external firmware or source output directories.
        result = IniDocument(b"\xff\xfe")
        for (section, key), index in original.entries.items():
            if section in SAFE_SECTIONS and not any(word in key for word in ("path", "file", "script", "rom")):
                result.set_text(section, key, original.get_text(section, key))
        for key, folder in PATHS.items():
            result.set_text("PathSettings", key, str(root / folder))
        result.set_int("PathSettings", "lastVisit", 0)
        result.set_int("Scripting", "AutoLoad", 0)
        result.set_int("RamWatch", "Auto-load", 0)
        return result.to_bytes()

    def isolate(self, run: Run, *, import_save=None, import_states=False) -> Run:
        if self.manager.active_id == run.run_id:
            raise ValueError("Arrêtez la session et le suivi de cette partie avant de préparer ses fichiers.")
        if self.is_isolated(run):
            self.validate(run)
            if import_save is not None or import_states:
                raise ValueError("Cette partie possède déjà ses fichiers ; aucun import ne les remplacera.")
            return self.manager.load(run.run_id)
        current = self.manager.load(run.run_id)
        if current._storage_revision != run._storage_revision:
            raise ValueError("La partie a changé ; rechargez-la avant la préparation.")
        options = deepcopy(run.launch_profile or {})
        source_rom = _regular(local_path(options.get("rom_path", "")))
        source_exe = _regular(local_path(options.get("emulator_path", "")))
        source_ini = _regular(local_path(options.get("ini_path") or source_exe.parent / "desmume.ini"))
        found = self._identity(source_rom, run)
        if not detect_capabilities(source_exe).known_build:
            raise ValueError("Cette version DeSmuME n'est pas vérifiée pour l'isolation des parties.")
        diagnostic = LuaRuntimeInstaller(self.manager.root.parent / "runtime/lua-cache").diagnose(source_exe)
        if not diagnostic.ready:
            raise ValueError("Installez ou réparez le support Lua dans Installation & diagnostic, "
                             "puis reprenez cette partie pour préparer ses copies.")
        if import_save is not None or import_states:
            if self.running_probe(source_exe) is not False:
                raise ValueError("Fermez DeSmuME avant de copier une sauvegarde ou ses save states.")
        save = _regular(local_path(import_save)) if import_save is not None else None
        if save is not None and (save.suffix.lower() != ".dsv" or save.stat().st_size == 0):
            raise ValueError("Choisissez une sauvegarde DeSmuME .dsv non vide à importer.")
        root = self.directory(run)
        self._check_location(root)
        expected = self._paths(run)
        ini_bytes = self._ini(source_ini, root)
        staging = local_path(root.parent / (".isolation-" + uuid4().hex))
        staging.mkdir()
        promoted = False
        try:
            for folder in {*PATHS.values(), "emulator", "backups"}:
                (staging / folder).mkdir()
            rom_hash = _copy(source_rom, staging / expected["rom_path"].relative_to(root))
            if run.rom_fingerprint and rom_hash != run.rom_fingerprint:
                raise ValueError("L'empreinte ROM a changé ; la partie existante est conservée.")
            exe_hash = _copy(source_exe, staging / "emulator/DeSmuME.exe")
            dlls = {}
            for item in diagnostic.dlls:
                if item.status == "verified":
                    dlls[item.name] = _copy(item.path, staging / "emulator" / item.name)
                    if dlls[item.name] != item.expected_sha256:
                        raise ValueError("La DLL Lua a changé pendant la préparation.")
            (staging / "emulator/desmume.ini").write_bytes(ini_bytes)
            imported = []
            if save is not None:
                digest = _copy(save, staging / expected["save_path"].relative_to(root))
                imported.append({"source": str(save), "target": str(expected["save_path"].relative_to(root)), "sha256": digest})
            if import_states:
                original = IniDocument(source_ini.read_bytes())
                for key, target_folder in (("StateSlots", "state-slots"), ("States", "states")):
                    raw_folder = Path(original.get_text("PathSettings", key, key))
                    folder = local_path(raw_folder if raw_folder.is_absolute() else source_exe.parent / raw_folder)
                    names = [source_rom.stem + ".ds" + str(i) for i in range(10)] if key == "StateSlots" else [source_rom.stem + ".dst"]
                    for name in names:
                        source = local_path(folder / name)
                        if source.exists():
                            target = Path(target_folder) / (expected["rom_path"].stem + source.suffix)
                            digest = _copy(source, staging / target)
                            imported.append({"source": str(source), "target": str(target), "sha256": digest})
            manifest = {"owner": OWNER, "schema_version": 1, "run_id": run.run_id, "game_id": run.game_id,
                        "identity": list(found), "rom_sha256": rom_hash, "emulator_sha256": exe_hash,
                        "dlls": dlls, "created_at": utc_now(), "source_rom": str(source_rom),
                        "source_emulator": str(source_exe), "source_ini": str(source_ini), "imports": imported}
            (staging / "isolation.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            # Keep promotion, metadata publication and any rollback under the
            # same run lock. A failed run.json write must not strand an owned
            # play/ folder that still points to legacy references in metadata.
            with self.manager._writing():
                updated = self.manager.load(run.run_id)
                if self.manager.active_id == run.run_id:
                    raise ValueError("La partie est devenue active pendant la copie ; préparation annulée.")
                if updated._storage_revision != run._storage_revision:
                    raise ValueError("La partie a changé pendant la copie ; rechargez-la.")
                if local_path(root).exists():
                    raise ValueError("Un espace de jeu existe déjà ; aucun fichier ne sera écrasé.")
                previous = self.manager._file(run.run_id).read_bytes()
                staging.rename(root)
                promoted = True
                try:
                    options.pop("_isolation_pending", None)
                    options.update({key: str(value) for key, value in expected.items()})
                    options["save_state_stem"] = expected["rom_path"].stem
                    updated.launch_profile = options
                    updated.save_path = str(expected["save_path"])
                    updated.rom_fingerprint = rom_hash
                    updated.game_code, updated.region, updated.revision = found[1:]
                    self.validate(updated)
                    self.manager._save(updated)
                except BaseException:
                    # If publication happened despite an exception, preserve
                    # the new files: persisted metadata may already use them.
                    if self.manager._file(run.run_id).read_bytes() == previous:
                        local_path(root).rename(staging)
                        promoted = False
                    raise
                return updated
        finally:
            if not promoted:
                # Only this call's fresh staging tree is eligible for cleanup.
                # Refuse substituted links rather than traversing them.
                self._remove_staging(staging)

    @staticmethod
    def _remove_staging(staging: Path):
        local_path(staging)
        pending, entries = [staging], []
        while pending:
            folder = local_path(pending.pop())
            with os.scandir(folder) as children:
                for child in children:
                    path = local_path(child.path)
                    entries.append(path)
                    if path.is_dir():
                        pending.append(path)
                    else:
                        _regular(path)
        for path in sorted(entries, key=lambda value: len(value.parts), reverse=True):
            path = local_path(path)
            if path.is_dir():
                path.rmdir()
            else:
                _regular(path).unlink()
        staging.rmdir()

    def validate(self, run: Run) -> None:
        root = self.directory(run)
        self._check_location(root)
        marker = _regular(root / "isolation.json")
        if marker.stat().st_size > 1024 * 1024:
            raise ValueError("Manifeste d'isolation trop volumineux.")
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise ValueError("Manifeste d'isolation invalide ; fichiers conservés.") from exc
        if not isinstance(data, dict) or data.get("owner") != OWNER or data.get("schema_version") != 1 or \
                data.get("run_id") != run.run_id or data.get("game_id") != run.game_id:
            raise ValueError("Le manifeste d'isolation ne correspond pas à cette partie.")
        expected = self._paths(run)
        options = run.launch_profile or {}
        for key, path in expected.items():
            if local_path(options.get(key, "")) != path:
                raise ValueError("Les chemins de cette partie sortent de son espace indépendant.")
        if local_path(run.save_path or "") != expected["save_path"] or options.get("save_state_stem") != expected["rom_path"].stem:
            raise ValueError("La sauvegarde associée ne correspond pas à cette partie.")
        for folder in {*PATHS.values(), "emulator", "backups"}:
            if not local_path(root / folder).is_dir():
                raise ValueError("Un dossier de la partie est absent ; lancement refusé.")
        for path in root.rglob("*"):
            local_path(path)
            if not path.is_dir():
                _regular(path)
        found = self._identity(expected["rom_path"], run)
        if data.get("identity") != list(found) or file_hash(expected["rom_path"]) != run.rom_fingerprint or data.get("rom_sha256") != run.rom_fingerprint:
            raise ValueError("L'empreinte de la copie ROM ne correspond plus à cette partie.")
        if file_hash(_regular(expected["emulator_path"])) != data.get("emulator_sha256") or not detect_capabilities(expected["emulator_path"]).known_build:
            raise ValueError("La copie DeSmuME a changé ; lancement refusé.")
        dlls = data.get("dlls")
        if not isinstance(dlls, dict) or set(dlls) - {"lua51.dll", "lua5.1.dll"}:
            raise ValueError("Manifeste Lua invalide.")
        for name, digest in dlls.items():
            if file_hash(_regular(root / "emulator" / name)) != digest:
                raise ValueError("Une DLL Lua de la partie a changé.")
        document = IniDocument(_regular(expected["ini_path"]).read_bytes())
        document.require_windows_profile_encoding()
        for key, folder in PATHS.items():
            if key != "Lua" and local_path(document.get_text("PathSettings", key)) != root / folder:
                raise ValueError("Les dossiers de sauvegarde DeSmuME ne sont plus isolés.")
