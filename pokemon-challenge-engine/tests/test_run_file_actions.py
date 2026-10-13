"""Run file orchestration with real Qt workers and synthetic files/processes."""

from dataclasses import replace
from threading import get_ident
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QMetaObject, Qt
from PySide6.QtWidgets import QMainWindow, QMessageBox

from app.bridge.state import BridgeState
from app.services.emulator_window_manager import EmulatorWindow, EmulatorWindowManager
from app.services.game_mode_config import launch_defaults
from app.services.run_deletion_service import RunDeletionService
from app.services.run_isolation_service import RunIsolationService
from app.ui.main_window import MainWindow
from test_game_mode_service import Launcher, Windows, service
from test_run_integration import create, qt_app, until


@pytest.fixture
def files_window(qt_app, tmp_path, catalog, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    window._open_after_activation = False
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[1:]))
    window.test_warnings = warnings
    try:
        yield window
    finally:
        window._switch_timer.stop()
        window._switch_target = None
        if window._switch_dialog is not None:
            window._switch_dialog.close()
        if window.game_mode_window is not None and not isinstance(window.game_mode_window, QMainWindow):
            window.game_mode_window = None
        window.bridge_controller.state = BridgeState()
        until(qt_app, lambda: not window.run_files.is_busy and not window.run_prepare.is_busy
              and not window.run_controller.activation_pending)
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def activate(window, app, run):
    window.run_controller.activate(run.run_id)
    until(app, lambda: window.run_controller.active_run is not None
          and not window.run_controller.activation_pending)
    assert window.runs.active_id == run.run_id


def modal_answer(monkeypatch, answer):
    seen = []

    def execute(dialog):
        seen.append({"title": dialog.windowTitle(), "text": dialog.text(),
                     "details": dialog.detailedText(), "info": dialog.informativeText(),
                     "default": dialog.standardButton(dialog.defaultButton())})
        return answer

    monkeypatch.setattr(QMessageBox, "exec", execute)
    return seen


def test_delete_flushes_queued_changes_and_detaches_autosave_before_worker_preview(
        files_window, qt_app, tmp_path, catalog, monkeypatch):
    window = files_window
    run = create(window.runs, tmp_path, catalog)
    kept = create(window.runs, tmp_path, catalog, "À conserver")
    activate(window, qt_app, run)
    window.run_controller.action(run.run_id, "add_note", {"text": "Dernière action avant suppression"})
    calls = []
    original_preview = RunDeletionService.preview
    main_thread = get_ident()

    def preview(deletion, run_id):
        saved = deletion.manager.load(run_id)
        calls.append((get_ident(), deletion.manager.active_id, saved.notes[-1]["text"]))
        return original_preview(deletion, run_id)

    monkeypatch.setattr(RunDeletionService, "preview", preview)
    seen = modal_answer(monkeypatch, QMessageBox.StandardButton.Yes)
    window._manage_run_files(run.run_id, "delete")
    # Inventory + confirmed deletion each use an I/O worker. Yield the GIL
    # explicitly while pumping Qt so the full suite cannot starve those workers.
    from time import monotonic, sleep
    deadline = monotonic() + 20
    while window.run_files.is_busy or (window.runs.root / run.run_id).exists():
        qt_app.processEvents()
        if window.test_warnings or monotonic() >= deadline:
            break
        sleep(0.005)
    assert not window.run_files.is_busy and not (window.runs.root / run.run_id).exists(), window.test_warnings
    assert calls == [(calls[0][0], None, "Dernière action avant suppression")]
    assert calls[0][0] != main_thread
    assert seen[0]["default"] == QMessageBox.StandardButton.Cancel
    assert "run.json" in seen[0]["details"]
    assert window.run_controller.active_run is None
    assert window.run_controller.requested_run_id is None and window._requested_run_id is None
    assert window.runs.active_id is None
    QMetaObject.invokeMethod(window.run_controller._worker, "tick", Qt.ConnectionType.BlockingQueuedConnection)
    qt_app.processEvents()
    assert not (window.runs.root / run.run_id).exists()
    assert window.runs.load(kept.run_id).name == "À conserver"
    assert not window.test_warnings


