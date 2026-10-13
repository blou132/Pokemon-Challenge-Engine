"""Synthetic ROM/PE/save files exercise ownership; no real gameplay is claimed."""

from copy import deepcopy
import ctypes
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.run_manager import RunManager
from app.models.challenge import Challenge
from app.services import emulator_capabilities, lua_runtime_installer
from app.services import run_isolation_service as isolation
from app.services.emulator_settings_service import IniDocument
from app.services.auto_setup_service import AutoSetupService
from app.services.config_service import AppConfig
from app.services.run_deletion_service import RunDeletionService
from app.services.run_isolation_service import RunIsolationService
from app.services.run_launch_service import RunLaunchService
from app.services.run_tracking_service import RunTrackingService
from test_auto_discovery import rom_bytes
from test_lua_runtime_setup import pe_bytes


@pytest.fixture
def environment(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    rom, exe, ini, save = (source / name for name in ("white.nds", "DeSmuME.exe", "desmume.ini", "white.dsv"))
    rom.write_bytes(rom_bytes())
    exe.write_bytes(pe_bytes(markers=b"DeSmuME lua51.dll"))
    ini.write_bytes(b"[Controls]\nA=88\n[Video]\nWindow Rotate=0\n[Scripting]\nAutoLoad=1\n"
                    b"[PathSettings]\nBattery=External\nStateSlots=StateSlots\nStates=States\nLua=old-lua\n"
                    b"[Recent Rom]\nRecent0=original.nds\n[RamWatch]\nAuto-load=1\n")
    save.write_bytes(b"synthetic existing user save")
    for folder, extension in (("StateSlots", ".ds0"), ("StateSlots", ".ds9"), ("States", ".dst")):
        (source / folder).mkdir(exist_ok=True)
        (source / folder / (rom.stem + extension)).write_bytes(b"synthetic state " + extension.encode())
    monkeypatch.setattr(emulator_capabilities, "VERIFIED_BUILD_SHA256", sha256(exe.read_bytes()).hexdigest())
    manifest = {}
    for name in ("lua51.dll", "lua5.1.dll"):
        raw = pe_bytes(dll=True, suffix=name.encode())
        (source / name).write_bytes(raw)
        manifest[name] = ("x64/" + name, len(raw), sha256(raw).hexdigest())
    monkeypatch.setattr(lua_runtime_installer, "DLL_MANIFEST", {"x64": manifest})
    # Production deliberately refuses DeSmuME beneath Windows TEMP. Only this
    # synthetic test tree gets a different TEMP boundary; no guard is removed.
    monkeypatch.setattr(isolation.tempfile, "gettempdir", lambda: str(tmp_path / "system-temp"))
    manager = RunManager(tmp_path / "r")
    options = {"rom_path": str(rom), "emulator_path": str(exe), "ini_path": str(ini),
               "save_path": str(save), "speed": "x2", "_isolation_pending": True,
               "_source": {"source_path": str(rom)}}
    service = RunIsolationService(manager, running_probe=lambda path: False)
    return SimpleNamespace(manager=manager, service=service, options=options, source=source,
                           rom=rom, exe=exe, ini=ini, save=save, tmp=tmp_path)


def create(env, name="Classic", **kwargs):
    return env.manager.create(name, "white", game_code="IRAF", region="FR", revision=0,
                              launch_profile=deepcopy(env.options), **kwargs)


def tree(folder):
    return {str(path.relative_to(folder)): path.read_bytes() for path in folder.rglob("*") if path.is_file()}


def test_two_adventures_have_distinct_roms_saves_states_and_progress(environment):
    env = environment
    original = tree(env.source)
    first = env.service.isolate(create(env))
    challenge = Challenge("white", "custom", ["nuzlocke", "permanent_death"], {},
                          {"enforcement": "soft", "rule_parameters": {}}, None, 42)
    second = env.service.isolate(create(env, "Nuzlocke", challenge=challenge))
    for key in ("rom_path", "emulator_path", "ini_path", "save_path", "save_state_directory", "backup_directory"):
        assert first.launch_profile[key] != second.launch_profile[key]
        assert Path(first.launch_profile[key]).is_relative_to(env.manager.root / first.run_id)
    assert Path(first.launch_profile["rom_path"]).read_bytes() == env.rom.read_bytes()
    assert Path(second.launch_profile["rom_path"]).read_bytes() == env.rom.read_bytes()
    assert not Path(first.save_path).exists() and not Path(second.save_path).exists()
    assert not first.launch_profile.get("_isolation_pending")
    Path(first.save_path).write_bytes(b"synthetic adventure A save")
    Path(second.save_path).write_bytes(b"synthetic adventure B save")
    env.manager.update(first.run_id, lambda run: setattr(run, "badges", 1))
    env.manager.update(second.run_id, lambda run: setattr(run, "badges", 3))
    reopened = RunManager(env.manager.root)
    for run in (first, second):
        RunIsolationService(reopened).validate(reopened.load(run.run_id))
    assert reopened.load(first.run_id).badges == 1 and reopened.load(second.run_id).badges == 3
    second_before = tree(env.manager.root / second.run_id)
    deletion = RunDeletionService(reopened)
    deletion.delete(deletion.preview(first.run_id))
    assert tree(env.manager.root / second.run_id) == second_before
    assert tree(env.source) == original


def test_import_copies_explicit_save_and_only_matching_states(environment):
    env = environment
    (env.source / "StateSlots/another.ds0").write_bytes(b"another game's slot")
    before = tree(env.source)
    run = env.service.isolate(create(env, save_path=str(env.save)), import_save=env.save, import_states=True)
    assert Path(run.save_path).read_bytes() == env.save.read_bytes()
    stem = Path(run.launch_profile["rom_path"]).stem
    root = env.service.directory(run)
    assert {path.name for path in (root / "state-slots").iterdir()} == {stem + ".ds0", stem + ".ds9"}
    assert (root / "states" / (stem + ".dst")).read_bytes() == b"synthetic state .dst"
    manifest = json.loads((root / "isolation.json").read_text(encoding="utf-8"))
    assert len(manifest["imports"]) == 4
    assert tree(env.source) == before
    Path(run.save_path).write_bytes(b"changed copied save")
    assert env.save.read_bytes() == b"synthetic existing user save"


def test_ini_paths_are_absolute_and_source_autoload_is_not_copied(environment):
    env = environment
    run = env.service.isolate(create(env))
    path = Path(run.launch_profile["ini_path"])
    document = IniDocument(path.read_bytes())
    assert document.get_int("Controls", "A", 0) == 88
    assert document.get_int("Scripting", "AutoLoad", 1) == 0
    assert document.get_int("RamWatch", "Auto-load", 1) == 0
    assert document.get_text("Recent Rom", "Recent0") == ""
    for key, folder in isolation.PATHS.items():
        assert Path(document.get_text("PathSettings", key)) == env.service.directory(run) / folder
    if os.name == "nt":
        buffer = ctypes.create_unicode_buffer(512)
        read = ctypes.windll.kernel32.GetPrivateProfileStringW
        read("PathSettings", "Battery", "missing", buffer, len(buffer), str(path))
        assert Path(buffer.value) == Path(run.save_path).parent
    # The existing autoload workflow legitimately points Lua at its session
    # directory. Save output paths must remain fixed while this setting changes.
    document.set_text("PathSettings", "Lua", str(env.tmp / "bridge-session"))
    document.set_int("Scripting", "AutoLoad", 1)
    path.write_bytes(document.to_bytes())
    env.service.validate(run)


def test_legacy_progress_and_original_references_survive_non_destructive_migration(environment):
    env = environment
    env.options.pop("_isolation_pending")
    old = create(env, save_path=str(env.save))
    old.badges, old.status = 4, "active"
    env.manager.save(old)
    original = tree(env.source)
    migrated = env.service.isolate(old, import_save=env.save)
    assert migrated.run_id == old.run_id and migrated.badges == 4
    assert migrated.history == old.history and migrated.rules_snapshot == old.rules_snapshot
    assert migrated.save_path != str(env.save)
    assert migrated.launch_profile["_source"]["source_path"] == str(env.rom)
    assert tree(env.source) == original


def test_existing_isolation_is_idempotent_and_never_overwrites_save(environment):
    env = environment
    run = env.service.isolate(create(env))
    Path(run.save_path).write_bytes(b"user progress")
    before = tree(env.manager.root / run.run_id)
    assert env.service.isolate(run) == run
    with pytest.raises(ValueError, match="aucun import"):
        env.service.isolate(run, import_save=env.save)
    assert tree(env.manager.root / run.run_id) == before


@pytest.mark.parametrize("code,revision", [("IRBF", 0), ("IREF", 0), ("IRAO", 0), ("IRAF", 1)])
def test_wrong_game_region_or_revision_cannot_be_isolated(environment, code, revision):
    env = environment
    env.rom.write_bytes(rom_bytes(code, revision))
    run = create(env)
    before = tree(env.manager.root / run.run_id)
    with pytest.raises(ValueError, match="identité"):
        env.service.isolate(run)
    assert tree(env.manager.root / run.run_id) == before


@pytest.mark.parametrize("failure", ["fingerprint", "copy", "validate", "publish"])
def test_preparation_failure_rolls_back_only_owned_copies_and_allows_retry(environment, monkeypatch, failure):
    env = environment
    run = create(env, rom_fingerprint="0" * 64 if failure == "fingerprint" else None)
    before, source = tree(env.manager.root / run.run_id), tree(env.source)
    with monkeypatch.context() as changes:
        if failure == "copy":
            def fail_copy(source, destination):
                destination.write_bytes(b"incomplete")
                raise OSError("copy failed")
            changes.setattr(isolation, "_copy", fail_copy)
        elif failure == "validate":
            changes.setattr(env.service, "validate", lambda run: (_ for _ in ()).throw(ValueError("validation failed")))
        elif failure == "publish":
            changes.setattr(env.manager, "_save", lambda run: (_ for _ in ()).throw(OSError("publication failed")))
        with pytest.raises((OSError, ValueError)):
            env.service.isolate(run)
    assert tree(env.manager.root / run.run_id) == before
    assert tree(env.source) == source
    assert list((env.manager.root / run.run_id).glob(".isolation-*")) == []
    assert not env.service.directory(run).exists()
    assert env.manager.load(run.run_id).launch_profile["_isolation_pending"] is True
    if failure != "fingerprint":
        env.service.validate(env.service.isolate(run))


def test_exception_after_metadata_publication_keeps_referenced_files(environment, monkeypatch):
    env = environment
    run = create(env)
    save = env.manager._save
    def publish_then_fail(value):
        save(value)
        raise OSError("after durable publication")
    monkeypatch.setattr(env.manager, "_save", publish_then_fail)
    with pytest.raises(OSError, match="durable"):
        env.service.isolate(run)
    persisted = env.manager.load(run.run_id)
    assert not persisted.launch_profile.get("_isolation_pending")
    env.service.validate(persisted)


def test_concurrent_progress_change_is_preserved_and_copies_discarded(environment, monkeypatch):
    env = environment
    run = create(env)
    copy = isolation._copy
    def copy_and_edit(source, destination):
        digest = copy(source, destination)
        if source == env.rom:
            env.manager.update(run.run_id, lambda value: setattr(value, "badges", 2))
        return digest
    monkeypatch.setattr(isolation, "_copy", copy_and_edit)
    with pytest.raises(ValueError, match="changé pendant"):
        env.service.isolate(run)
    assert env.manager.load(run.run_id).badges == 2
    assert not env.service.directory(run).exists()


@pytest.mark.parametrize("running", [True, None])
def test_import_requires_confirmed_stopped_emulator(environment, running):
    env = environment
    service = RunIsolationService(env.manager, running_probe=lambda path: running)
    run = create(env)
    with pytest.raises(ValueError, match="Fermez DeSmuME"):
        service.isolate(run, import_save=env.save)
    assert not service.directory(run).exists()


def test_active_selection_blocks_isolation(environment):
    env = environment
    run = create(env)
    env.manager.set_active_id(run.run_id)
    with pytest.raises(ValueError, match="Arrêtez la session"):
        env.service.isolate(run)
    assert not env.service.directory(run).exists()


@pytest.mark.parametrize("change", ["rom_missing", "rom_modified", "manifest_missing", "manifest_owner", "exe_modified", "dll_modified", "ini_battery", "save_path"])
def test_missing_or_changed_owned_files_never_fall_back_to_sources(environment, change):
    env = environment
    run = env.service.isolate(create(env))
    root = env.service.directory(run)
    original = tree(env.source)
    if change == "rom_missing":
        Path(run.launch_profile["rom_path"]).unlink()
    elif change == "rom_modified":
        Path(run.launch_profile["rom_path"]).write_bytes(rom_bytes("IREF"))
    elif change == "manifest_missing":
        (root / "isolation.json").unlink()
    elif change == "manifest_owner":
        data = json.loads((root / "isolation.json").read_text(encoding="utf-8"))
        data["run_id"] = "another-run"
        (root / "isolation.json").write_text(json.dumps(data), encoding="utf-8")
    elif change == "exe_modified":
        Path(run.launch_profile["emulator_path"]).write_bytes(b"changed")
    elif change == "dll_modified":
        (root / "emulator/lua51.dll").write_bytes(b"changed")
    elif change == "ini_battery":
        path = Path(run.launch_profile["ini_path"])
        ini = IniDocument(path.read_bytes())
        ini.set_text("PathSettings", "Battery", str(env.source))
        path.write_bytes(ini.to_bytes())
    else:
        run.save_path = str(env.save)
    assert env.service.is_isolated(run)
    with pytest.raises((ValueError, OSError)):
        env.service.isolate(run)
    assert tree(env.source) == original


def test_windows_temp_guard_still_refuses_real_temp_boundary(environment, monkeypatch):
    env = environment
    monkeypatch.setattr(isolation.tempfile, "gettempdir", lambda: str(env.tmp))
    if os.name == "nt":
        with pytest.raises(ValueError, match="temporaire Windows"):
            env.service.isolate(create(env))


@pytest.mark.parametrize("missing_name", ["lua51.dll", "lua5.1.dll"])
def test_missing_lua_dll_blocks_isolation_until_source_is_repaired(environment, missing_name):
    env = environment
    run = create(env)
    dll = env.source / missing_name
    verified_dll = dll.read_bytes()
    dll.unlink()
    original = tree(env.source)
    metadata = env.manager.load(run.run_id).to_dict()
    with pytest.raises(ValueError, match="support Lua"):
        env.service.isolate(run)
    assert not env.service.directory(run).exists()
    assert tree(env.source) == original
    assert env.manager.load(run.run_id).to_dict() == metadata
    dll.write_bytes(verified_dll)
    prepared = env.service.isolate(env.manager.load(run.run_id))
    assert (Path(prepared.launch_profile["emulator_path"]).parent / missing_name).read_bytes() == verified_dll
    env.service.validate(prepared)


def test_unknown_emulator_or_unverified_dll_is_not_copied(environment):
    env = environment
    run = create(env)
    (env.source / "lua51.dll").write_bytes(pe_bytes(dll=True, suffix=b"untrusted"))
    with pytest.raises(ValueError, match="support Lua"):
        env.service.isolate(run)
    assert not env.service.directory(run).exists()
    env.exe.write_bytes(pe_bytes(markers=b"DeSmuME lua51.dll", suffix=b"unknown"))
    with pytest.raises(ValueError, match="version DeSmuME"):
        env.service.isolate(run)


@pytest.fixture
def launcher(environment, monkeypatch):
    env = environment
    base = env.tmp / "p"
    env.manager = RunManager(base / "runs")
    env.service = RunIsolationService(env.manager, running_probe=lambda path: False)
    setup = AutoSetupService(base, AppConfig())
    checked = []
    health_check = setup.health_check
    def observe_health(game_id, *args, **kwargs):
        checked.append(deepcopy(kwargs.get("options_override")))
        return health_check(game_id, *args, **kwargs)
    monkeypatch.setattr(setup, "health_check", observe_health)
    # A failed launch must not accidentally scan any real drives in this test.
    monkeypatch.setattr(setup, "automatic_setup", lambda **kwargs: pytest.fail("unexpected global discovery"))
    return SimpleNamespace(env=env, launch=RunLaunchService(base, AppConfig(), setup=setup), checked=checked)


def test_pending_launch_prepares_independent_rom_and_accepts_only_planned_missing_save(launcher):
    item, env = launcher, launcher.env
    run = create(env)
    result = item.launch.prepare(run)
    assert result["health"]["ready"]
    assert item.checked[-1]["save_path"] == ""
    current = env.manager.load(run.run_id)
    assert not current.launch_profile.get("_isolation_pending")
    assert result["profile"]["rom_path"] != str(env.rom)
    assert result["profile"]["save_path"] == current.save_path
    assert not Path(current.save_path).exists()
    Path(current.save_path).write_bytes(b"synthetic later emulator save")
    second = item.launch.prepare(current)
    assert second["health"]["ready"]
    assert item.checked[-1]["save_path"] == current.save_path
    assert env.save.read_bytes() == b"synthetic existing user save"


def test_pending_launch_refuses_active_run_before_any_isolation(launcher):
    item, env = launcher, launcher.env
    run = create(env)
    env.manager.set_active_id(run.run_id)
    before = tree(env.manager.root / run.run_id)
    with pytest.raises(ValueError, match="Mes parties"):
        item.launch.prepare(run)
    assert tree(env.manager.root / run.run_id) == before


def test_isolated_launch_survives_unavailable_original_sources(launcher):
    item, env = launcher, launcher.env
    run = create(env)
    item.launch.prepare(run)
    current = env.manager.load(run.run_id)
    env.source.rename(env.tmp / "source-moved")
    result = item.launch.prepare(current)
    assert result["health"]["ready"]
    assert result["profile"]["rom_path"] == current.launch_profile["rom_path"]


def test_removed_owned_directory_never_rebinds_run_to_source(launcher):
    item, env = launcher, launcher.env
    run = create(env)
    item.launch.prepare(run)
    current = env.manager.load(run.run_id)
    root = env.service.directory(current)
    root.rename(root.with_name("play-moved"))
    assert env.service.is_isolated(current)
    with pytest.raises((ValueError, OSError)):
        item.launch.prepare(current)
    assert env.manager.load(run.run_id).launch_profile == current.launch_profile


@pytest.mark.parametrize("imported", [False, True])
def test_missing_imported_or_previously_observed_save_is_not_a_new_adventure(launcher, imported):
    item, env = launcher, launcher.env
    run = env.service.isolate(create(env), import_save=env.save if imported else None)
    if not imported:
        Path(run.save_path).write_bytes(b"synthetic first save")
        item.launch.prepare(run)
    Path(run.save_path).unlink()
    with pytest.raises(ValueError, match="sauvegarde.*disparu"):
        item.launch.prepare(run)
    assert not Path(run.save_path).exists()
    assert env.save.read_bytes() == b"synthetic existing user save"


def test_pending_preflight_never_overwrites_association_changed_during_check(launcher, monkeypatch):
    item, env = launcher, launcher.env
    run = create(env)
    original = item.launch.setup.health_check
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        env.manager.update(run.run_id, lambda current: current.launch_profile.update(speed="x4"))
        return result
    monkeypatch.setattr(item.launch.setup, "health_check", changed)
    with pytest.raises(ValueError, match="changé pendant la vérification"):
        item.launch.prepare(run)
    assert env.manager.load(run.run_id).launch_profile["speed"] == "x4"
    assert not env.service.directory(run).exists()


@pytest.mark.parametrize("change", ["save_path", "rom_path", "backup_directory", "fingerprint"])
def test_tracking_cannot_replace_owned_references_with_another_adventure(environment, change):
    env = environment
    first = env.service.isolate(create(env))
    second = env.service.isolate(create(env, "Second"))
    tracker = RunTrackingService(env.manager)
    tracker.activate(first.run_id)
    options = deepcopy(first.launch_profile)
    fingerprint = first.rom_fingerprint
    if change == "fingerprint":
        fingerprint = "0" * 64
    else:
        options[change] = second.launch_profile[change]
    with pytest.raises(ValueError, match="indépendants|empreinte"):
        tracker.update_launch_reference(options, fingerprint)
    assert env.manager.load(first.run_id).launch_profile == first.launch_profile
    tracker.deactivate()
