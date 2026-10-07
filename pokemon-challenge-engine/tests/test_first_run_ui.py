"""Parcours Qt synthétiques : aucun téléchargement, processus ou fichier utilisateur."""

from copy import deepcopy
import os
from threading import Event
from time import monotonic
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QThread, QTimer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.ui.setup_dialog import InstallationDialog
from app.ui.setup_tasks import SetupTaskRunner
from app.ui.main_window import MainWindow
from app.services.game_mode_service import RunState


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def until(app, predicate, timeout=5):
    limit = monotonic() + timeout
    while not predicate() and monotonic() < limit:
        app.processEvents()
        QTest.qWait(5)
    assert predicate(), "L'opération Qt n'a pas terminé dans le délai attendu."


def snapshot():
    return {"installations": [{"root": "C:/fixture/RetroBat", "roms_directory": "C:/fixture/RetroBat/roms"}],
            "emulators": [{"path": "C:/fixture/RetroBat/emulators/desmume/DeSmuME.exe", "architecture": "x64",
                           "version": "test", "known_build": False, "lua_status": "missing", "dlls": [],
                           "ini_path": "C:/fixture/RetroBat/emulators/desmume/desmume.ini"}],
            "games": [{"id": "white-archive", "label": "Pokémon Blanc", "game_id": "white", "game_code": "IRAF",
                       "region": "FR", "revision": 0, "source_path": "C:/fixture/RetroBat/roms/nds/Blanc.zip",
                       "archive_member": "Blanc.nds", "source_kind": "zip", "requires_choice": False,
                       "supported": True, "saves": [{"path": "C:/fixture/Blanc.dsv", "size": 524288,
                                "modified_at": "2026-10-01", "confidence": "high", "reason": "synthetic"}],
                       "proposed_save": "C:/fixture/Blanc.dsv"}], "warnings": [], "details": [], "setup_complete": False}


class SyntheticSetup:
    def __init__(self):
        self.report = snapshot()
        self.calls = []
        self.first_run_done = False
        self.error = None
        self.ready = False

    def scan(self, **kwargs):
        self.calls.append(("scan", kwargs, QThread.currentThread()))
        if self.error:
            raise self.error
        return deepcopy(self.report)

    def prepare(self, selection, **kwargs):
        self.calls.append(("prepare", selection, kwargs))
        self.ready = True
        return {"game_id": "white", "profile": {}, "health": {"ready": True, "issues": [], "warnings": [],
                "lua_status": {"status": "verified"}}, "actions": ["Préparation synthétique"]}

    def repair(self, selection, replace_confirmed=False):
        self.calls.append(("repair", selection, replace_confirmed))
        return self.prepare(selection)

    def complete_first_run(self):
        self.first_run_done = True

    def storage_summary(self):
        return {"items": [{"kind": "extracted_roms", "label": "ROM extraites", "bytes": 1048576, "count": 1}]}

    def cleanup(self, kind, **kwargs):
        self.calls.append(("cleanup", kind, kwargs))
        return {"removed": 1}


@pytest.fixture
def dialog(qt_app):
    service = SyntheticSetup()
    widget = InstallationDialog(service, first_run=True, active_session=lambda: "active-test-session")
    yield widget, service
    until(qt_app, lambda: not widget.is_busy)
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


def scan(dialog, app):
    widget, service = dialog
    widget.start()
    until(app, lambda: not widget.is_busy)
    return widget, service


def test_first_run_detect_prepare_then_play(qt_app, dialog):
    widget, service = scan(dialog, qt_app)
    assert widget.game_combo.currentData() == "white-archive"
    assert widget.save_combo.currentData() == "C:/fixture/Blanc.dsv"
    assert widget.summary["lua"].text() == "Réparation nécessaire"
    assert widget.summary["game"].text() == "À préparer depuis l'archive"
    assert widget.details.isHidden()
    assert not widget.play_button.isEnabled()
    widget.prepare_button.click()
    until(qt_app, lambda: not widget.is_busy)
    assert widget.play_button.isEnabled()
    assert "test en jeu requis" in widget.summary["lua"].text()
    spy = QSignalSpy(widget.play_requested)
    widget.play_button.click()
    until(qt_app, lambda: spy.count() == 1)
    assert spy.at(0) == ["white"]
    assert service.first_run_done
    assert service.calls[0][2] is not qt_app.thread()


def test_multiple_archives_and_saves_require_choice(qt_app, dialog):
    widget, service = dialog
    second = deepcopy(service.report["games"][0])
    second.update(id="white-other", archive_member="Blanc2.nds")
    service.report["games"].append(second)
    service.report["games"][0]["saves"].append({"path": "C:/fixture/Blanc-old.dsv", "size": 524288, "modified_at": "hier"})
    scan(dialog, qt_app)
    assert widget.game_combo.currentData() is None
    widget.game_combo.setCurrentIndex(1)
    assert widget.save_combo.currentData() is None
    widget.prepare_selected()
    assert not any(call[0] == "prepare" for call in service.calls)
    assert "sauvegardes" in widget.status_label.text()
    widget.save_combo.setCurrentIndex(1)
    assert widget.selection()["save_path"] == ""