def test_delete_confirmation_lists_owned_files_and_preserves_external_references_on_cancel(
        files_window, qt_app, tmp_path, catalog, monkeypatch):
    window = files_window
    source = tmp_path / "original.nds"
    save = tmp_path / "original.dsv"
    source.write_bytes(b"synthetic source ROM")
    save.write_bytes(b"synthetic external save")
    run = create(window.runs, tmp_path, catalog)
    run.save_path = str(save)
    run.launch_profile["rom_path"] = str(source)
    run.launch_profile["save_path"] = str(save)
    window.runs.save(run)
    before = {path: path.read_bytes() for path in (source, save, window.runs.root / run.run_id / "run.json")}
    seen = modal_answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    window._manage_run_files(run.run_id, "delete")
    until(qt_app, lambda: bool(seen) and not window.run_files.is_busy)
    assert str(source) in seen[0]["details"] and str(save) in seen[0]["details"]
    assert "Références externes conservées" in seen[0]["details"]
    assert "Archiver" in seen[0]["info"]
    assert {path: path.read_bytes() for path in before} == before
    assert not window.test_warnings


@pytest.mark.parametrize("busy", ["bridge", "emulator", "preparing", "file_worker", "activation"])
def test_delete_refuses_busy_session_or_preparation(files_window, tmp_path, catalog, monkeypatch, busy):
    window = files_window
    run = create(window.runs, tmp_path, catalog)
    before = (window.runs.root / run.run_id / "run.json").read_bytes()
    previews = []
    monkeypatch.setattr(RunDeletionService, "preview", lambda *args: previews.append(args))
    if busy == "bridge":
        window.bridge_controller.state = BridgeState(status="receiving")
    elif busy == "emulator":
        window.game_mode_window = SimpleNamespace(service=SimpleNamespace(state=SimpleNamespace(running=True)), launch_busy=False)
    elif busy == "activation":
        window.run_controller.activation_pending = True
    else:
        runner = window.run_prepare if busy == "preparing" else window.run_files
        runner._thread = object()  # A busy status, without starting a test process.
    try:
        window._manage_run_files(run.run_id, "delete")
        assert previews == [] and window.test_warnings[0][0] == "Partie occupée"
        assert (window.runs.root / run.run_id / "run.json").read_bytes() == before
    finally:
        window.run_controller.activation_pending = False
        if busy in {"preparing", "file_worker"}:
            runner._thread = None


def test_session_start_during_delete_confirmation_cancels_action(
        files_window, qt_app, tmp_path, catalog, monkeypatch):
    window = files_window
    run = create(window.runs, tmp_path, catalog)

    def answer(dialog):
        window.bridge_controller.state = BridgeState(status="receiving")
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "exec", answer)
    window._manage_run_files(run.run_id, "delete")
    until(qt_app, lambda: bool(window.test_warnings) and not window.run_files.is_busy)
    assert window.runs.load(run.run_id).run_id == run.run_id
    assert "suppression annulée" in window.test_warnings[0][1]


def test_worker_running_context_refuses_delete_before_window_status_catches_up(
        files_window, qt_app, tmp_path, catalog, monkeypatch):
    window = files_window
    run = create(window.runs, tmp_path, catalog)
    activate(window, qt_app, run)
    previews = []
    monkeypatch.setattr(RunDeletionService, "preview", lambda *args: previews.append(args))
    # The process notification and detach are ordered on the real worker queue.
    window.run_controller.process_context(True, "white")
    try:
        window._manage_run_files(run.run_id, "delete")
        assert previews == [] and not window.run_files.is_busy
        assert window.runs.active_id == run.run_id
        assert window.run_controller.active_run.run_id == run.run_id
        assert window.runs.load(run.run_id).run_id == run.run_id
        assert "Fermez DeSmuME" in window.test_warnings[-1][1]
    finally:
        window.run_controller.process_context(False, None)


