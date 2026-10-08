"""Native Qt orchestration over synthetic local files; no actual game is launched."""

from dataclasses import replace
import os
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from app.services.auto_setup_service import AutoSetupService
from app.services.launcher_service import LauncherService
from app.ui.main_window import MainWindow
from app.ui.run_dialogs import NewRunDialog
from test_auto_discovery import rom_bytes
from test_auto_setup_service import environment
from test_automatic_setup_flow import automatic


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def until(app, predicate, *, timeout=8):
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
        sleep(0.005)  # Give Python filesystem workers the GIL as well as Qt events.
    assert predicate()


@pytest.fixture
def startup(qt_app, catalog, automatic, monkeypatch):
    env = automatic
    # Represent the standard <drive>/RetroBat location without preconfigured
    # paths. The imported fixture bounds drive discovery to this temp directory.
    original_root = env.root
    discovered_root = original_root.with_name("RetroBat")
    assert discovered_root.parent == original_root.parent and not discovered_root.exists()
    original_root.rename(discovered_root)
    for name in ("exe", "ini", "save", "source"):
        setattr(env, name, discovered_root / getattr(env, name).relative_to(original_root))
    env.root = discovered_root
    env.service.legacy.retrobat_path = ""
    popups, launches = [], []
    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name,
            lambda *args, kind=name, **kwargs: popups.append((kind, args[1:])) or QMessageBox.StandardButton.Ok)

    def unexpected_launch(_launcher, game_id):
        launches.append(game_id)
        raise AssertionError("No emulator should launch during startup or creation")

    monkeypatch.setattr(LauncherService, "launch", unexpected_launch)
    window = MainWindow(catalog, env.service.base_dir)
    window._setup_service = env.service
    window.show()
    context = SimpleNamespace(env=env, window=window, popups=popups, launches=launches)
    try:
        yield context
    finally:
        until(qt_app, lambda: not window.discovery_runner.is_busy and not window.run_prepare.is_busy)
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def start(context, app):
    QTimer.singleShot(0, context.window.start_first_run)
    until(app, lambda: context.window._discovery_report is not None and
          not context.window.discovery_runner.is_busy)
    return context.window._discovery_report


def originals(env):
    return {path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in (env.source, env.exe, env.ini, env.save)}


def test_startup_detects_and_prepares_zip_save_emulator_without_manual_action_or_popup(startup, qt_app):
    env, window = startup.env, startup.window
    before = originals(env)
    assert not window.config.retrobat_path and not window.config.desmume_path
    assert not any(window.config.rom_paths.values())
    assert not window.config_service.path.exists()
    report = start(startup, qt_app)

    assert isinstance(window.setup_service(), AutoSetupService)
    assert window.pages.currentWidget() is window.runs_page
    assert report["ready"]
    white = report["game_states"]["white"]
    assert white["status"] == "ready"
    assert white["emulator_path"] == str(env.exe)
    assert white["save_path"] == str(env.save)
    assert Path(white["profile"]["rom_path"]).is_relative_to(env.service.cache_root)
    assert Path(white["profile"]["rom_path"]).read_bytes() == rom_bytes()
    assert all(report["game_states"][game]["status"] == "not_found" for game in ("black", "black2", "white2"))
    assert "Prête" in window.runs_page.installation_label.text()
    assert "Prêt" in window.runs_page.installation_games["white"].text()
    assert window.installation_dialog is None and window.game_mode_window is None
    assert startup.popups == [] and startup.launches == []
    assert originals(env) == before


def test_startup_without_any_game_keeps_library_usable_without_global_popup(startup, qt_app):
    startup.env.source.unlink()
    report = start(startup, qt_app)
    window = startup.window

    assert not report["ready"]
    assert all(item["status"] == "not_found" for item in report["game_states"].values())
    assert window.pages.currentWidget() is window.runs_page
    assert window.runs_page.new_button.isEnabled()
    assert window.runs.list_runs() == []
    assert window.installation_dialog is None
    assert startup.popups == [] and startup.launches == []


def test_return_to_library_rechecks_changed_files_and_updates_selected_game(startup, qt_app):
    start(startup, qt_app)
    window, env = startup.window, startup.env
    window.navigate(0)
    (env.exe.parent / "lua51.dll").unlink()
    completed = QSignalSpy(window.discovery_runner.succeeded)
    window.navigate(6)
    until(qt_app, lambda: completed.count() == 1 and not window.discovery_runner.is_busy)

    assert window._discovery_report["game_states"]["white"]["status"] == "lua_required"
    assert not window._discovery_report["ready"]
    assert "Lua requis" in window.runs_page.installation_games["white"].text()
    assert startup.popups == [] and startup.launches == []


