"""Synthetic Gen IV identity/isolation checks, never a claim of real emulation."""

from hashlib import sha256
import json
from pathlib import Path
import zipfile

import pytest

from app.bridge.melonds import MelonDSBridgeReader
from app.bridge.protocol import ProtocolError, parse_message
from app.core.challenge_engine import ChallengeEngine
from app.core.game_detector import GameDetector, GEN4_CODE_PREFIXES
from app.core.run_manager import RunManager
from app.services.bridge_service import BridgeService
from app.services.config_service import AppConfig
from app.services.emulator_service import EmulatorService
from app.services.melonds_run_service import MelonDSRunService
from app.services.rom_preparation_service import identity, inspect_rom_source, RomPreparationService
from app.services.rom_transformation_service import RomTransformationService, RandomizerOptions
from app.services.run_isolation_service import RunIsolationService
from app.services.run_launch_service import RunLaunchService
from test_melonds_bridge import frame, publish
from test_melonds_run import component


GAMES = tuple((game, prefix + "F") for prefix, game in GEN4_CODE_PREFIXES.items())


def rom(code, revision=0):
    header = bytearray(512)
    header[12:16] = code.encode("ascii")
    header[30] = revision
    return bytes(header) + b"synthetic data: not a playable ROM"


@pytest.mark.parametrize("game_id,code", GAMES)
@pytest.mark.parametrize("revision", [0, 5])
def test_gen4_catalog_identity_and_readonly_preparation(catalog, tmp_path, game_id, code, revision):
    game = catalog.games[game_id]
    assert game.status == "classic_only" and game.generation == 4 and game.supports_melonds
    assert not game.supports_live_tracking and not game.supports_monotype and not game.supports_desmume
    assert game.revision is None  # Actual cartridge revision is kept, not guessed from a memory profile.
    assert all(game_id not in rule.supported_games for rule in catalog.rules.values())
    path = tmp_path / "name-does-not-identify-game.nds"
    before = rom(code, revision)
    path.write_bytes(before)
    assert GameDetector.detect(path) == game_id
    assert identity(before) == (game_id, code, "FR", revision)
    candidate, = inspect_rom_source(path)
    assert candidate.game_id == game_id and candidate.revision == revision
    result = RomPreparationService(tmp_path / "cache").prepare(path, expected_game=game_id)
    assert result.rom_sha256 == sha256(before).hexdigest()
    assert path.read_bytes() == before


def test_gen4_archives_keep_revision_and_source(tmp_path):
    path = tmp_path / "owned.zip"
    data = rom("ADAF", 5)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("folder/game.nds", data)
    before = path.read_bytes()
    result = RomPreparationService(tmp_path / "cache").prepare(path)
    assert (result.game_id, result.revision) == ("diamond", 5)
    assert result.path.read_bytes() == data and path.read_bytes() == before


@pytest.mark.parametrize("game_id,code", GAMES)
def test_gen4_normal_only_and_run_generation(catalog, tmp_path, game_id, code):
    engine = ChallengeEngine(catalog)
    challenge = engine.generate(game_id, "normal", {}, 0, 10)
    assert not engine.validate(challenge)
    manager = RunManager(tmp_path / "runs")
    run = manager.create("Classic", game_id, challenge=challenge)
    assert manager.load(run.run_id).generation == 4
    with pytest.raises(ValueError, match="génération"):
        manager.create("Wrong generation", game_id, 5)
    for mode in ("custom", "random"):
        with pytest.raises(ValueError, match="classique"):
            engine.generate(game_id, mode, {"nuzlocke": "required"}, 1, 10)
    challenge.mode = "custom"
    assert engine.validate(challenge)
    with pytest.raises(ValueError, match="classique"):
        manager.create("Forged challenge", game_id, challenge=challenge)