def test_final_tracking_write_failure_blocks_deletion(
        files_window, qt_app, tmp_path, catalog, monkeypatch):
    from app.services.run_tracking_service import RunTrackingService
    window = files_window
    run = create(window.runs, tmp_path, catalog)
    activate(window, qt_app, run)
    before = window.runs.load(run.run_id).to_dict()
    previews = []
    monkeypatch.setattr(RunDeletionService, "preview", lambda *args: previews.append(args))

    def denied(*args, **kwargs):
        raise PermissionError("Synthetic final write denied")

    with monkeypatch.context() as guarded:
        guarded.setattr(RunTrackingService, "flush", denied)
        window._manage_run_files(run.run_id, "delete")
        assert previews == [] and not window.run_files.is_busy
        assert window.runs.load(run.run_id).to_dict() == before
        assert window.runs.active_id == run.run_id
        assert "final write denied" in window.test_warnings[-1][1]


def test_cancel_isolation_keeps_active_run_and_original_metadata(
        files_window, qt_app, tmp_path, catalog, monkeypatch):
    window = files_window
    run = create(window.runs, tmp_path, catalog)
    activate(window, qt_app, run)
    before = window.runs.load(run.run_id).to_dict()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    called = []
    monkeypatch.setattr(RunIsolationService, "isolate", lambda *args, **kwargs: called.append(args))
    window._manage_run_files(run.run_id, "isolate")
    assert not window.run_files.is_busy and called == []
    assert window.runs.active_id == run.run_id
    assert window.runs.load(run.run_id).to_dict() == before


def test_isolation_worker_receives_exact_run_and_explicit_import_then_resumes_it(
        files_window, qt_app, tmp_path, catalog, monkeypatch):
    window = files_window
    run = create(window.runs, tmp_path, catalog)
    run.save_path = str(tmp_path / "chosen.dsv")
    window.runs.save(run)
    activate(window, qt_app, run)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    calls, resumed = [], []
    main_thread = get_ident()

    def isolate(isolation, selected, **kwargs):
        calls.append((get_ident(), isolation.manager.active_id, selected.run_id, kwargs))
        return selected

    monkeypatch.setattr(RunIsolationService, "isolate", isolate)
    monkeypatch.setattr(window, "resume_run", resumed.append)
    window._manage_run_files(run.run_id, "isolate")
    until(qt_app, lambda: bool(resumed) and not window.run_files.is_busy)
    assert calls[0][0] != main_thread and calls[0][1] is None
    assert calls[0][2:] == (run.run_id, {"import_save": run.save_path, "import_states": True})
    assert resumed == [run.run_id]
    assert not window.test_warnings


def test_change_game_offer_is_nonmodal_and_cancel_never_closes_emulator(files_window, monkeypatch):
    window = files_window
    closed = []
    monkeypatch.setattr(window, "_begin_switch", closed.append)
    window._offer_session_switch("synthetic-request")
    assert window._switch_dialog.isVisible()
    assert "Aucune fermeture forcée" in window._switch_dialog.informativeText()
    assert closed == []
    cancel = next(button for button in window._switch_dialog.buttons() if button.text() == "Annuler")
    cancel.click()
    assert closed == [] and window._switch_target is None


def test_change_game_waits_for_owned_emulator_then_lua_before_resuming(files_window, monkeypatch):
    window = files_window
    window._requested_run_id = "black2-target"
    calls = []
    state = SimpleNamespace(running=True)
    mode = SimpleNamespace(service=SimpleNamespace(state=state, request_close=lambda: calls.append("close")),
                           launch_busy=False, refresh_run=lambda: calls.append("poll"))
    window.game_mode_window = mode
    window.bridge_controller.state = BridgeState(status="receiving")

    def stop_bridge():
        calls.append("stop_lua")
        window.bridge_controller.state = BridgeState()

    monkeypatch.setattr(window.bridge_controller, "stop", stop_bridge)
    monkeypatch.setattr(window.run_controller, "process_context", lambda *args: calls.append(("process", args)))
    monkeypatch.setattr(window.run_controller, "deactivate", lambda: calls.append("detach"))
    monkeypatch.setattr(window, "resume_run", lambda run_id: calls.append(("resume", run_id)))
    window._begin_switch("black2-target")
    assert calls == ["close"]
    window._continue_switch()
    assert calls == ["close", "poll"]
    assert window._switch_target == "black2-target"
    state.running = False
    window._continue_switch()
    assert calls[-2:] == ["poll", "stop_lua"]
    window._continue_switch()
    assert calls[-3:] == [("process", (False, None)), "detach", ("resume", "black2-target")]
    assert window._switch_target is None and not window._switch_timer.isActive()


