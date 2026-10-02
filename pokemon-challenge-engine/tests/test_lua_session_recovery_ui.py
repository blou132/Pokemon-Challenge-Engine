"""Récupération Qt de sessions synthétiques avec les services Lua de production."""

import json
import os
from pathlib import Path
from time import monotonic, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.bridge_controller import BridgeController
from app.services.bridge_service import BridgeService
from app.services.config_service import AppConfig
from app.ui.bridge_page import BridgePage
from app.ui.main_window import MainWindow
from app.bridge.state import BridgeState


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def until(app, predicate, timeout=5):
    limit = monotonic() + timeout
    while not predicate() and monotonic() < limit:
        app.processEvents()
        QTest.qWait(10)
    assert predicate()


@pytest.fixture
def connection(qt_app, catalog, tmp_path):
    bridge = BridgeService(tmp_path / "runtime/bridge")
    controller = BridgeController(tmp_path, bridge=bridge)
    page = BridgePage(catalog, controller, AppConfig())
    page.game_combo.setCurrentIndex(page.game_combo.findData("white"))
    page.prepare_button.click()
    until(qt_app, lambda: controller.state.status == "waiting")
    yield page, controller, bridge
    controller.shutdown()
    page.close()
    page.deleteLater()
    controller.deleteLater()
    qt_app.processEvents()


def disconnect(app, controller, bridge):
    payload = {"protocol_version": 1, "session_id": bridge.session_id, "sequence": 1, "event": "emulator_closing",
               "timestamp": int(time()), "emulator": "desmume", "script_version": "0.3.0", "game_id": "white",
               "game_code": "IRAF", "game_region": "FR", "rom_revision": 0, "capabilities": [],
               "memory_profile": None, "party_size": None, "party": None, "error": None}
    (bridge.session_dir / "snapshot-1.json").write_text(json.dumps(payload), encoding="utf-8")
    until(app, lambda: controller.state.status == "disconnected")


def test_reconnect_marks_old_session_stopped_and_prepares_new_script(qt_app, connection):
    page, controller, bridge = connection
    old = bridge.session_dir
    old_script = page.script_path.text()
    disconnect(qt_app, controller, bridge)
    assert not page.reconnect_button.isHidden()
    assert not page.game_combo.isEnabled()
    assert "arrêtez" in page.session_notice.text()
    page.reconnect_button.click()
    until(qt_app, lambda: controller.state.status == "waiting" and bridge.session_dir != old)
    assert (old / "stop").is_file()
    assert page.script_path.text() != old_script
    assert Path(page.script_path.text()).is_file()
    assert not (bridge.session_dir / "stop").exists()


def test_stop_and_change_requires_confirmation_then_unlocks(qt_app, connection, monkeypatch):
    page, controller, bridge = connection
    disconnect(qt_app, controller, bridge)
    old = bridge.session_dir
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    page.change_game_button.click()
    assert controller.state.status == "disconnected"
    assert not (old / "stop").exists()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    page.change_game_button.click()
    until(qt_app, lambda: controller.state.status == "stopped")
    assert page.game_combo.isEnabled()
    assert (old / "stop").is_file()
    page.game_combo.setCurrentIndex(page.game_combo.findData("black2"))
    page.prepare_button.click()
    until(qt_app, lambda: controller.state.status == "waiting")
    assert bridge.state.expected_game == "black2"


def test_script_copy_and_open_folder_are_explicit(qt_app, connection, monkeypatch):
    page, controller, bridge = connection
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    assert page.script_path.isHidden()
    page.copy_script_button.click()
    assert QApplication.clipboard().text() == str(bridge.session_dir / "connect.lua")
    assert opened == []
    page.folder_script_button.click()
    assert opened == [QUrl.fromLocalFile(str(bridge.session_dir))]
    assert "manuelle" in page.instructions.text()


def test_game_mode_explains_lua_lock_and_unlocks_after_confirmed_stop(qt_app, catalog, tmp_path, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    try:
        window.open_game_mode()
        mode = window.game_mode_window
        window.bridge_controller.start("white")
        until(qt_app, lambda: window.bridge_controller.state.status == "waiting")
        disconnect(qt_app, window.bridge_controller, window.bridge_controller.bridge)
        assert not mode.page.game_combo.isEnabled()
        assert "déconnectée" in mode.page.session_notice.text()
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        mode.page.change_game_button.click()
        until(qt_app, lambda: window.bridge_controller.state.status == "stopped")
        assert mode.page.game_combo.isEnabled()
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()
