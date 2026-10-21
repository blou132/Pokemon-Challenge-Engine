"""Synthetic Qt states and file messages only; no emulator or user save opened."""

from types import SimpleNamespace

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QLabel, QPushButton

from app.bridge.state import BridgeState
from app.core.run_manager import RunManager
from app.services.bridge_controller import BridgeController
from app.services.bridge_service import BridgeService
from app.services.config_service import AppConfig
from app.services.game_mode_service import RunState
from app.ui.bridge_page import BridgePage
from app.ui.game_mode_page import GameModePage
from app.ui.main_window import MainWindow
from test_bridge_service import FakeLuaClient
from test_run_integration import create, qt_app
from test_run_ui_edges import select_run


def melon_run(catalog, tmp_path):
    run = create(RunManager(tmp_path / "runs"), tmp_path, catalog)
    run.launch_profile["emulator_kind"] = "melonds"
    return run


@pytest.mark.parametrize("status", ["stopped", "waiting", "connected", "receiving", "disconnected", "error"])
def test_game_mode_labels_follow_selected_emulator_without_live_claims(qt_app, catalog, tmp_path, status):
    page = GameModePage(catalog)
    try:
        page.set_persistent_run(melon_run(catalog, tmp_path))
        page.set_run_state(RunState(game_id="white", running=True))
        page.set_bridge_state(BridgeState(status=status, game_id="white"))
        page.show()
        qt_app.processEvents()
        texts = [widget.text() for kind in (QLabel, QPushButton) for widget in page.findChildren(kind)
                 if widget.isVisible()]
        assert all("Lua" not in text and "LUA" not in text and "DeSmuME" not in text for text in texts)
        assert page.connection_badge.text().startswith("melonDS · ")
        assert page.launch_button.text() == "melonDS en cours"
        assert page.manual_lua_button.isHidden()
        assert "Sauvegarde Pokémon : gérée dans melonDS" in page.autosave_label.text()
        assert all("Non disponible" in slot.name_label.text() for slot in page.team_slots)
        assert ("connecté" == page.connection_badge.text().split(" · ")[-1]) == (status in {"connected", "receiving"})
    finally:
        page.close()
        page.deleteLater()
        qt_app.processEvents()


def test_switching_back_restores_desmume_labels(qt_app, catalog, tmp_path):
    page = GameModePage(catalog)
    try:
        run = melon_run(catalog, tmp_path)
        page.set_persistent_run(run)
        run.launch_profile.pop("emulator_kind")  # existing adventures use the legacy default
        page.set_persistent_run(run)
        page.set_run_state(RunState(game_id="white", running=True))
        page.set_bridge_state(BridgeState(status="waiting"))
        assert page.connection_badge.text() == "Lua · attente du script"
        assert page.launch_button.text() == "DeSmuME en cours"
        assert page.session_status.text() == "ATTENTE LUA"
        assert not page.manual_lua_button.isHidden()
        assert "Sauvegarde Pokémon : gérée dans DeSmuME" in page.autosave_label.text()
        page.set_persistent_run(None)
        assert page.connect_button.text() == "Connexion Lua"
    finally:
        page.close()
        page.deleteLater()
        qt_app.processEvents()


def test_native_diagnostics_route_to_game_mode_and_never_offer_a_lua_file(qt_app, catalog, tmp_path, monkeypatch):
    controller = BridgeController(tmp_path)
    page = BridgePage(catalog, controller, AppConfig())
    calls = []
    monkeypatch.setattr(controller, "start", lambda *args, **kwargs: calls.append((args, kwargs)))
    try:
        page.set_emulator_kind("melonds")
        page._prepared(str(tmp_path / "melonds-frame.json"))
        page.update_state(BridgeState(status="waiting"))
        requested = QSignalSpy(page.game_mode_requested)
        page.prepare_button.click()
        assert requested.count() == 1
        assert calls == []  # native process environment must keep its original session
        assert page.status_label.text() == "En attente des données de melonDS"
        assert page.script_path.text() == ""
        assert page.script_path.isHidden() and page.script_details_button.isHidden()
        assert page.copy_script_button.isHidden() and page.folder_script_button.isHidden()
        assert "inconnue" in page.instructions.text()
        assert "Lua" not in page.diagnostics_note.text()
        page.update_state(BridgeState(status="disconnected"))
        assert "Fermez melonDS" in page.session_notice.text()
        page.reconnect_button.click()
        assert requested.count() == 2 and calls == []
        page.set_emulator_kind("desmume")
        page.update_state(BridgeState(status="waiting"))
        assert page.title_label.text() == "Connexion DeSmuME"
        assert page.status_label.text() == "En attente du script Lua"
        assert "Tools > Lua Scripting" in page.instructions.text()
        assert not page.copy_script_button.isHidden()
    finally:
        controller.shutdown()
        page.close()
        page.deleteLater()
        qt_app.processEvents()