def test_change_game_timeout_keeps_previous_emulator_and_does_not_resume(files_window, monkeypatch):
    window = files_window
    window._requested_run_id = "black2-target"
    calls = []
    window.game_mode_window = SimpleNamespace(
        service=SimpleNamespace(state=SimpleNamespace(running=True), request_close=lambda: calls.append("close")),
        launch_busy=False, refresh_run=lambda: None)
    monkeypatch.setattr(window, "resume_run", calls.append)
    window._begin_switch("black2-target")
    window._switch_ticks = 149
    window._continue_switch()
    assert calls == ["close"]
    assert window.game_mode_window.service.state.running
    assert window._switch_target is None and not window._switch_timer.isActive()
    assert "interrompu" in window.statusBar().currentMessage()


def test_outdated_change_game_confirmation_never_closes_current_session(files_window):
    window = files_window
    calls = []
    window.game_mode_window = SimpleNamespace(
        service=SimpleNamespace(state=SimpleNamespace(running=True), request_close=lambda: calls.append("close")),
        launch_busy=False)
    window._requested_run_id = "black2-target"
    window._offer_session_switch("black2-target")
    window._requested_run_id = "white-target"
    proceed = next(button for button in window._switch_dialog.buttons()
                   if button.text() == "Fermer la session et continuer")
    proceed.click()
    assert calls == []
    assert window._switch_target is None and not window._switch_timer.isActive()
    assert window._requested_run_id == "white-target"


def test_close_backup_is_recorded_for_old_active_run_while_next_run_is_requested(
        files_window, qt_app, tmp_path, catalog, monkeypatch):
    window = files_window
    first = create(window.runs, tmp_path, catalog, "Blanc A")
    second = window.runs.create("Noir 2 B", "black2")
    source = tmp_path / "first.dsv"
    source.write_bytes(b"synthetic game save; no emulator is opened")
    original = source.read_bytes()
    first.save_path = str(source)
    first.launch_profile.update(save_path=str(source), backup_directory=str(tmp_path / "first-backups"),
                                backup_on_close=True)
    window.runs.save(first)
    activate(window, qt_app, first)
    mode = window._ensure_game_mode()
    mode.bind_requested_run(window.run_controller.active_run, window.run_controller.state)
    monkeypatch.setattr(mode.service, "_launcher_factory", Launcher)
    monkeypatch.setattr(mode.service, "windows", Windows())
    process = mode.service.launch("white", options_override=first.launch_profile)
    mode.refresh_run()
    window._request_run(second.run_id)
    # Only a system backup from the still-active adventure may cross this
    # selection boundary. A stale manual action and a backup for B are refused.
    window._run_action(first.run_id, "add_note", {"text": "Stale action must not be saved"})
    window._run_action(second.run_id, "record_backup", {"payload": {"reason": "close"}})
    resumed = []
    monkeypatch.setattr(window, "resume_run", resumed.append)
    monkeypatch.setattr(mode.service, "request_close", lambda: setattr(process, "code", 0))
    window._begin_switch(second.run_id)
    window._continue_switch()
    assert resumed == [second.run_id]
    saved = window.runs.load(first.run_id)
    backups = [event for event in saved.history if event["type"] == "backup_created"]
    assert len(backups) == 1 and backups[0]["source"] == "system"
    assert backups[0]["payload"]["game_id"] == "white"
    assert backups[0]["payload"]["reason"] == "close"
    backup_file = tmp_path / "first-backups" / backups[0]["payload"]["filename"]
    assert backup_file.read_bytes() == original and source.read_bytes() == original
    assert saved.notes == []
    assert window.runs.load(second.run_id).notes == []
    assert [event["type"] for event in window.runs.load(second.run_id).history] == ["run_created"]
    assert window.run_controller.active_run is None
    assert not window.test_warnings