def test_new_run_uses_detected_white_and_save_with_real_dialog_and_persistence(startup, qt_app, monkeypatch):
    start(startup, qt_app)
    window, env = startup.window, startup.env
    before = originals(env)
    resumed, observed = [], {}
    monkeypatch.setattr(window, "resume_run", resumed.append)

    def accept_dialog():
        dialog = window.findChild(NewRunDialog)
        observed.update(game_id=dialog.game_combo.currentData(), save_path=dialog.save_edit.text(),
                        source=dialog.source_combo.currentData(), configured_save_hidden=dialog.configured_save_button.isHidden())
        dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).click()

    QTimer.singleShot(0, accept_dialog)
    run = window.new_run()
    until(qt_app, lambda: not window.discovery_runner.is_busy)

    assert observed == {"game_id": "white", "save_path": str(env.save), "source": "classic", "configured_save_hidden": True}
    assert run is not None and resumed == [run.run_id]
    stored = window.runs.load(run.run_id)
    assert stored.game_id == "white" and stored.game_code == "IRAF"
    assert stored.save_path == str(env.save)
    assert stored.profile_id is None and stored.active_rules == ()
    assert stored.launch_profile["emulator_path"] == str(env.exe)
    assert stored.launch_profile["_source"]["source_path"] == str(env.source)
    assert Path(stored.launch_profile["rom_path"]).is_relative_to(env.service.cache_root)
    assert len(window.runs.list_runs()) == 1
    assert originals(env) == before
    assert startup.popups == [] and startup.launches == []


def test_discovery_worker_leaves_qt_navigation_and_timers_responsive(startup, qt_app, monkeypatch):
    env, window = startup.env, startup.window
    entered, release = Event(), Event()
    original_scan = env.service.scan

    def gated_scan(*args, **kwargs):
        entered.set()
        if not release.wait(5):
            raise AssertionError("Test did not release the discovery worker")
        return original_scan(*args, **kwargs)

    monkeypatch.setattr(env.service, "scan", gated_scan)
    ticks = []
    timer = QTimer(window)
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(True))
    try:
        window.start_first_run()
        until(qt_app, entered.is_set)
        timer.start()
        until(qt_app, lambda: len(ticks) >= 3)
        window.navigate(0)
        assert window.pages.currentWidget() is window.home_page
        assert window.discovery_runner.is_busy
        assert window._discovery_report is None
    finally:
        timer.stop()
        release.set()
        until(qt_app, lambda: not window.discovery_runner.is_busy)
    assert window._discovery_report["game_states"]["white"]["status"] == "ready"


def test_manual_configuration_changed_during_scan_is_applied_after_completion(startup, qt_app, monkeypatch):
    env, window = startup.env, startup.window
    entered, release = Event(), Event()
    original_scan = env.service.scan
    scans = []

    def gated_first_scan(*args, **kwargs):
        scans.append(True)
        if len(scans) == 1:
            entered.set()
            if not release.wait(5):
                raise AssertionError("Test did not release the discovery worker")
        return original_scan(*args, **kwargs)

    monkeypatch.setattr(env.service, "scan", gated_first_scan)
    manual_rom = env.root / "manual" / "white.nds"
    manual_rom.parent.mkdir()
    completed = QSignalSpy(window.discovery_runner.succeeded)
    failed = QSignalSpy(window.discovery_runner.failed)
    try:
        window.start_first_run()
        until(qt_app, entered.is_set)
        manual_rom.write_bytes(rom_bytes())
        changed = replace(window.config, rom_paths=window.config.rom_paths | {"white": str(manual_rom)})
        window.config_service.save(changed)
        window.config_changed(changed)
        assert window.discovery_runner.is_busy
        assert window._manual_config_changes
    finally:
        release.set()
        try:
            # This path performs two real filesystem scans and atomic writes.
            until(qt_app, lambda: not window.discovery_runner.is_busy and (completed.count() >= 2 or failed.count()), timeout=20)
        except AssertionError:
            pytest.fail(str({"scans": len(scans), "completed": completed.count(), "failed": failed.count(),
                             "pending": window._discovery_pending, "edits": len(window._manual_config_changes),
                             "busy": window.discovery_runner.is_busy, "session_busy": window._session_busy(),
                             "closing": window._closing, "status": window.statusBar().currentMessage()}))

    assert failed.count() == 0, failed.at(0) if failed.count() else ""
    assert not window._manual_config_changes
    assert len(scans) == 2
    assert window.config.rom_paths["white"] == str(manual_rom)
    assert window.config_service.load().rom_paths["white"] == str(manual_rom)
    assert env.service._preferences()[1]["launch_profiles"]["white"]["rom_path"] == str(manual_rom)
    assert window._discovery_report["game_states"]["white"]["profile"]["rom_path"] == str(manual_rom)
    assert startup.popups == [] and startup.launches == []


