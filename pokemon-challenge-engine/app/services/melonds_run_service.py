"""Prepare a separate melonDS environment without replacing an old adventure.

Existing play/ stays byte-for-byte intact. Only after copies validate does the
run reference switch to play-melonds/. The previous metadata is retained there.
"""

from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

from app.core.game_detector import GEN4_GAME_IDS
from app.models.run import utc_now
from app.services.discovery_safety import file_hash, local_path
from app.services.melonds_runtime import initial_config, validate_config, verify_installation
from app.services.run_isolation_service import OWNER, RunIsolationService, _copy, _regular
from app.services.rom_transformation_service import RomTransformationService, transformation_options, verified_transformation_report
from app.services.save_conversion_service import convert_gen5_battery
from app.services.library_setup_service import verify_library_source


class MelonDSRunService:
    def __init__(self, manager, *, running_probe=None):
        self.manager = manager
        self.running_probe = running_probe or RunIsolationService(manager).running_probe

    def directory(self, run):
        return local_path(self.manager._directory(run.run_id) / "play-melonds")

    def paths(self, run, executable_name="melonDS.exe"):
        root = self.directory(run)
        stem = f"{run.game_id}-{run.run_id}"
        return {"rom_path": root / "game" / (stem + ".nds"),
                "emulator_path": root / "emulator" / executable_name,
                "ini_path": root / "emulator/portable/melonDS.toml",
                "save_path": root / "saves" / (stem + ".sav"),
                "save_state_directory": root / "states", "backup_directory": root / "backups"}

    @staticmethod
    def _validate_game_support(run):
        if run.game_id in GEN4_GAME_IDS:
            snapshot = run.rules_snapshot
            if run.generation != 4 or snapshot.get("mode") != "normal" or snapshot.get("active_rules") or \
                    snapshot.get("monotype") is not None or "rom_transformation" in snapshot.get("settings", {}):
                raise ValueError("Gen IV : seule une partie classique sans challenge ni transformation est disponible.")

    def prepare(self, run, executable: Path, *, migrate=False, import_save=None):
        self._validate_game_support(run)
        if run.game_id in GEN4_GAME_IDS and (migrate or import_save is not None or run.save_path):
            raise ValueError("L'import et la conversion de sauvegardes Gen IV ne sont pas validés ; créez une nouvelle aventure classique.")
        if self.manager.active_id == run.run_id:
            raise ValueError("Arrêtez le suivi de cette partie avant de changer d'émulateur.")
        current = self.manager.load(run.run_id)
        if current._storage_revision != run._storage_revision:
            raise ValueError("La partie a changé ; rechargez-la.")
        root = self.directory(run)
        if root.exists():
            raise ValueError("Un espace melonDS existe déjà ; aucun fichier ne sera écrasé.")
        package = verify_installation(executable)
        original = deepcopy(run.launch_profile or {})
        configured = transformation_options(run.rules_snapshot)
        save_source = import_save if import_save is not None else run.save_path
        if configured is not None and not migrate and (save_source or run.save_path or run.status != "preparing"
                or run.current_zone is not None or run.badges is not None):
            raise ValueError("Une nouvelle ROM dérivée exige une aventure sans sauvegarde importée.")
        source_rom = _regular(local_path(original.get("rom_path", "")))
        library_hash = None if migrate else verify_library_source(run, source_rom)
        found = RunIsolationService._identity(source_rom, run)
        existing = RunIsolationService(self.manager)
        if migrate:
            if original.get("emulator_kind", "desmume") != "desmume":
                raise ValueError("Cette partie utilise déjà melonDS.")
            existing.validate(run)
            if self.running_probe(Path(original["emulator_path"])) is not False:
                raise ValueError("Fermez DeSmuME avant de copier la progression.")
        elif any((run.started_at, run.last_played_at, run.sessions, run.current_party, run.known_pokemon,
                  run.captures, run.deaths, run.total_play_seconds)):
            raise ValueError("Une partie existante exige la migration explicite de sa sauvegarde.")
        expected = self.paths(run, package["executable"])
        staging = local_path(root.parent / (".melonds-" + uuid4().hex))
        staging.mkdir()
        promoted = False
        try:
            for name in ("game", "saves", "states", "backups", "migration", "emulator/portable"):
                (staging / name).mkdir(parents=True)
            transformation = None
            if migrate or configured is None:
                rom_hash = _copy(source_rom, staging / "game" / expected["rom_path"].name)
                if library_hash is not None and rom_hash != library_hash:
                    raise ValueError("La ROM maîtresse a changé pendant la copie ; préparation refusée.")
                if run.rom_fingerprint and rom_hash != run.rom_fingerprint:
                    raise ValueError("La ROM ne correspond plus à cette partie.")
                if configured is not None:
                    old_manifest = json.loads((existing.directory(run) / "isolation.json").read_text(encoding="utf-8"))
                    transformation = deepcopy(old_manifest["transformation"])
                    old = existing.directory(run) / "transformation"
                    (staging / "transformation").mkdir()
                    for item in old.iterdir():
                        if item.is_file():
                            _copy(item, staging / "transformation" / item.name)
            else:
                private_input = staging / "source-input.nds"
                copied_hash = _copy(source_rom, private_input)
                if library_hash is not None and copied_hash != library_hash:
                    raise ValueError("La ROM maîtresse a changé pendant la copie ; transformation refusée.")
                result = RomTransformationService.from_local_config(self.manager.root.parent).transform(
                    private_input, staging / "transformation", game_id=run.game_id, seed=run.seed, options=configured)
                private_input.unlink()
                rom_hash = _copy(result.rom_path, staging / "game" / expected["rom_path"].name)
                if rom_hash != result.manifest["output_sha256"]:
                    raise ValueError("La ROM dérivée a changé pendant la copie.")
                transformation = {"manifest_sha256": file_hash(result.manifest_path),
                                  "report_sha256": file_hash(result.report_path),
                                  "source_sha256": result.manifest["source_sha256"]}
                _regular(result.rom_path).unlink()
            for name, digest in package["files"].items():
                target = staging / "emulator" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if _copy(executable.parent / name, target) != digest:
                    raise ValueError("Le composant melonDS a changé pendant sa copie.")
            _copy(executable.parent / "pce-bridge.json", staging / "emulator/pce-bridge.json")
            (staging / "emulator/portable/melonDS.toml").write_text(initial_config(root), encoding="utf-8")
            imports = []
            if save_source:
                save = local_path(save_source)
                if save.exists():
                    if original.get("emulator_path") and self.running_probe(original["emulator_path"]) is not False:
                        raise ValueError("Fermez l'émulateur avant de copier sa sauvegarde.")
                    backup = staging / "migration" / ("source" + save.suffix)
                    _copy(save, backup)
                    converted = convert_gen5_battery(backup, staging / "saves" / expected["save_path"].name)
                    imports.append({"source": str(save), "target": str(expected["save_path"].relative_to(root)), **converted})
                elif migrate and not existing.save_may_be_missing(run):
                    raise ValueError("La sauvegarde attendue a disparu ; migration refusée.")
                elif not migrate:
                    raise ValueError("La sauvegarde choisie est introuvable.")
            (staging / "migration/source-run.json").write_text(
                json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            manifest = {"owner": OWNER, "schema_version": 1, "emulator_kind": "melonds", "run_id": run.run_id,
                        "game_id": run.game_id, "identity": list(found), "rom_sha256": rom_hash,
                        "created_at": utc_now(), "source_rom": str(source_rom), "imports": imports,
                        "package_manifest_sha256": file_hash(staging / "emulator/pce-bridge.json")}
            if transformation is not None:
                manifest["transformation"] = transformation
            (staging / "isolation.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            with self.manager._writing():
                updated = self.manager.load(run.run_id)
                if self.manager.active_id == run.run_id or updated._storage_revision != run._storage_revision:
                    raise ValueError("La partie a changé pendant sa préparation.")
                previous = self.manager._file(run.run_id).read_bytes()
                staging.rename(root)
                promoted = True
                try:
                    options = deepcopy(original)
                    options.pop("_isolation_pending", None)
                    options.update({key: str(value) for key, value in expected.items()})
                    options.update(emulator_kind="melonds", save_state_stem=expected["rom_path"].stem,
                                   lua_connection="manual", apply_settings=False)
                    updated.launch_profile = options
                    updated.save_path = str(expected["save_path"])
                    updated.rom_fingerprint = rom_hash
                    updated.game_code, updated.region, updated.revision = found[1:]
                    self.validate(updated)
                    self.manager._save(updated)
                except BaseException:
                    if self.manager._file(run.run_id).read_bytes() == previous:
                        root.rename(staging)
                        promoted = False
                    raise
                return updated
        finally:
            if not promoted:
                RunIsolationService._remove_staging(staging)

    def validate(self, run):
        self._validate_game_support(run)
        root = self.directory(run)
        marker = _regular(root / "isolation.json")
        if marker.stat().st_size > 1024 * 1024:
            raise ValueError("Manifeste melonDS trop volumineux.")
        manifest = json.loads(marker.read_text(encoding="utf-8"))
        if (manifest.get("owner") != OWNER or manifest.get("schema_version") != 1
                or manifest.get("emulator_kind") != "melonds" or manifest.get("run_id") != run.run_id
                or manifest.get("game_id") != run.game_id):
            raise ValueError("L'espace melonDS ne correspond pas à cette partie.")
        options = run.launch_profile or {}
        exe = local_path(options.get("emulator_path", ""))
        if exe.parent != root / "emulator":
            raise ValueError("L'émulateur sort de l'espace indépendant.")
        if file_hash(_regular(exe.parent / "pce-bridge.json")) != manifest.get("package_manifest_sha256"):
            raise ValueError("Le manifeste du composant melonDS a changé.")
        package = verify_installation(exe)
        expected = self.paths(run, package["executable"])
        if (any(local_path(options.get(key, "")) != path for key, path in expected.items())
                or local_path(run.save_path or "") != expected["save_path"]
                or options.get("save_state_stem") != expected["rom_path"].stem):
            raise ValueError("Un chemin melonDS sort de cette partie.")
        for folder in ("game", "saves", "states", "backups", "migration", "emulator/portable"):
            if not local_path(root / folder).is_dir():
                raise ValueError("Un dossier melonDS de cette partie est absent.")
        for path in root.rglob("*"):
            local_path(path)
            if not path.is_dir():
                _regular(path)
        found = RunIsolationService._identity(expected["rom_path"], run)
        if (manifest.get("identity") != list(found) or manifest.get("rom_sha256") != run.rom_fingerprint
                or file_hash(expected["rom_path"]) != run.rom_fingerprint):
            raise ValueError("La copie de ROM melonDS a changé.")
        if transformation_options(run.rules_snapshot) is not None or manifest.get("transformation") is not None:
            evidence = manifest.get("transformation")
            directory = root / "transformation"
            if (not isinstance(evidence, dict) or file_hash(_regular(directory / "manifest.json")) != evidence.get("manifest_sha256")
                    or file_hash(_regular(directory / "report.json")) != evidence.get("report_sha256")):
                raise ValueError("La provenance de transformation melonDS a changé.")
            verified_transformation_report(directory, expected["rom_path"], game_id=run.game_id,
                                           rom_sha256=run.rom_fingerprint, configuration=run.rules_snapshot)
        validate_config(expected["ini_path"], root)