def legacy_without_launch_profile(window, app):
    """Use real preparation and Qt workers over a bounded, missing installation."""
    run = window.runs.create("Ancienne partie sans configuration", "white")
    assert run.launch_profile is None
    window._setup_service = SimpleNamespace(
        health_check=lambda *args, **kwargs: {"ready": False, "launch_ready": False, "issues": ["Installation synthétique absente"]},
        automatic_setup=lambda **kwargs: {"game_states": {"white": {"status": "not_found", "message": "ROM absente"}},
                                          "games": [], "emulators": []})
    window.resume_run(run.run_id)
    until(app, lambda: window.game_mode_window is not None and window.game_mode_window.persistent_run is not None
          and window.game_mode_window.persistent_run.run_id == run.run_id)
    return run, window.game_mode_window


def test_legacy_null_launch_profile_resumes_and_live_callbacks_keep_defaults(
        files_window, qt_app):
    window = files_window
    run, mode = legacy_without_launch_profile(window, qt_app)
    assert mode.launch_options("white") == launch_defaults("white", window.config, window.base_dir)
    assert mode.persistent_run.launch_profile is None
    mode._game_changed("white")
    mode.refresh_run()
    window._run_changed(window.run_controller.active_run, window.run_controller.state)
    installation_requests = []
    mode.installation_requested.disconnect(window.open_installation)
    mode.installation_requested.connect(lambda: installation_requests.append(True))
    mode.launch_game("white")
    until(qt_app, lambda: bool(installation_requests) and not mode.play_runner.is_busy)
    assert "Installation à vérifier" in mode.page.status_label.text()
    assert window.runs.load(run.run_id).launch_profile is None
    assert not mode.service.state.running and mode.service.process is None
    assert not window.test_warnings


def test_legacy_null_launch_profile_accepts_ready_result_before_launching(
        files_window, qt_app, monkeypatch):
    window = files_window
    run, mode = legacy_without_launch_profile(window, qt_app)
    options = launch_defaults("white", window.config, window.base_dir)
    options["lua_connection"] = "manual"
    launches = []
    monkeypatch.setattr(mode, "_launch_process", lambda *args, **kwargs: launches.append((args, kwargs)))
    mode._play_prepared({"run_id": run.run_id, "game_id": "white", "profile": options,
                         "rom_fingerprint": None, "health": {"ready": True, "issues": []}})
    until(qt_app, lambda: bool(launches))
    assert launches == [(('white',), {"prepare_lua": True})]
    assert window.runs.load(run.run_id).launch_profile == options
    assert mode.persistent_run.run_id == run.run_id
    assert not window.test_warnings


def test_graceful_close_targets_only_the_process_owned_by_game_mode(service, monkeypatch):
    process = service.launch("white")
    calls = []
    monkeypatch.setattr(service.windows, "request_close", lambda pid, **kwargs: calls.append((pid, kwargs)), raising=False)
    service.request_close()
    assert calls == [(process.pid, {"executable": service._run_options["emulator_path"]})]
    assert process.poll() is None and service.state.running


def test_graceful_close_refuses_mismatched_process_identity(service, monkeypatch):
    process = service.launch("white")
    service.state = replace(service.state, pid=process.pid + 1)
    calls = []
    monkeypatch.setattr(service.windows, "request_close", lambda *args, **kwargs: calls.append(args), raising=False)
    with pytest.raises(ValueError, match="identifiée"):
        service.request_close()
    assert calls == [] and process.poll() is None


def test_window_close_posts_wm_close_to_verified_window_only(monkeypatch):
    manager = EmulatorWindowManager.__new__(EmulatorWindowManager)
    calls = []
    manager.user = SimpleNamespace(PostMessageW=lambda *args: calls.append(args) or True)
    window = EmulatorWindow(456, 123, "Synthetic", "owned.exe", (0, 0, 800, 600))
    monkeypatch.setattr(manager, "find", lambda pid, executable: window if (pid, executable) == (123, "owned.exe") else None)
    manager.request_close(123, executable="owned.exe")
    assert calls == [(456, 0x0010, 0, 0)]
    with pytest.raises(ValueError, match="absente ou ambiguë"):
        manager.request_close(999, executable="owned.exe")
    assert calls == [(456, 0x0010, 0, 0)]