def test_selection_wires_navigation_and_live_connection_messages(qt_app, catalog, tmp_path, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    run = melon_run(catalog, tmp_path)
    window.runs.save(run)
    try:
        mode = select_run(window, run, qt_app, monkeypatch)
        assert window.nav_buttons[5].text() == "↔   Connexion melonDS"
        assert window.bridge_page.emulator_kind == "melonds"
        assert "melonDS" in window.game_mode_button.toolTip()
        mode._bridge_state_changed(BridgeState(status="connected", game_id="white"))
        assert mode.page.status_label.text() == "Connexion melonDS confirmée par les données du jeu."
        assert all("Non disponible" in slot.name_label.text() for slot in mode.page.team_slots)
        mode._bridge_state_changed(BridgeState(status="waiting"))
        assert mode.page.connection_badge.text() == "melonDS · attente des données"
        assert "Lua" not in mode.page.status_label.text()
        window._set_bridge_run(None)
        assert window.nav_buttons[5].text() == "↔   Connexion DeSmuME"
        assert window.bridge_page.emulator_kind == "desmume"
    finally:
        window.close()
        qt_app.processEvents()


def test_native_prepare_failure_never_falls_back_to_lua_or_launch(qt_app, catalog, tmp_path, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    run = melon_run(catalog, tmp_path)
    window.runs.save(run)
    try:
        mode = select_run(window, run, qt_app, monkeypatch)
        fallbacks = []
        launches = []
        monkeypatch.setattr(mode, "_autoload_prepared", lambda result: fallbacks.append(result))
        monkeypatch.setattr(mode, "_launch_process", lambda *args: launches.append(args))
        mode._lua_pipeline = {"request": 42, "options": {"emulator_kind": "melonds"}}
        mode._bridge_failed(42, "Erreur synthétique")
        assert mode._lua_pipeline is None
        assert fallbacks == launches == []
        assert mode.page._session_phase == "error"
        assert mode.page.status_label.text() == "Suivi melonDS à réparer : Erreur synthétique"
        assert mode.page.manual_lua_button.isHidden()
    finally:
        window.close()
        qt_app.processEvents()


@pytest.mark.parametrize("native", [False, True])
def test_timeout_names_the_actual_transport(tmp_path, native):
    clock = [10.0]
    bridge = BridgeService(tmp_path, clock=lambda: clock[0])
    bridge.start("white")
    if native:
        bridge.native_reader = SimpleNamespace(poll=lambda: None)
    clock[0] += 4
    state = bridge.poll()
    assert state.status == "disconnected"
    assert state.party is None
    assert state.last_error == ("Aucune donnée récente de melonDS : connexion perdue ou jeu arrêté." if native else
                                "Aucun message Lua récent : connexion perdue ou script arrêté.")


@pytest.mark.parametrize("event,expected", [
    ("bridge_error", "La passerelle melonDS a signalé une erreur."),
    ("emulator_closing", "La passerelle ou melonDS a été fermé."),
])
def test_native_error_messages_preserve_received_failure(tmp_path, event, expected):
    bridge = BridgeService(tmp_path)
    bridge.start("black")
    client = FakeLuaClient(bridge.session_dir, bridge.session_id)
    fields = {"event": event, "emulator": "melonds", "script_version": "0.5.0", "protocol_version": 2, "observation": None}
    client.send(**fields)
    assert bridge.poll().last_error == expected
    client.send(**fields, error="Erreur précise du producteur")
    assert bridge.poll().last_error == "Erreur précise du producteur"