@pytest.mark.parametrize("game_id,code", GAMES)
def test_gen4_two_runs_are_independent_and_resume(tmp_path, component, game_id, code):
    path = tmp_path / "master.nds"
    source = rom(code, 5)
    path.write_bytes(source)
    manager = RunManager(tmp_path / "PCE/runs")
    service = MelonDSRunService(manager, running_probe=lambda path: False)
    runs = []
    for name in ("First", "Second"):
        run = manager.create(name, game_id, game_code=code, region="FR", revision=5,
            rom_fingerprint=sha256(source).hexdigest(),
            launch_profile={"game_id": game_id, "rom_path": str(path), "emulator_path": str(component),
                            "emulator_kind": "melonds", "_isolation_pending": True})
        runs.append(service.prepare(run, component))
    for key in ("rom_path", "save_path", "emulator_path", "ini_path", "save_state_directory"):
        assert runs[0].launch_profile[key] != runs[1].launch_profile[key]
    for run in runs:
        assert Path(run.launch_profile["rom_path"]).read_bytes() == source
        reopened = RunManager(manager.root).load(run.run_id)
        RunIsolationService(manager).validate(reopened)
        assert RunLaunchService(manager.root.parent, AppConfig()).prepare(reopened)["health"]["ready"]
    Path(runs[0].save_path).write_bytes(b"first synthetic battery")
    assert not Path(runs[1].save_path).exists()
    assert path.read_bytes() == source


def test_gen4_never_uses_gen5_save_conversion_or_transformer(tmp_path, component):
    source = tmp_path / "master.nds"
    source.write_bytes(rom("CPUF"))
    save = tmp_path / "old.sav"
    save.write_bytes(b"preserve this old battery")
    manager = RunManager(tmp_path / "runs")
    run = manager.create("Classic", "platinum", launch_profile={
        "game_id": "platinum", "rom_path": str(source), "emulator_path": str(component), "emulator_kind": "melonds"})
    with pytest.raises(ValueError, match="sauvegardes Gen IV"):
        MelonDSRunService(manager).prepare(run, component, import_save=save)
    assert save.read_bytes() == b"preserve this old battery"
    with pytest.raises(ValueError, match="Gen V"):
        RomTransformationService(component, component).transform(
            source, tmp_path / "transform", game_id="platinum", seed=1,
            options=RandomizerOptions(("starters",)))
    assert not (tmp_path / "transform").exists()


@pytest.mark.parametrize("game_id,code", GAMES)
def test_gen4_heartbeat_has_identity_but_never_pk5_capabilities(tmp_path, game_id, code):
    bridge = BridgeService(tmp_path / "bridge")
    bridge.start(game_id, code, 5)
    reader = MelonDSBridgeReader(bridge.session_dir, bridge.session_id, code, 5)
    value = frame({"id": None, "game_id": game_id, "game_code": code, "revision": 5}, bridge.session_id,
                  status="unsupported", memory_profile=None, party_count=None, party_hex=None, map_id=None)
    assert publish(reader, value)
    message = reader._message(value)
    result = parse_message(json.dumps(message).encode())
    assert result.game_id == game_id and result.rom_revision == 5
    assert set(result.capabilities) == {"heartbeat", "game_identity"}
    assert result.party is result.observation is result.memory_profile is None
    for changes in ({"party_size": 0, "capabilities": ["heartbeat", "game_identity", "party_size"]},
                    {"memory_profile": "invented-gen4-profile"}, {"emulator": "desmume"}):
        with pytest.raises(ProtocolError, match="Gen IV"):
            parse_message(json.dumps(message | changes).encode())
    value.update(status="ok", party_count=1, party_hex="00" * 220)
    with pytest.raises(ValueError, match="équipe"):
        reader._message(value)


def test_gen4_cannot_start_gen5_lua(tmp_path):
    bridge = BridgeService(tmp_path / "bridge")
    with pytest.raises(ValueError, match="Gen IV"):
        EmulatorService(tmp_path, bridge).prepare("diamond", emulator_kind="desmume")
    assert bridge.session_dir is None