def test_archive_multi_member_requires_explicit_selection_even_one_supported_candidate(qt_app, dialog):
    widget, service = dialog
    service.report["games"][0]["requires_choice"] = True
    scan(dialog, qt_app)
    assert widget.game_combo.currentData() is None


def test_multiple_installations_never_choose_first_silently(qt_app, dialog):
    widget, service = dialog
    service.report["installations"].append({"root": "D:/fixture/RetroBat"})
    scan(dialog, qt_app)
    assert widget.installation_combo.currentData() is None
    with pytest.raises(ValueError, match="installation RetroBat"):
        widget.selection()


def test_permission_failure_stays_visible_and_retry_works(qt_app, dialog):
    widget, service = dialog
    service.error = PermissionError("Accès refusé au dossier de test")
    scan(dialog, qt_app)
    assert "Accès refusé" in widget.status_label.text()
    assert not widget.play_button.isEnabled()
    service.error = None
    widget.scan()
    until(qt_app, lambda: not widget.is_busy)
    assert widget.prepare_button.isEnabled()


def test_repair_needs_explicit_confirmation(qt_app, dialog, monkeypatch):
    widget, service = scan(dialog, qt_app)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    widget.repair_selected()
    assert not any(call[0] == "repair" for call in service.calls)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    widget.repair_selected()
    until(qt_app, lambda: not widget.is_busy)
    assert next(call for call in service.calls if call[0] == "repair")[2] is False


