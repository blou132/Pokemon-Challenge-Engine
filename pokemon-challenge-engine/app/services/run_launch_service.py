"""Validate a run's frozen local launch references using the existing setup tools."""

from copy import deepcopy
from pathlib import Path

from app.services.auto_setup_service import AutoSetupService
from app.services.discovery_safety import file_hash
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

    def prepare(self, run):
        snapshot = deepcopy(run.launch_profile or {})
        source = snapshot.pop("_source", None)
        values = validate_config({"launch_profiles": {run.game_id: snapshot}}, self.config,
                                 self.base_dir)["launch_profiles"][run.game_id]
        values["challenge_profile_id"] = None
        # Run.save_path is the explicit association, never inferred from a profile
        # that could since have been edited for a second run of the same game.
        values["save_path"] = run.save_path or ""
        preparation_error = None
        if source and source.get("source_path"):
            try:
                prepared = RomPreparationService(self.setup.cache_root).prepare(
                    source["source_path"], member=source.get("archive_member"), expected_game=run.game_id)
                values["rom_path"] = str(prepared.path)
            except (OSError, ValueError) as exc:
                preparation_error = "Source de la ROM à vérifier : " + str(exc)
        health = self.setup.health_check(run.game_id, options_override=values)
        if preparation_error:
            health["ready"] = False
            health["launch_ready"] = False
            health["issues"].append(preparation_error)
        fingerprint = None
        if health["ready"] or health.get("launch_ready", False):
            fingerprint = file_hash(Path(values["rom_path"]))
            if run.rom_fingerprint and run.rom_fingerprint != fingerprint:
                health["ready"] = False
                health["launch_ready"] = False
                health["issues"].append("La ROM a changé depuis la création de cette partie. Vérifiez son association avant de reprendre.")
        return {"game_id": run.game_id, "run_id": run.run_id, "profile": values,
                "health": health, "rom_fingerprint": fingerprint, "actions": []}
