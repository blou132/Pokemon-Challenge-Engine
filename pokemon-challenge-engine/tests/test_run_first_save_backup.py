"""A new run creates no fake DSV, yet its opt-in launch backup remains enabled."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.run_manager import RunManager
from app.services.config_service import AppConfig
from app.services.emulator_settings_service import IniDocument
from app.services.game_mode_service import GameModeService
from app.services.run_isolation_service import RunIsolationService
from app.services.run_launch_service import RunLaunchService
from app.services.save_manager_service import SaveManagerService
from test_game_mode_service import Launcher, Windows
from test_run_isolation import create, environment


@pytest.fixture
def adventure(environment):
    env = environment
    base = env.tmp / "p"
    env.manager = RunManager(base / "runs")
    env.service = RunIsolationService(env.manager, running_probe=lambda path: False)
    env.options["backup_on_launch"] = True
    run = env.service.isolate(create(env))
    mode = GameModeService(base, AppConfig(), launcher_factory=Launcher, window_manager=Windows())
    options = {key: value for key, value in run.launch_profile.items() if not key.startswith("_")}
    backups = SaveManagerService(Path(options["backup_directory"]))
    return SimpleNamespace(env=env, run=run, mode=mode, options=options, backups=backups)


def test_new_adventure_launches_without_fake_save_then_backs_up_first_real_file_once(adventure):
    item = adventure
    observed = []
    item.mode.backup_observer = observed.append
    process = item.mode.launch("white", options_override=item.options)
    assert process.poll() is None
    assert item.mode._pending_launch_backup
    assert item.env.manager.load(item.run.run_id).launch_profile["backup_on_launch"] is True
    assert not Path(item.run.save_path).exists()
    item.mode.tick()
    assert item.backups.list_backups() == ()
    Path(item.run.save_path).write_bytes(b"synthetic first game save")
    state = item.mode.tick()
    records = item.backups.list_backups()
    assert state.running and "Premier backup créé" in state.message
    assert len(records) == 1 and records[0].reason == "launch"
    assert (item.backups.root / records[0].filename).read_bytes() == b"synthetic first game save"
    assert len(observed) == 1
    Path(item.run.save_path).write_bytes(b"synthetic second game save")
    item.mode.tick()
    assert item.backups.list_backups() == records
    assert item.env.save.read_bytes() == b"synthetic existing user save"


def test_first_save_flushed_at_process_exit_is_backed_up(adventure):
    item = adventure
    process = item.mode.launch("white", options_override=item.options)
    Path(item.run.save_path).write_bytes(b"synthetic save flushed on exit")
    process.code = 0
    state = item.mode.tick()
    assert not state.running and "Premier backup créé" in state.message
    assert len(item.backups.list_backups()) == 1


@pytest.mark.parametrize("save_created", [False, True])
def test_normal_close_remembers_first_save_with_all_backups_disabled(adventure, save_created):
    item = adventure
    options = item.options | {"backup_on_launch": False, "backup_periodic": False, "backup_on_close": False}
    process = item.mode.launch("white", options_override=options)
    save = Path(item.run.save_path)
    if save_created:
        save.write_bytes(b"synthetic save flushed on close")
    process.code = 0
    state = item.mode.tick()
    assert not state.running
    assert "non vérifiée" not in state.message
    assert item.backups.list_backups() == ()
    assert (item.env.service.directory(item.run) / "save-observed.json").exists() is save_created
    if save_created:
        save.unlink()
        launch = RunLaunchService(item.mode.base_dir, AppConfig())
        with pytest.raises(ValueError, match="disparu"):
            launch.prepare(item.env.manager.load(item.run.run_id))
    else:
        assert item.env.service.save_may_be_missing(item.run)


def test_leaving_before_first_save_creates_no_file_or_backup(adventure):
    item = adventure
    process = item.mode.launch("white", options_override=item.options)
    process.code = 0
    assert not item.mode.tick().running
    assert not Path(item.run.save_path).exists()
    assert item.backups.list_backups() == ()
    assert not item.mode._pending_launch_backup


def test_observation_failure_on_close_is_reported_without_leaving_session_active(adventure, monkeypatch):
    item = adventure
    options = item.options | {"backup_on_launch": False, "backup_periodic": False, "backup_on_close": False}
    process = item.mode.launch("white", options_override=options)
    Path(item.run.save_path).write_bytes(b"synthetic first save")
    def denied(*args):
        raise PermissionError("disk unavailable")
    monkeypatch.setattr(RunIsolationService, "mark_save_observed", denied)
    process.code = 0
    state = item.mode.tick()
    assert not state.running and "non vérifiée" in state.message and "disk unavailable" in state.message
    assert item.backups.list_backups() == ()


def test_existing_run_save_keeps_normal_backup_before_launch(adventure):
    item = adventure
    Path(item.run.save_path).write_bytes(b"existing adventure save")
    item.mode.launch("white", options_override=item.options)
    assert not item.mode._pending_launch_backup
    assert len(item.backups.list_backups()) == 1


def test_missing_external_save_still_refuses_launch(adventure):
    item = adventure
    options = item.options | {"save_path": str(item.env.tmp / "missing-external.dsv")}
    with pytest.raises(ValueError, match="introuvable"):
        item.mode.launch("white", options_override=options)
    assert item.mode.process is None
    assert item.backups.list_backups() == ()


@pytest.mark.parametrize("change", ["backup_directory", "rom_path", "manifest"])
def test_missing_save_exception_requires_exact_verified_owned_profile(adventure, change):
    item = adventure
    options = deepcopy(item.options)
    if change == "manifest":
        (item.env.service.directory(item.run) / "isolation.json").write_bytes(b"invalid")
    else:
        options[change] = str(item.env.tmp / "external")
    with pytest.raises(ValueError):
        item.mode.launch("white", options_override=options)
    assert item.mode.process is None


def test_first_backup_revalidates_isolation_after_launch(adventure):
    item = adventure
    item.mode.launch("white", options_override=item.options)
    ini_path = Path(item.options["ini_path"])
    document = IniDocument(ini_path.read_bytes())
    document.set_text("PathSettings", "Battery", str(item.env.source))
    ini_path.write_bytes(document.to_bytes())
    Path(item.run.save_path).write_bytes(b"synthetic first save")
    state = item.mode.tick()
    assert state.running and "Premier backup non créé" in state.message
    assert "Backup manuel" in state.message
    assert item.backups.list_backups() == ()


def test_failed_first_backup_is_reported_and_does_not_loop_or_kill_game(adventure, monkeypatch):
    item = adventure
    process = item.mode.launch("white", options_override=item.options)
    Path(item.run.save_path).write_bytes(b"synthetic first save")
    calls = []
    def denied(*args):
        calls.append(args)
        raise PermissionError("disk unavailable")
    monkeypatch.setattr(item.mode, "_backup", denied)
    state = item.mode.tick()
    assert state.running and "Premier backup non créé" in state.message
    assert "disk unavailable" in state.message
    item.mode.tick()
    assert len(calls) == 1 and process.poll() is None


def test_stop_tracking_cancels_deferred_backup(adventure):
    item = adventure
    process = item.mode.launch("white", options_override=item.options)
    item.mode.stop_tracking()
    Path(item.run.save_path).write_bytes(b"save after stopping PCE tracking")
    item.mode.tick()
    assert process.poll() is None and not item.mode._pending_launch_backup
    assert item.backups.list_backups() == ()