def test_existing_different_dlls_need_separate_confirmation(qt_app, dialog, monkeypatch):
    widget, service = dialog
    service.report["emulators"][0]["dlls"] = [{"name": "lua51.dll", "path": "C:/fixture/lua51.dll", "status": "different"}]
    scan(dialog, qt_app)
    choices = iter([QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
    monkeypatch.setattr(QMessageBox, "question", lambda *args: next(choices))
    widget.repair_selected()
    assert not any(call[0] == "repair" for call in service.calls)
    texts = []
    def yes(*args):
        texts.append(args[2])
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", yes)
    widget.repair_selected()
    until(qt_app, lambda: not widget.is_busy)
    assert len(texts) == 2 and "C:/fixture/lua51.dll" in texts[1]
    assert next(call for call in service.calls if call[0] == "repair")[2] is True


def test_storage_cleanup_confirmed_and_active_session_forwarded(qt_app, dialog, monkeypatch):
    widget, service = scan(dialog, qt_app)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    widget.cleanup("sessions")
    until(qt_app, lambda: not widget.is_busy)
    call = next(call for call in service.calls if call[0] == "cleanup")
    assert call == ("cleanup", "sessions", {"confirmed": True, "active_session": "active-test-session"})


def test_worker_keeps_event_loop_responsive_and_close_is_deferred(qt_app, dialog):
    widget, service = dialog
    entered, release = Event(), Event()
    original = service.scan
    def held(**kwargs):
        entered.set()
        release.wait(3)
        return original(**kwargs)
    service.scan = held
    widget.show()
    widget.start()
    try:
        until(qt_app, entered.is_set)
        tick = []
        QTimer.singleShot(0, lambda: tick.append(True))
        until(qt_app, lambda: bool(tick))
        widget.close()
        assert widget.isVisible() and widget.is_busy
    finally:
        release.set()
        until(qt_app, lambda: not widget.is_busy)


def test_settings_entry_preserves_six_pages_and_first_run_starts_only_on_request(qt_app, catalog, tmp_path):
    window = MainWindow(catalog, tmp_path)
    service = SyntheticSetup()
    window._setup_service = service
    try:
        assert window.installation_dialog is None
        assert window.pages.count() == 6
        window.start_first_run()
        assert window.installation_dialog.first_run
        until(qt_app, lambda: not window.installation_dialog.is_busy)
        window.installation_dialog.continue_button.click()
        until(qt_app, lambda: not window.installation_dialog.is_busy)
        assert service.first_run_done
        window.settings_page.installation_button.click()
        assert window.installation_dialog.isVisible()
        assert window.pages.count() == 6
    finally:
        if window.installation_dialog:
            until(qt_app, lambda: not window.installation_dialog.is_busy)
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_prepared_game_health_check_runs_in_worker_before_launch_and_lua(qt_app, catalog, tmp_path, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    try:
        window.open_game_mode()
        mode = window.game_mode_window
        calls = []
        def prepare_play(game_id):
            calls.append(("health", game_id, QThread.currentThread() is qt_app.thread()))
            return {"game_id": game_id, "health": {"ready": True, "issues": [], "warnings": []}}
        mode._setup_service = SimpleNamespace(is_configured=lambda game: True, prepare_play=prepare_play)
        monkeypatch.setattr(mode.service, "reload_preferences", lambda: calls.append(("reload",)))
        def launch(game_id, profile_id):
            calls.append(("launch", game_id))
            mode.service.state = RunState(game_id=game_id, running=True)
            return SimpleNamespace(pid=123)
        monkeypatch.setattr(mode.service, "launch", launch)
        from PySide6.QtCore import QTimer
        controller = window.bridge_controller
        def prepare_bridge(game, path):
            calls.append(("lua", game))
            controller.bridge.start(game)
            controller.request_id += 1
            request = controller.request_id
            script = controller.bridge.session_dir / "connect.lua"
            script.write_text("-- synthetic fixture", encoding="utf-8")
            QTimer.singleShot(0, lambda: controller.prepared_for_request.emit(request, str(script)))
            return request
        monkeypatch.setattr(controller, "start", prepare_bridge)
        monkeypatch.setattr(mode.autoload, "restore", lambda *args: None)
        monkeypatch.setattr(mode.autoload, "prepare", lambda *args, **kwargs:
                            SimpleNamespace(enabled=False, message="Synthetic manual fallback"))
        mode.page.game_combo.setCurrentIndex(mode.page.game_combo.findData("white"))
        mode.launch_game("white")
        until(qt_app, lambda: not mode.launch_busy and mode.service.state.running)
        assert calls == [("health", "white", False), ("reload",), ("lua", "white"), ("launch", "white")]
    finally:
        if window.game_mode_window:
            until(qt_app, lambda: not window.game_mode_window.play_runner.is_busy)
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_failed_health_check_never_launches_and_offers_repair(qt_app, catalog, tmp_path, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    try:
        window.open_game_mode()
        mode = window.game_mode_window
        mode._setup_service = SimpleNamespace(is_configured=lambda game: True,
            prepare_play=lambda game: {"health": {"ready": False, "issues": ["Support Lua à réparer"]}})
        mode.installation_requested.disconnect()
        requested = QSignalSpy(mode.installation_requested)
        monkeypatch.setattr(mode.service, "launch", lambda *args: pytest.fail("Le diagnostic doit bloquer le lancement."))
        mode.launch_game("white")
        until(qt_app, lambda: not mode.play_runner.is_busy)
        assert requested.count() == 1
        assert "Support Lua" in mode.page.status_label.text()
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_explicit_emulator_choice_replaces_the_previous_selection(qt_app, dialog):
    widget, service = scan(dialog, qt_app)
    original = widget.emulator_combo.currentData()
    second = deepcopy(service.report["emulators"][0])
    second["path"] = "C:/fixture/other/DeSmuME.exe"
    service.report["emulators"].append(second)
    widget._overrides["emulator_path"] = second["path"]
    widget.scan()
    until(qt_app, lambda: not widget.is_busy)
    assert widget.selection()["emulator_path"] == second["path"] != original


def test_unrecognized_explicit_emulator_never_falls_back_to_previous_choice(qt_app, dialog):
    widget, service = scan(dialog, qt_app)
    widget._overrides["emulator_path"] = "C:/fixture/unsupported.exe"
    widget.scan()
    until(qt_app, lambda: not widget.is_busy)
    assert widget.emulator_combo.currentData() is None
    assert not widget.prepare_button.isEnabled()
    assert not widget.play_button.isEnabled()


def test_incomplete_repair_clears_previous_lua_success(qt_app, dialog):
    widget, service = scan(dialog, qt_app)
    widget.prepare_selected()
    until(qt_app, lambda: not widget.is_busy)
    assert widget.play_button.isEnabled()
    widget._operation = "repair"
    widget._completed({"game_id": "white", "health": {"ready": False,
        "issues": ["DLL manquante après modification externe"], "lua_status": {"status": "missing"}}})
    assert not widget.play_button.isEnabled()
    assert widget.summary["lua"].text() == "Réparation nécessaire"
    assert "DLL manquante" in widget.status_label.text()


def test_failed_repair_never_leaves_stale_ready_summary(qt_app, dialog):
    widget, service = scan(dialog, qt_app)
    widget.prepare_selected()
    until(qt_app, lambda: not widget.is_busy)
    widget._operation = "repair"
    widget._failed("Accès refusé")
    assert not widget.play_button.isEnabled()
    assert widget.summary["game"].text() == "Préparation non confirmée"
    assert widget.summary["lua"].text() == "À revérifier"


def test_continue_never_replays_launch_after_failed_first_run_save(qt_app, dialog):
    widget, service = scan(dialog, qt_app)
    widget.prepare_selected()
    until(qt_app, lambda: not widget.is_busy)
    original_complete = service.complete_first_run
    def failed_complete():
        raise PermissionError("Enregistrement local refusé")
    service.complete_first_run = failed_complete
    launches = QSignalSpy(widget.play_requested)
    widget.play_button.click()
    until(qt_app, lambda: not widget.is_busy)
    assert launches.count() == 0
    service.complete_first_run = original_complete
    widget.continue_button.click()
    until(qt_app, lambda: not widget.is_busy)
    assert service.first_run_done
    assert launches.count() == 0
