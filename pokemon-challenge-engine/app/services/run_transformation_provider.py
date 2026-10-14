"""Load actual ROM species data once per unchanged owned adventure artifact."""

from copy import deepcopy
import json
from pathlib import Path

from app.models.run import validate_run_id
from app.services.discovery_safety import file_hash, file_signature, local_path
from app.services.rom_transformation_service import _regular, transformation_options, verified_transformation_report


class RunTransformationProvider:
    def __init__(self, runs_directory: Path):
        self.runs_directory = local_path(runs_directory)
        self._cache = {}

    def for_run(self, run) -> dict | None:
        """None means no applied transformation, never assumed original types.

        The caller must handle an old Randomizer declaration without provenance
        as unknown. Failed validation raises; it never falls back to stock types.
        """
        configured = transformation_options(run.rules_snapshot)
        if configured is None:
            return None
        root = local_path(self.runs_directory / validate_run_id(run.run_id) / "play")
        directory = root / "transformation"
        rom = local_path((run.launch_profile or {}).get("rom_path", ""))
        expected = root / "game" / f"{run.game_id}-{run.run_id}.nds"
        if rom != expected:
            raise ValueError("Les données Randomizer ne correspondent pas à l'espace de cette partie.")
        artifacts = [rom, root / "isolation.json", directory / "manifest.json", directory / "report.json",
                     directory / "PceRandomizer.java"]
        signatures = tuple(file_signature(_regular(path)) for path in artifacts)
        key = (run.run_id, run.game_id, run.rom_fingerprint, run.seed,
               tuple(configured.to_dict()["categories"]), configured.balanced, signatures)
        if key in self._cache:
            return deepcopy(self._cache[key])
        marker = artifacts[1]
        if marker.stat().st_size > 1024 * 1024:
            raise ValueError("Manifeste d'isolation trop volumineux.")
        isolation = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(isolation, dict) or isolation.get("owner") != "pokemon-challenge-engine-run" or \
                isolation.get("schema_version") != 1 or isolation.get("run_id") != run.run_id or \
                isolation.get("game_id") != run.game_id or isolation.get("rom_sha256") != run.rom_fingerprint:
            raise ValueError("La ROM dérivée n'appartient pas à cette aventure.")
        evidence = isolation.get("transformation")
        if not isinstance(evidence, dict) or evidence.get("manifest_sha256") != file_hash(artifacts[2]) or \
                evidence.get("report_sha256") != file_hash(artifacts[3]):
            raise ValueError("La provenance de transformation a changé.")
        report = verified_transformation_report(directory, rom, game_id=run.game_id,
                                                rom_sha256=run.rom_fingerprint, configuration=run.rules_snapshot)
        if tuple(file_signature(_regular(path)) for path in artifacts) != signatures:
            raise ValueError("La ROM dérivée ou ses données ont changé pendant leur lecture.")
        result = {"game_id": run.game_id, "rom_sha256": run.rom_fingerprint, "categories": configured.to_dict()["categories"],
                  "pokemon": report["pokemon"], "starters": report.get("starters", []),
                  "source": "verified-derived-rom"}
        # A worker tracks one adventure; bound cache memory when switching runs.
        self._cache = {key: result}
        return deepcopy(result)