def test_failed_manual_config_write_preserves_choice_until_explicit_retry_without_loop(startup, qt_app, monkeypatch):
    start(startup, qt_app)
    env, window = startup.env, startup.window
    original_apply = env.service.apply_manual_config
    attempts = []

    def fail_once(previous, current):
        attempts.append(current.rom_paths["white"])
        if len(attempts) == 1:
            raise PermissionError("Synthetic preferences write denied")
        return original_apply(previous, current)

    monkeypatch.setattr(env.service, "apply_manual_config", fail_once)
    manual_rom = env.root / "manual" / "white.nds"
    manual_rom.parent.mkdir()
    manual_rom.write_bytes(rom_bytes())
    changed = replace(window.config, rom_paths=window.config.rom_paths | {"white": str(manual_rom)})
    window.config_service.save(changed)
    failed = QSignalSpy(window.discovery_runner.failed)
    window.config_changed(changed)
    until(qt_app, lambda: failed.count() == 1 and not window.discovery_runner.is_busy)

    assert window._manual_config_changes
    assert "Synthetic preferences write denied" in window.runs_page.installation_label.text()
    for _ in range(20):
        qt_app.processEvents()
        QTest.qWait(2)
        sleep(0.001)
    assert attempts == [str(manual_rom)]
    assert not window.discovery_runner.is_busy

    window.refresh_installation(force=True)
    until(qt_app, lambda: not window.discovery_runner.is_busy and not window._manual_config_changes)
    assert attempts == [str(manual_rom), str(manual_rom)]
    assert window._discovery_report["game_states"]["white"]["status"] == "ready"
    assert env.service._preferences()[1]["launch_profiles"]["white"]["rom_path"] == str(manual_rom)
    assert window.config_service.load().rom_paths["white"] == str(manual_rom)
    assert startup.popups == [] and startup.launches == []


def test_deferred_discovery_resumes_when_session_stops(startup, qt_app, monkeypatch):
    window = startup.window
    busy = [True]
    monkeypatch.setattr(window, "_session_busy", lambda: busy[0])
    window.start_first_run()
    assert window._discovery_pending and not window.discovery_runner.is_busy
    busy[0] = False
    window.bridge_controller.state_changed.emit(window.bridge_controller.state)
    until(qt_app, lambda: window._discovery_report is not None and not window.discovery_runner.is_busy)
    assert not window._discovery_pending
    assert window._discovery_report["game_states"]["white"]["status"] == "ready"


def test_closing_does_not_start_deferred_discovery_during_bridge_shutdown(startup, monkeypatch):
    window = startup.window
    window._discovery_pending = True
    monkeypatch.setattr(window.discovery_runner, "start", lambda *_: pytest.fail("Discovery started while closing"))
    shutdown = window.bridge_controller.shutdown

    def stopped_during_shutdown():
        window.bridge_controller.state_changed.emit(window.bridge_controller.state)
        shutdown()

    monkeypatch.setattr(window.bridge_controller, "shutdown", stopped_during_shutdown)
    window.close()
    assert not window.isVisible()


def test_periodic_file_check_updates_library_without_navigation(startup, qt_app):
    start(startup, qt_app)
    window, env = startup.window, startup.env
    assert window._installation_watch.isActive()
    assert window._installation_watch.interval() == 30_000
    (env.exe.parent / "lua51.dll").unlink()
    completed = QSignalSpy(window.discovery_runner.succeeded)
    window._installation_watch.timeout.emit()
    until(qt_app, lambda: completed.count() == 1 and not window.discovery_runner.is_busy)
    assert window.pages.currentWidget() is window.runs_page
    assert window._discovery_report["game_states"]["white"]["status"] == "lua_required"
    assert startup.popups == [] and startup.launches == []
