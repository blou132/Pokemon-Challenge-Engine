"""Synthetic ownership/configuration tests; these do not validate emulation."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from app.core.run_manager import RunManager
from app.services.config_service import AppConfig
from app.services.melonds_run_service import MelonDSRunService
from app.services.melonds_runtime import UPSTREAM_COMMIT, initial_config, validate_config, verify_installation
from app.services.run_isolation_service import RunIsolationService
from app.services.run_launch_service import RunLaunchService
from app.services.save_manager_service import SaveManagerService
from test_auto_discovery import rom_bytes
from test_run_isolation import environment, create, tree
from test_save_conversion import dsv


@pytest.fixture
def component(tmp_path, monkeypatch):
    root = tmp_path / "component"
    root.mkdir()
    exe = root / "melonDS.exe"
    exe.write_bytes(b"synthetic executable - never executed")
    (root / "pce-bridge.json").write_text(json.dumps({"schema_version": 1, "bridge_version": "1.1-pce.1",
        "upstream_commit": UPSTREAM_COMMIT, "executable": exe.name,
        "files": {exe.name: sha256(exe.read_bytes()).hexdigest()}}), encoding="utf-8")
    from app.services import melonds_runtime
    monkeypatch.setattr(melonds_runtime, "VERIFIED_MANIFEST_SHA256",
                        {sha256((root / "pce-bridge.json").read_bytes()).hexdigest()})
    return exe


def fresh(tmp_path, component, name="Classic", *, challenge=None):
    rom = tmp_path / "white.nds"
    if not rom.exists():
        rom.write_bytes(rom_bytes())
    manager = RunManager(tmp_path / "PCE/runs")
    run = manager.create(name, "white", game_code="IRAF", region="FR", revision=0, challenge=challenge,
        launch_profile={"game_id": "white", "rom_path": str(rom), "emulator_path": str(component),
                        "emulator_kind": "melonds", "_isolation_pending": True})
    return manager, run


def test_independent_runs_and_reopen_without_retrobat(tmp_path, component):
    manager, first = fresh(tmp_path, component)
    _, second = fresh(tmp_path, component, "Second")
    service = MelonDSRunService(manager, running_probe=lambda path: False)
    first, second = service.prepare(first, component), service.prepare(second, component)
    for key in ("rom_path", "save_path", "emulator_path", "ini_path", "save_state_directory"):
        assert first.launch_profile[key] != second.launch_profile[key]
    assert not Path(first.save_path).exists()
    assert Path(first.launch_profile["rom_path"]).read_bytes() == (tmp_path / "white.nds").read_bytes()
    result = RunLaunchService(manager.root.parent, AppConfig()).prepare(manager.load(first.run_id))
    assert result["health"]["ready"] is True
    assert result["profile"]["emulator_kind"] == "melonds"
    RunIsolationService(manager).validate(second)


def test_migration_preserves_previous_environment_history_and_rules(environment, component):
    env = environment
    env.save.write_bytes(dsv())
    original = env.service.isolate(create(env, save_path=str(env.save)), import_save=env.save, import_states=True)
    old_tree = tree(env.service.directory(original))
    before = original.to_dict()
    service = MelonDSRunService(env.manager, running_probe=lambda path: False)
    updated = service.prepare(original, component, migrate=True)
    assert tree(env.service.directory(original)) == old_tree
    assert updated.run_id == original.run_id
    assert updated.rom_fingerprint == original.rom_fingerprint
    for key in ("rules_snapshot", "history", "current_party", "captures", "deaths", "seed"):
        assert updated.to_dict()[key] == before[key]
    assert Path(updated.save_path).read_bytes() == dsv()[:512 * 1024]
    assert list((service.directory(updated) / "states").iterdir()) == []
    assert (service.directory(updated) / "migration/source.dsv").read_bytes() == dsv()
    assert json.loads((service.directory(updated) / "migration/source-run.json").read_text(encoding="utf-8")) == before
    assert RunIsolationService(env.manager).save_may_be_missing(updated) is False
    service.validate(env.manager.load(updated.run_id))
    with pytest.raises(ValueError, match="existe déjà"):
        service.prepare(updated, component)


def test_missing_previously_observed_battery_is_refused(tmp_path, component):
    manager, run = fresh(tmp_path, component)
    run = MelonDSRunService(manager).prepare(run, component)
    Path(run.save_path).write_bytes(b"\xff" * (512 * 1024))
    launcher = RunLaunchService(manager.root.parent, AppConfig())
    launcher.prepare(run)
    Path(run.save_path).unlink()
    with pytest.raises(ValueError, match="disparu"):
        launcher.prepare(run)


def test_migration_while_emulator_running_refused(environment, component):
    run = environment.service.isolate(create(environment))
    before = tree(environment.service.directory(run))
    service = MelonDSRunService(environment.manager, running_probe=lambda path: True)
    with pytest.raises(ValueError, match="Fermez"):
        service.prepare(run, component, migrate=True)
    assert tree(environment.service.directory(run)) == before
    assert not service.directory(run).exists()


def test_package_modified_or_traversal_refused(component, monkeypatch):
    marker = component.parent / "pce-bridge.json"
    data = json.loads(marker.read_text())
    component.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changé"):
        verify_installation(component)
    data["files"] = {"../outside.dll": "0" * 64, component.name: sha256(component.read_bytes()).hexdigest()}
    marker.write_text(json.dumps(data))
    from app.services import melonds_runtime
    monkeypatch.setattr(melonds_runtime, "VERIFIED_MANIFEST_SHA256", {sha256(marker.read_bytes()).hexdigest()})
    with pytest.raises(ValueError, match="Chemin"):
        verify_installation(component)


@pytest.mark.parametrize("replacement", [('[Instance0.Gdb]\nEnabled = false', '[Instance0.Gdb]\nEnabled = true'),
                                         ('ExternalBIOSEnable = false', 'ExternalBIOSEnable = true'),
                                         ('RelocSRAM = false', 'RelocSRAM = true')])
def test_external_features_refused(tmp_path, replacement):
    path = tmp_path / "melonDS.toml"
    path.write_text(initial_config(tmp_path).replace(*replacement), encoding="utf-8")
    with pytest.raises(ValueError, match="externes"):
        validate_config(path, tmp_path)


def test_sav_backups_restore_and_no_cross_format_restore(tmp_path):
    save = tmp_path / "white.sav"
    save.write_bytes(b"first save")
    service = SaveManagerService(tmp_path / "backups")
    first = service.backup(save, "white")
    assert first.filename.endswith(".sav")
    save.write_bytes(b"second save")
    service.restore(first.filename, save, "white", confirmed=True)
    assert save.read_bytes() == b"first save"
    dsv_path = tmp_path / "white.dsv"
    dsv_path.write_bytes(b"source dsv unchanged")
    with pytest.raises(ValueError, match="formats"):
        service.restore(first.filename, dsv_path, "white", confirmed=True)
    assert dsv_path.read_bytes() == b"source dsv unchanged"


def test_self_declared_manifest_cannot_authorize_an_executable(component):
    marker = component.parent / "pce-bridge.json"
    marker.write_text(marker.read_text() + " ")
    with pytest.raises(ValueError, match="non vérifiée"):
        verify_installation(component)


def test_melonds_native_session_rejects_corruption_and_recovers(tmp_path):
    from app.services.emulator_service import EmulatorService
    from app.services.bridge_service import BridgeService
    from test_melonds_bridge import PROFILES, frame
    rom = tmp_path / "white.nds"
    rom.write_bytes(rom_bytes())
    bridge = BridgeService(tmp_path / "sessions")
    marker = EmulatorService(tmp_path, bridge).prepare("white", str(rom), emulator_kind="melonds")
    assert marker.name == "melonds-session.json"
    assert not (marker.parent / "connect.lua").exists()
    profile = next(item for item in PROFILES if item["game_id"] == "white")
    sample = frame(profile, bridge.session_id)
    target = marker.parent / "melonds-frame.json"
    target.write_text(json.dumps(sample))
    assert bridge.poll().party[0]["species_id"] == 501
    target.write_text("bad JSON")
    assert bridge.poll().party is None
    assert bridge.state.status == "error"
    sample["sequence"] = 2
    target.write_text(json.dumps(sample))
    assert bridge.poll().party[0]["species_id"] == 501
    bridge.stop()
    assert bridge.native_reader is None


def test_melonds_state_slots_are_distinct_from_desmume(tmp_path):
    (tmp_path / "white.ml1").write_bytes(b"melon state")
    (tmp_path / "white.ds2").write_bytes(b"desmume state")
    melon = SaveManagerService.inspect_slots(tmp_path, "white", "white", emulator_kind="melonds")
    legacy = SaveManagerService.inspect_slots(tmp_path, "white", "white")
    assert melon[1].exists and not melon[2].exists
    assert legacy[2].exists and not legacy[1].exists


@pytest.mark.parametrize("argument", [False, True])
def test_derived_rom_never_imports_previous_progress(tmp_path, component, argument):
    from test_run_randomizer_isolation import challenge
    manager, run = fresh(tmp_path, component, challenge=challenge())
    save = tmp_path / "old.dsv"
    save.write_bytes(dsv())
    if not argument:
        run.save_path = str(save)
    manager.save(run)
    service = MelonDSRunService(manager)
    with pytest.raises(ValueError, match="sans sauvegarde"):
        service.prepare(run, component, import_save=save if argument else None)
    assert not service.directory(run).exists()


def test_explicit_import_argument_is_used(tmp_path, component):
    manager, run = fresh(tmp_path, component)
    source = tmp_path / "chosen.dsv"
    source.write_bytes(dsv())
    result = RunIsolationService(manager, running_probe=lambda path: False).isolate(run, import_save=source)
    assert Path(result.save_path).read_bytes() == dsv()[:512 * 1024]
    assert source.read_bytes() == dsv()
    with pytest.raises(ValueError, match="déjà"):
        RunIsolationService(manager).isolate(result, import_save=source)


def test_portable_import_preserves_melonds_settings_and_sources(tmp_path, component):
    from app.services.user_data_import import execute_import, plan_import
    manager, run = fresh(tmp_path, component)
    service = MelonDSRunService(manager)
    run = service.prepare(run, component)
    Path(run.save_path).write_bytes(b"\xff" * (512 * 1024))
    backup = SaveManagerService(Path(run.launch_profile["backup_directory"])).backup(run.save_path, "white")
    ini = Path(run.launch_profile["ini_path"])
    ini.write_text(ini.read_text().replace("Width = 512", "Width = 768"), encoding="utf-8")
    before = tree(manager.root.parent)
    target = tmp_path / "imported with spaces"
    execute_import(plan_import(manager.root.parent, target))
    moved_manager = RunManager(target / "runs")
    moved = moved_manager.load(run.run_id)
    MelonDSRunService(moved_manager).validate(moved)
    assert Path(moved.save_path).read_bytes() == Path(run.save_path).read_bytes()
    assert "Width = 768" in Path(moved.launch_profile["ini_path"]).read_text()
    assert SaveManagerService(Path(moved.launch_profile["backup_directory"])).list_backups_for_save(
        moved.save_path, "white")[0].sha256 == backup.sha256
    assert tree(manager.root.parent) == before


def test_retained_desmume_must_be_closed_before_run_deletion(environment, component):
    from app.services.run_deletion_service import RunDeletionService
    env = environment
    run = env.service.isolate(create(env))
    old_exe = Path(run.launch_profile["emulator_path"])
    updated = MelonDSRunService(env.manager, running_probe=lambda path: False).prepare(run, component, migrate=True)
    service = RunDeletionService(env.manager, running_probe=lambda path: Path(path) == old_exe)
    before = tree(env.manager.root)
    with pytest.raises(ValueError, match="ancien DeSmuME"):
        service.preview(updated.run_id)
    assert tree(env.manager.root) == before
