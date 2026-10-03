"""Synthetic UI integration at run/save/process boundaries; no actual emulator."""
from copy import deepcopy
from types import SimpleNamespace

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from app.core.run_manager import RunManager
from app.models.challenge import Challenge
from app.services.game_mode_service import RunState
from app.services.launcher_service import LauncherService
from app.services.run_launch_service import RunLaunchService
from app.ui.main_window import MainWindow
from test_run_integration import create, qt_app, until


def select_run(window, run, qt_app, monkeypatch):
    def prepare(service, selected):
        return {"run_id": selected.run_id, "game_id": selected.game_id,
                "profile": deepcopy(selected.launch_profile), "rom_fingerprint": None,
                "health": {"ready": False, "issues": ["Synthetic environment"]}}
    monkeypatch.setattr(RunLaunchService, "prepare", prepare)
    window.resume_run(run.run_id)
    until(qt_app, lambda: window.game_mode_window is not None
          and window.game_mode_window.persistent_run is not None)
    return window.game_mode_window


def prepared_result(run):
    options = deepcopy(run.launch_profile)
    options["rom_path"] = "newly-prepared-synthetic.nds"
    return {"run_id": run.run_id, "game_id": run.game_id, "profile": options,
            "rom_fingerprint": "a" * 64, "health": {"ready": True, "issues": []}}


def test_archived_inactive_run_can_change_status_without_launch_or_session(qt_app, tmp_path, catalog):
    window = MainWindow(catalog, tmp_path)
    run = create(window.runs, tmp_path, catalog)
    window.runs.update(run.run_id, lambda item: setattr(item, "status", "archived"))
    try:
        assert window.run_controller.active_run is None
        window._run_action(run.run_id, "set_status", {"status": "active"})
        until(qt_app, lambda: window.runs.load(run.run_id).status == "active")
        saved = window.runs.load(run.run_id)
        assert saved.sessions == [] and saved.total_play_seconds == 0
        assert saved.history[-1]["type"] == "status_changed"
        assert window.game_mode_window is None
        assert window.run_controller.active_run is None
        assert window.runs.active_id is None
    finally:
        window.close()
        qt_app.processEvents()


def test_selected_run_blocks_the_legacy_profile_launcher(qt_app, tmp_path, catalog, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    run = create(window.runs, tmp_path, catalog)
    calls = []
    monkeypatch.setattr(LauncherService, "validate", lambda *args: [])
    monkeypatch.setattr(LauncherService, "launch", lambda *args: calls.append("unsafe launch"))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    window.run_controller.active_run = run
    try:
        window.launch_challenge(Challenge.from_dict(run.rules_snapshot))
        assert calls == []
    finally:
        window.close()
        qt_app.processEvents()


def test_closing_only_game_mode_keeps_owned_process_and_monitor(qt_app, tmp_path, catalog, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    run = create(window.runs, tmp_path, catalog)
    try:
        mode = select_run(window, run, qt_app, monkeypatch)
        process = SimpleNamespace(pid=424242, poll=lambda: None)
        mode.service.process = process
        mode.service._started = mode.service._last_periodic = mode.service._clock()
        mode.service._run_options = deepcopy(run.launch_profile)
        mode.service.state = RunState(game_id="white", running=True, pid=process.pid)
        mode.service.windows = SimpleNamespace(find=lambda *args: None)
        mode.close()
        qt_app.processEvents()
        assert mode.service.process is process
        assert mode.service.state.running
        assert mode.timer.isActive()
        window.open_game_mode()
        assert window.game_mode_window is mode
        assert mode.service.process is process
        mode.refresh_run()
        assert mode.service.state.running
    finally:
        window.close()
        qt_app.processEvents()


def test_prepared_run_is_not_launched_when_reference_save_fails(qt_app, tmp_path, catalog, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    run = create(window.runs, tmp_path, catalog)
    launches = []
    try:
        mode = select_run(window, run, qt_app, monkeypatch)
        monkeypatch.setattr(mode, "_launch_process", lambda *args, **kwargs: launches.append(args))
        with monkeypatch.context() as failing:
            def fail_save(manager, value):
                raise PermissionError("Synthetic disk write failure")
            failing.setattr(RunManager, "save", fail_save)
            mode._play_prepared(prepared_result(run))
            until(qt_app, lambda: bool(window.run_controller.state.get("error")))
            for _ in range(3):
                qt_app.processEvents()
                QTest.qWait(5)
            assert launches == []
            assert window.runs.load(run.run_id).launch_profile["rom_path"] == run.launch_profile["rom_path"]
    finally:
        window.close()
        qt_app.processEvents()


def test_launch_occurs_only_after_snapshot_and_fingerprint_are_durable(qt_app, tmp_path, catalog, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    run = create(window.runs, tmp_path, catalog)
    observed_at_launch = []
    try:
        mode = select_run(window, run, qt_app, monkeypatch)
        def launch(*args, **kwargs):
            saved = RunManager(tmp_path / "runs").load(run.run_id)
            observed_at_launch.append((saved.launch_profile["rom_path"], saved.rom_fingerprint))
        monkeypatch.setattr(mode, "_launch_process", launch)
        result = prepared_result(run)
        mode._play_prepared(result)
        until(qt_app, lambda: bool(observed_at_launch))
        assert observed_at_launch == [(result["profile"]["rom_path"], result["rom_fingerprint"])]
    finally:
        window.close()
        qt_app.processEvents()
