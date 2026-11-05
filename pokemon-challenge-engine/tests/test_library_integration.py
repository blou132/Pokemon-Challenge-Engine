"""Real library/run pipelines with isolated synthetic ROMs and a fake ZX tool.

These checks never discover the personal library and never execute an emulator.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.run_manager import RunManager
from app.services.config_service import AppConfig
from app.services.game_mode_config import GameModeConfigStore
from app.services.library_setup_service import LibrarySetupService, verify_library_source
from app.services.rom_library_service import RomLibraryService
from app.services.run_deletion_service import RunDeletionService
from app.services.run_isolation_service import RunIsolationService
from app.services.run_launch_service import RunLaunchService
from test_auto_discovery import rom_bytes
from test_melonds_run import component
from test_rom_transformation import transformation
from test_run_randomizer_isolation import challenge


@pytest.fixture
def integrated(tmp_path, component, catalog, monkeypatch):
    sources = tmp_path / "originals"
    sources.mkdir()
    source = sources / "personal.nds"
    source.write_bytes(rom_bytes())
    library = RomLibraryService(tmp_path / "permanent-library")
    from app.services import melonds_runtime
    monkeypatch.setattr(melonds_runtime, "find_installation", lambda _base: component)
    base = tmp_path / "build-one-data"
    setup = LibrarySetupService(base, AppConfig(), library, catalog, source_directories=(sources,))
    report = setup.automatic_setup()
    launcher = RunLaunchService(base, AppConfig(), setup=setup)
    return SimpleNamespace(source=source, sources=sources, library=library, setup=setup, report=report,
                           launcher=launcher, base=base, manager=RunManager(base / "runs"),
                           component=component, catalog=catalog)


def new_run(env, *, name="Library adventure", configured=None):
    snapshot = env.launcher.snapshot("white", env.report["launch_profiles"]["white"])
    snapshot["_isolation_pending"] = True
    return env.manager.create(name, "white", game_code="IRAF", region="FR", revision=0,
                              launch_profile=snapshot, challenge=configured)


def owned(env, run):
    result = env.launcher.prepare(run)
    assert result["health"]["ready"]
    return env.manager.load(run.run_id)


def test_new_build_and_data_store_discover_same_library_without_sources_or_reimport(integrated, tmp_path, monkeypatch):
    env = integrated
    entry = env.library.list_entries()[0]
    master = env.library.master_path(entry)
    before = master.read_bytes(), master.stat().st_mtime_ns, env.library.manifest_path.read_bytes()
    env.source.unlink()
    env.sources.rmdir()

    def never_import(*_args):
        raise AssertionError("An already prepared permanent library must not be imported again")

    monkeypatch.setattr(RomLibraryService, "import_directory", never_import)
    upgraded = RomLibraryService(env.library.root)
    # Keep the synthetic Windows staging path below MAX_PATH as in production's
    # short per-user store; the new build still has an independent data root.
    new_base = tmp_path / "v2"
    setup = LibrarySetupService(new_base, AppConfig(), upgraded, env.catalog, source_directories=(env.sources,))
    report = setup.automatic_setup()
    assert report["game_states"]["white"]["status"] == "ready"
    assert report["launch_profiles"]["white"]["rom_path"] == str(master)
    launcher = RunLaunchService(new_base, AppConfig(), setup=setup)
    manager = RunManager(new_base / "runs")
    snapshot = launcher.snapshot("white", report["launch_profiles"]["white"])
    snapshot["_isolation_pending"] = True
    run = manager.create("After update", "white", launch_profile=snapshot)
    assert launcher.prepare(run)["health"]["ready"]
    assert Path(manager.load(run.run_id).launch_profile["rom_path"]).is_relative_to(new_base)
    assert upgraded.resolve("white") == master
    assert (master.read_bytes(), master.stat().st_mtime_ns, env.library.manifest_path.read_bytes()) == before


def test_two_runs_keep_rom_battery_states_and_deletion_independent(integrated):
    env = integrated
    master = env.library.resolve("white")
    before = master.read_bytes(), env.source.read_bytes(), env.library.manifest_path.read_bytes()
    first = owned(env, new_run(env, name="First"))
    second = owned(env, new_run(env, name="Second"))
    for field in ("rom_path", "emulator_path", "ini_path", "save_path", "save_state_directory", "backup_directory"):
        assert first.launch_profile[field] != second.launch_profile[field]
        assert Path(first.launch_profile[field]).is_relative_to(env.manager._directory(first.run_id))
        assert Path(second.launch_profile[field]).is_relative_to(env.manager._directory(second.run_id))
    for run, marker in ((first, b"first"), (second, b"second")):
        game = Path(run.launch_profile["rom_path"])
        assert game.read_bytes() == before[0]
        assert game.stat().st_ino != master.stat().st_ino
        Path(run.save_path).write_bytes(marker)
        (Path(run.launch_profile["save_state_directory"]) / "slot.ml1").write_bytes(marker)
        assert env.launcher.prepare(run)["health"]["ready"]
    deletion = RunDeletionService(env.manager, running_probe=lambda _path: False)
    plan = deletion.preview(first.run_id)
    assert str(master) in plan.preserved_references
    deletion.delete(plan)
    assert not env.manager._directory(first.run_id).exists()
    assert Path(second.save_path).read_bytes() == b"second"
    assert (Path(second.launch_profile["save_state_directory"]) / "slot.ml1").read_bytes() == b"second"
    assert env.launcher.prepare(env.manager.load(second.run_id))["health"]["ready"]
    assert (master.read_bytes(), env.source.read_bytes(), env.library.manifest_path.read_bytes()) == before


@pytest.mark.parametrize("missing", ["original", "master", "manifest"])
def test_owned_run_reopens_without_its_source_library(integrated, missing):
    env = integrated
    run = owned(env, new_run(env))
    Path(run.save_path).write_bytes(b"existing run progress")
    targets = {"original": env.source, "master": env.library.resolve("white"), "manifest": env.library.manifest_path}
    targets[missing].unlink()
    reopened = RunLaunchService(env.base, AppConfig(), setup=LibrarySetupService(
        env.base, AppConfig(), RomLibraryService(env.library.root), env.catalog))
    result = reopened.prepare(RunManager(env.base / "runs").load(run.run_id))
    assert result["health"]["ready"]
    assert Path(result["profile"]["save_path"]).read_bytes() == b"existing run progress"


def test_snapshot_uses_pinned_master_instead_of_stale_legacy_rom(integrated, tmp_path):
    env = integrated
    foreign = tmp_path / "foreign.nds"
    foreign.write_bytes(rom_bytes("IRBF"))
    options = deepcopy(env.report["launch_profiles"]["white"])
    options["rom_path"] = str(foreign)
    snapshot = env.launcher.snapshot("white", options)
    assert snapshot["rom_path"] == str(env.library.resolve("white"))
    assert snapshot["_library_source"]["sha256"] == env.library.list_entries()[0].sha256
    assert options["rom_path"] == str(foreign)


def test_cached_library_reloads_launch_preferences_without_rehashing_masters(integrated, monkeypatch):
    env = integrated
    store = GameModeConfigStore(env.base, AppConfig())
    preferences = store.load()
    preferences['launch_profiles']['white'].update(speed='x4', backup_on_close=True,
                                                   backup_retention=25, rom_path='stale-external.nds')
    store.save(preferences)
    monkeypatch.setattr(env.library, 'verify', lambda: pytest.fail('Unchanged masters need no new full hash'))
    report = env.setup.automatic_setup()
    assert report['cached'] is True
    options = report['launch_profiles']['white']
    assert (options['speed'], options['backup_on_close'], options['backup_retention']) == ('x4', True, 25)
    assert options['rom_path'] == str(env.library.master_path(env.library.list_entries()[0]))
    assert env.launcher.snapshot('white', options)['speed'] == 'x4'


def test_cached_library_refuses_corrupt_preferences_without_overwriting_them(integrated):
    env = integrated
    path = GameModeConfigStore(env.base, AppConfig()).path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{corrupt preference data')
    before = path.read_bytes(), path.stat().st_mtime_ns
    with pytest.raises(ValueError, match='préférences Mode Jeu sont illisibles'):
        env.setup.automatic_setup()
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_corrupt_master_after_setup_is_blocked_before_run_preparation(integrated):
    env = integrated
    run = new_run(env)
    before = env.manager.load(run.run_id).to_dict()
    master = env.library.resolve("white")
    data = bytearray(master.read_bytes())
    data[-1] ^= 1
    master.write_bytes(data)
    with pytest.raises(ValueError, match="Intégrité"):
        env.launcher.prepare(run)
    assert env.manager.load(run.run_id).to_dict() == before
    assert not RunIsolationService(env.manager).directory(run).exists()
    status = env.setup.automatic_setup()
    assert status["game_states"]["white"]["status"] == "needs_attention"
    assert not status["library_integrity"]["white"]["valid"]


@pytest.mark.parametrize("kind", ["rom_path", "reference_hash", "reference_root", "manifest_master"])
def test_rebinding_reference_or_master_is_refused_without_publishing(integrated, tmp_path, kind):
    env = integrated
    run = new_run(env)
    other = tmp_path / "other.nds"
    replacement = bytearray(rom_bytes())
    replacement[-1] ^= 1
    other.write_bytes(replacement)
    if kind == "rom_path":
        run.launch_profile["rom_path"] = str(other)
    elif kind == "reference_hash":
        run.launch_profile["_library_source"]["sha256"] = "f" * 64
    elif kind == "reference_root":
        run.launch_profile["_library_source"]["root"] = str(tmp_path / "another-library")
    else:
        # Simulate an external manifest edit to a different otherwise valid ROM.
        old = json.loads(env.library.manifest_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(replacement).hexdigest()
        target = env.library.root / "masters" / "white" / f"{digest}.nds"
        target.write_bytes(replacement)
        old["entries"][0].update(sha256=digest, relative_path=target.relative_to(env.library.root).as_posix())
        env.library.manifest_path.write_text(json.dumps(old), encoding="utf-8")
    env.manager.save(run)
    with pytest.raises(ValueError, match="référence"):
        env.launcher.prepare(env.manager.load(run.run_id))
    assert not RunIsolationService(env.manager).directory(run).exists()


@pytest.mark.parametrize("randomized", [False, True])
def test_changed_master_between_verification_and_copy_is_refused(integrated, monkeypatch, randomized):
    env = integrated
    run = new_run(env, configured=challenge() if randomized else None)
    master = env.library.resolve("white")
    from app.services import melonds_run_service
    original = melonds_run_service._copy
    changed = []

    def race(source, destination):
        if source == master:
            data = bytearray(source.read_bytes())
            data[-1] ^= 1
            source.write_bytes(data)
            changed.append(True)
        return original(source, destination)

    monkeypatch.setattr(melonds_run_service, "_copy", race)
    before = env.manager.load(run.run_id).to_dict()
    with pytest.raises(ValueError, match="maîtresse a changé pendant la copie"):
        env.launcher.prepare(run)
    assert changed == [True]
    assert env.manager.load(run.run_id).to_dict() == before
    assert not RunIsolationService(env.manager).directory(run).exists()
    assert not tuple(env.manager._directory(run.run_id).glob(".melonds-*"))


def test_randomizer_receives_private_input_and_publishes_owned_output(integrated, transformation, monkeypatch):
    env = integrated
    from app.services import rom_transformation_service
    monkeypatch.setattr(rom_transformation_service.RomTransformationService, "from_local_config",
                        classmethod(lambda _cls, _base: transformation.service))
    master = env.library.resolve("white")
    before = master.read_bytes(), master.stat().st_mtime_ns, env.source.read_bytes()
    seen = []
    transform = transformation.service.transform

    def guarded(source, destination, **kwargs):
        assert source != master and source != env.source
        assert source.is_relative_to(env.manager.root)
        assert source.read_bytes() == before[0]
        seen.append(source)
        return transform(source, destination, **kwargs)

    monkeypatch.setattr(transformation.service, "transform", guarded)
    run = owned(env, new_run(env, configured=challenge()))
    assert seen and not seen[0].exists()
    derived = Path(run.launch_profile["rom_path"])
    assert derived.read_bytes() != before[0]
    assert env.launcher.prepare(run)["health"]["ready"]
    assert (master.read_bytes(), master.stat().st_mtime_ns, env.source.read_bytes()) == before


@pytest.mark.parametrize("failure", ["input_mutation", "tool_failure"])
def test_failed_randomizer_cannot_modify_master_or_original(integrated, transformation, monkeypatch, failure):
    env = integrated
    from app.services import rom_transformation_service
    monkeypatch.setattr(rom_transformation_service.RomTransformationService, "from_local_config",
                        classmethod(lambda _cls, _base: transformation.service))
    master = env.library.resolve("white")
    before = master.read_bytes(), master.stat().st_mtime_ns, env.source.read_bytes()
    seen = []

    def fail(working, _output, _report):
        assert working != master and working != env.source
        assert working.is_relative_to(env.manager.root)
        seen.append(working)
        if failure == "input_mutation":
            working.write_bytes(b"the tool changed only its own private input")
        else:
            raise ValueError("synthetic tool failure")

    transformation.changes["action"] = fail
    run = new_run(env, configured=challenge())
    metadata = env.manager.load(run.run_id).to_dict()
    with pytest.raises(ValueError):
        env.launcher.prepare(run)
    assert seen
    assert env.manager.load(run.run_id).to_dict() == metadata
    assert not RunIsolationService(env.manager).directory(run).exists()
    assert (master.read_bytes(), master.stat().st_mtime_ns, env.source.read_bytes()) == before
    assert env.library.verify()[0].valid


@pytest.mark.parametrize("field,value", [("root", None), ("root", "relative-library"),
                                        ("path", None), ("revision", False), ("sha256", 15)])
def test_malformed_reference_fails_as_validation_error(integrated, field, value):
    env = integrated
    run = new_run(env)
    source = Path(run.launch_profile["rom_path"])
    run.launch_profile["_library_source"][field] = value
    with pytest.raises(ValueError):
        verify_library_source(run, source)
