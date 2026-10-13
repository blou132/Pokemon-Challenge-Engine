"""Validate a run's frozen local launch references using the existing setup tools."""

from copy import deepcopy
from pathlib import Path

from app.services.auto_setup_service import AutoSetupService, GAME_LABELS
from app.services.discovery_safety import file_hash, local_path
from app.services.game_mode_config import GameModeConfigStore, validate_config
from app.services.rom_preparation_service import RomPreparationService


class RunLaunchService:
    def __init__(self, base_dir, config, *, setup=None):
        self.base_dir = Path(base_dir)
        self.config = config
        self.setup = setup or AutoSetupService(self.base_dir, config)

    def snapshot(self, game_id, options=None, save_path=None):
        values = deepcopy(options if options is not None else
                          GameModeConfigStore(self.base_dir, self.config).load()["launch_profiles"][game_id])
        values["challenge_profile_id"] = None
        if save_path is not None:
            values["save_path"] = save_path
        record = self.setup.store.load()["games"].get(game_id)
        if record and record["prepared_path"] == values["rom_path"]:
            values["_source"] = {key: record.get(key) for key in ("source_path", "archive_member")}
        return values

    @staticmethod
    def _exists(value):
        try:
            return bool(value) and local_path(value).is_file()
        except (OSError, ValueError):
            return False

    def _recover(self, run, values, source):
        report = self.setup.automatic_setup(game_id=run.game_id)
        entry = report.get("game_states", {}).get(run.game_id, {})
        candidate = next((item for item in report.get("games", [])
                          if item["id"] == entry.get("candidate_id") and item["game_id"] == run.game_id
                          and item.get("supported")), None)
        recovering_source = bool(source and not self._exists(source.get("source_path")))
        need_rom = not self._exists(values["rom_path"]) or recovering_source
        emulator = entry.get("emulator_path", "")
        if not emulator:
            emulators = [item for item in report.get("emulators", []) if item.get("architecture")]
            if len(emulators) == 1:
                emulator = emulators[0]["path"]
        # A run's explicit save may resolve a global save ambiguity. Only the
        # already identified ROM/emulator may be reused; never guess either choice.
        if (need_rom and candidate is None) or (not self._exists(values["emulator_path"]) and not emulator):
            message = entry.get("message") or f"{GAME_LABELS[run.game_id]} n'a pas été trouvé. Ajoutez le jeu à votre bibliothèque RetroBat."
            return values, source, message
        if need_rom:
            prepared = RomPreparationService(self.setup.cache_root).prepare(
                candidate["source_path"], member=candidate.get("archive_member"), expected_game=run.game_id)
            expected = run.rom_fingerprint
            if expected is None and recovering_source and self._exists(values["rom_path"]):
                expected = file_hash(local_path(values["rom_path"]))
            if expected and prepared.rom_sha256 != expected:
                return values, source, "La ROM a changé depuis la création de cette partie. Vérifiez son association avant de reprendre."
            if not self._exists(values["rom_path"]):
                values["rom_path"] = str(prepared.path)
            source = {key: candidate.get(key) for key in ("source_path", "archive_member")}
        if not self._exists(values["emulator_path"]):
            values["emulator_path"] = emulator
        if not self._exists(values["ini_path"]):
            ini = Path(values["emulator_path"]).parent / "desmume.ini"
            if self._exists(ini):
                values["ini_path"] = str(ini)
        return values, source, None

    def prepare(self, run):
        snapshot = deepcopy(run.launch_profile or {})
        source = snapshot.pop("_source", None)
        pending_isolation = snapshot.pop("_isolation_pending", False)
        # An owned copy must never be rebound to its original ZIP/cache by the
        # legacy source-recovery path. Missing copies require explicit repair.
        owned = self.base_dir / "runs" / run.run_id / "play"
        if owned.exists() or any(value and Path(value).is_relative_to(owned)
                                 for key, value in snapshot.items() if key in {"rom_path", "emulator_path", "save_path"}):
            return self._prepare_isolated(run, snapshot, source)
        values = validate_config({"launch_profiles": {run.game_id: snapshot}}, self.config,
                                 self.base_dir)["launch_profiles"][run.game_id]
        values["challenge_profile_id"] = None
        # Run.save_path is the explicit association, never inferred from a profile
        # that could since have been edited for a second run of the same game.
        values["save_path"] = "" if pending_isolation else run.save_path or ""
        preparation_error = None
        if source and source.get("source_path"):
            try:
                prepared = RomPreparationService(self.setup.cache_root).prepare(
                    source["source_path"], member=source.get("archive_member"), expected_game=run.game_id)
                values["rom_path"] = str(prepared.path)
            except (OSError, ValueError) as exc:
                preparation_error = "Source de la ROM à vérifier : " + str(exc)
        if self._exists(values["emulator_path"]) and not self._exists(values["ini_path"]):
            ini = Path(values["emulator_path"]).parent / "desmume.ini"
            if self._exists(ini):
                values["ini_path"] = str(ini)
        health = self.setup.health_check(run.game_id, options_override=values)
        source_missing = bool(source and not self._exists(source.get("source_path")))
        missing_reference = not self._exists(values["rom_path"]) or not self._exists(values["emulator_path"])
        if source_missing or (missing_reference and not (health["ready"] or health.get("launch_ready", False))):
            try:
                values, source, recovery_error = self._recover(run, values, source)
                if not source_missing or recovery_error is None:
                    health = self.setup.health_check(run.game_id, options_override=values)
                if source_missing or recovery_error:
                    preparation_error = recovery_error
            except (OSError, ValueError) as exc:
                preparation_error = "Recherche de cette partie incomplète : " + str(exc)
        if preparation_error:
            health["ready"] = False
            health["launch_ready"] = False
            health["issues"].insert(0, preparation_error)
        fingerprint = None
        if health["ready"] or health.get("launch_ready", False):
            fingerprint = file_hash(Path(values["rom_path"]))
            if run.rom_fingerprint and run.rom_fingerprint != fingerprint:
                health["ready"] = False
                health["launch_ready"] = False
                health["issues"].append("La ROM a changé depuis la création de cette partie. Vérifiez son association avant de reprendre.")
        if pending_isolation and (health["ready"] or health.get("launch_ready", False)):
            from app.core.run_manager import RunManager
            from app.services.run_isolation_service import RunIsolationService
            manager = RunManager(self.base_dir / "runs")
            if manager.active_id == run.run_id:
                raise ValueError("Reprenez cette partie depuis Mes parties pour préparer ses fichiers indépendants.")
            def associate(current):
                if current._storage_revision != run._storage_revision:
                    raise ValueError("La partie a changé pendant la vérification ; rechargez-la avant de reprendre.")
                current.launch_profile = deepcopy(values)
                current.launch_profile["_isolation_pending"] = True
                if source:
                    current.launch_profile["_source"] = deepcopy(source)
            run = manager.update(run.run_id, associate)
            run = RunIsolationService(manager).isolate(run, import_save=run.save_path)
            return self.prepare(run)
        return {"game_id": run.game_id, "run_id": run.run_id, "profile": values,
                "health": health, "rom_fingerprint": fingerprint, "source": source, "actions": []}

    def _prepare_isolated(self, run, snapshot, source):
        from app.core.run_manager import RunManager
        from app.services.run_isolation_service import RunIsolationService
        isolation = RunIsolationService(RunManager(self.base_dir / "runs"))
        isolation.validate(run)
        values = validate_config({"launch_profiles": {run.game_id: snapshot}}, self.config,
                                 self.base_dir)["launch_profiles"][run.game_id]
        values["challenge_profile_id"] = None
        values["save_path"] = str(isolation.expected_save_path(run))
        checking = deepcopy(values)
        # A new adventure has no DSV yet. Only an ownership-verified planned
        # target may be absent; external missing saves still fail preflight.
        if not Path(values["save_path"]).exists():
            if not isolation.save_may_be_missing(run):
                raise ValueError("La sauvegarde de cette aventure a disparu. Restaurez sa copie depuis un backup avant de reprendre.")
            checking["save_path"] = ""
        else:
            isolation.mark_save_observed(run)
        health = self.setup.health_check(run.game_id, options_override=checking)
        return {"game_id": run.game_id, "run_id": run.run_id, "profile": values,
                "health": health, "rom_fingerprint": run.rom_fingerprint,
                "source": source, "actions": []}
