"""Synthetic Qt launch orchestration; no actual emulator or user files."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QThread

from app.bridge.state import BridgeState
from app.core.profile_manager import ProfileManager
from app.services.bridge_controller import BridgeController
from app.services.config_service import AppConfig
from app.services.game_mode_config import launch_defaults, validate_config
from app.services.game_mode_service import RunState
from app.ui.game_mode_settings import LaunchProfilePage
from app.ui.game_mode_window import GameModeWindow
from test_bridge_ui import publish
from test_run_integration import create, qt_app, until
from app.core.run_manager import RunManager


@pytest.fixture
def mode(qt_app, catalog, tmp_path, monkeypatch):
    controller = BridgeController(tmp_path)
    window = GameModeWindow(catalog, tmp_path, controller, ProfileManager(tmp_path / "profiles"), AppConfig())
    rom = tmp_path / "Actual prepared ROM.nds"
    header = bytearray(512)
    header[12:16] = b"IRAF"
    rom.write_bytes(header)
    window.service.save_launch_profile("white", {"rom_path": str(rom), "lua_connection": "manual"})
    window.page.game_combo.setCurrentIndex(window.page.game_combo.findData("white"))
    calls = []
    window.test_calls = calls
    def autoload(exe, actual_rom, script, session_id, **options):
        assert QThread.currentThread() is not qt_app.thread()
        assert Path(script).is_file() and (Path(script).parent / "config.lua").is_file()
        assert not (Path(script).parent / "stop").exists()
        assert actual_rom == str(rom)
        calls.append(("autoload", session_id, options["configure_ini"]))
        return SimpleNamespace(enabled=options["configure_ini"], message="Manual fixture")
    monkeypatch.setattr(window.autoload, "prepare", autoload)
    monkeypatch.setattr(window.autoload, "restore", lambda exe: calls.append(("restore",)))
    def launch(game, profile_id=None, **options):
        assert calls[-1][0] == "autoload"
        assert controller.bridge.session_id == calls[-1][1]
        calls.append(("launch", game))
        window.service.state = RunState(game_id=game, running=True, pid=4242)
        return SimpleNamespace(pid=4242)
    monkeypatch.setattr(window.service, "launch", launch)
    window.timer.stop()
    yield window
    until(qt_app, lambda: not window.autoload_runner.is_busy and not window.play_runner.is_busy)
    window._lua_pipeline = None
    window.lua_timeout.stop()
    controller.shutdown()
    window.close()
    window.deleteLater()
    qt_app.processEvents()


def start(mode, qt_app):
    mode._launch_process("white", prepare_lua=True)
    assert mode.page.connection_badge.text() == "Lua · préparation"
    assert not mode.service.state.running
    until(qt_app, lambda: not mode.launch_busy)
    assert mode.service.state.running


def test_bridge_and_autoload_are_ready_before_launch_then_real_protocol_message_connects(mode, qt_app):
    start(mode, qt_app)
    assert [item[0] for item in mode.test_calls] == ["restore", "autoload", "launch"]
    assert mode.page.connection_badge.text() == "Lua · attente du script"
    assert mode.page.session_status.text() == "ATTENTE LUA"
    publish(mode.controller.bridge, 1, game_id="white", game_code="IRAF", memory_profile="white_fr_rev0")
    until(qt_app, lambda: mode.controller.state.connected)
    assert mode.page.connection_badge.text() == "Lua · connecté"
    assert mode.page.session_status.text() == "EN JEU"
    assert not mode.lua_timeout.isActive()


def test_timeout_keeps_emulator_running_and_offers_all_recovery_actions(mode, qt_app):
    start(mode, qt_app)
    mode._lua_timed_out()
    assert mode.service.state.running
    assert mode.page.session_status.text() == "ERREUR LUA"
    assert "DeSmuME a démarré mais Lua ne s'est pas connecté." in mode.page.status_label.text()
    assert not mode.page.reconnect_button.isHidden()
    assert not mode.page.manual_lua_button.isHidden()
    assert not mode.page.lua_diagnostic_button.isHidden()
    assert not mode.page.launch_button.isEnabled()
    assert "déjà lancé" in mode.page.launch_button.toolTip()


def test_reconnect_creates_new_session_and_loader_without_writing_ini_or_relaunching(mode, qt_app):
    start(mode, qt_app)
    old = mode.controller.bridge.session_dir
    mode.reconnect_lua()
    until(qt_app, lambda: not mode.launch_busy)
    new = mode.controller.bridge.session_dir
    assert old != new and (old / "stop").exists()
    assert not (new / "stop").exists()
    assert mode.test_calls[-1] == ("autoload", new.name, False)
    assert len([item for item in mode.test_calls if item[0] == "launch"]) == 1
    assert len([item for item in mode.test_calls if item[0] == "restore"]) == 1
    assert "processus ouvert" in mode.page.status_label.text()
    assert mode.page.connection_badge.text() != "Lua · connecté"


def test_stale_heartbeat_does_not_connect_the_new_session(mode, qt_app):
    start(mode, qt_app)
    current = mode._connection_session
    mode._bridge_state_changed(BridgeState(status="connected", game_id="white", session_id="old"))
    assert mode.page.connection_badge.text() != "Lua · connecté"
    mode._bridge_state_changed(BridgeState(status="connected", game_id="black", session_id=current))
    assert mode.page.connection_badge.text() != "Lua · connecté"


def test_unknown_prepared_signal_cannot_start_autoload(mode, qt_app):
    start(mode, qt_app)
    calls = list(mode.test_calls)
    mode._bridge_prepared(10000, str(mode.controller.bridge.session_dir / "connect.lua"))
    assert mode.test_calls == calls


@pytest.mark.parametrize("stop_kind", ["request", "marker"])
def test_stop_during_autoload_cancels_launch(mode, qt_app, monkeypatch, stop_kind):
    entered, release = Event(), Event()
    original = mode.autoload.prepare
    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        release.wait(5)
        return result
    monkeypatch.setattr(mode.autoload, "prepare", delayed)
    try:
        mode._launch_process("white", prepare_lua=True)
        until(qt_app, entered.is_set)
        if stop_kind == "request":
            mode.controller.stop()
        else:
            (mode.controller.bridge.session_dir / "stop").touch()
    finally:
        release.set()
    until(qt_app, lambda: not mode.launch_busy)
    assert not mode.service.state.running
    assert not any(item[0] == "launch" for item in mode.test_calls)


def test_old_autoload_result_cannot_cancel_new_preparation(mode):
    newer = {"generation": 2}
    mode._lua_pipeline = newer
    mode._autoload_prepared({"pipeline": {"generation": 1}})
    assert mode._lua_pipeline is newer
    mode._lua_pipeline = None


def test_old_stopped_state_cannot_replace_new_heartbeat(mode, qt_app):
    start(mode, qt_app)
    request = mode.controller.request_id
    state = BridgeState(status="connected", game_id="white", session_id=mode._connection_session)
    mode.controller._receive_scoped_state(request, state)
    assert mode.page.connection_badge.text() == "Lua · connecté"
    mode.controller._receive_scoped_state(request - 1, BridgeState())
    assert mode.page.connection_badge.text() == "Lua · connecté"


def test_autoload_failure_launches_in_manual_mode_without_connected_claim(mode, qt_app, monkeypatch):
    original = mode.autoload.prepare
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise ValueError("Synthetic INI unavailable")
    monkeypatch.setattr(mode.autoload, "prepare", fail)
    start(mode, qt_app)
    assert "INI unavailable" in mode.page.status_label.text()
    assert "mode manuel" in mode.page.status_label.text()
    assert mode.page.connection_badge.text() != "Lua · connecté"


def test_run_guard_is_rechecked_after_background_autoload(mode, qt_app, tmp_path, catalog, monkeypatch):
    run = create(RunManager(tmp_path / "runs"), tmp_path, catalog)
    run.launch_profile = deepcopy(mode.launch_options("white"))
    mode.bind_requested_run(run)
    allowed = [True]
    mode.set_run_guard(lambda run_id: allowed[0])
    entered, release = Event(), Event()
    original = mode.autoload.prepare
    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        release.wait(5)
        return result
    monkeypatch.setattr(mode.autoload, "prepare", delayed)
    try:
        mode._launch_process("white", prepare_lua=True)
        until(qt_app, entered.is_set)
        allowed[0] = False
    finally:
        release.set()
    until(qt_app, lambda: not mode.launch_busy)
    assert not mode.service.state.running
    assert not any(item[0] == "launch" for item in mode.test_calls)


def test_binding_and_reopening_run_reads_its_own_controls(mode, qt_app, tmp_path, catalog, monkeypatch):
    seen = []
    monkeypatch.setattr(mode, "_refresh_controls", lambda exe: seen.append(exe))
    manager = RunManager(tmp_path / "runs")
    one, two = create(manager, tmp_path, catalog), create(manager, tmp_path, catalog)
    one.launch_profile["emulator_path"] = "A.exe"
    two.launch_profile["emulator_path"] = "B.exe"
    mode.bind_requested_run(one)
    mode.bind_requested_run(two)
    assert seen == ["A.exe", "B.exe"]
    assert mode.set_persistent_run(one) is False
    assert mode.persistent_run.run_id == two.run_id
    mode.show()
    qt_app.processEvents()
    assert seen[-1] == "B.exe"
    updated = deepcopy(two)
    updated.launch_profile["emulator_path"] = "B2.exe"
    mode.set_persistent_run(updated)
    assert seen[-1] == "B2.exe"


def test_missing_controls_offer_configuration_and_existing_mapping_replaces_it(mode):
    mode.page.set_controls({}, "Non disponible")
    assert mode.page.controls_buttons[0].text() == "Configurer les contrôles"
    assert mode.page.controls_buttons[1].isHidden()
    mode.page.set_controls({"A": "X"}, "desmume.ini")
    assert mode.page.control_labels["A"].text() == "X"
    assert mode.page.controls_buttons[0].text() == "Modifier"
    assert not mode.page.controls_buttons[1].isHidden()


@pytest.mark.parametrize("accepted", [True, False])
def test_first_consent_is_saved_once_and_reused_for_other_runs(mode, qt_app, monkeypatch, accepted):
    monkeypatch.setattr("app.services.emulator_capabilities.detect_capabilities", lambda exe: SimpleNamespace(known_build=True))
    consent = [None]
    prompts = []
    monkeypatch.setattr(mode, "_ask_lua_consent", lambda: prompts.append("prompt") or accepted)
    monkeypatch.setattr(mode.autoload, "consent_status", lambda exe: consent[0])
    monkeypatch.setattr(mode.autoload, "record_consent", lambda exe, value: consent.__setitem__(0, value))
    for _ in range(2):
        options = {"emulator_path": "fixture.exe", "lua_connection": "ask"}
        mode._resolve_lua_choice(options)
        assert options["lua_connection"] == ("auto" if accepted else "manual")
    assert prompts == ["prompt"]
    # A manually configured legacy launch (without AutoSetup) uses the same
    # stored consent and must not bypass the automatic connection preference.
    mode.service.save_launch_profile("white", {"lua_connection": "ask"})
    mode._launch_process("white", prepare_lua=True)
    until(qt_app, lambda: not mode.launch_busy)
    assert mode.service.state.running
    assert mode.service.config["launch_profiles"]["white"]["lua_connection"] == ("auto" if accepted else "manual")
    assert next(item[2] for item in mode.test_calls if item[0] == "autoload") is accepted
    assert prompts == ["prompt"]


def test_manual_choice_never_prompts_or_changes_ini(mode, monkeypatch):
    monkeypatch.setattr(mode, "_ask_lua_consent", lambda: pytest.fail("manual must not prompt"))
    options = {"emulator_path": "fixture.exe", "lua_connection": "manual"}
    mode._resolve_lua_choice(options)
    assert options["lua_connection"] == "manual"
    assert mode.test_calls == []


@pytest.mark.parametrize("choice", ["ask", "auto", "manual"])
def test_lua_setting_is_backwards_compatible_and_visible(qt_app, catalog, tmp_path, choice):
    old = launch_defaults("white", AppConfig(), tmp_path)
    old.pop("lua_connection")
    assert validate_config({"launch_profiles": {"white": old}}, AppConfig(), tmp_path)["launch_profiles"]["white"]["lua_connection"] == "ask"
    values = validate_config({"launch_profiles": {"white": old | {"lua_connection": choice}}}, AppConfig(), tmp_path)
    page = LaunchProfilePage(catalog, values["launch_profiles"])
    page.set_context("white")
    assert page.auto_lua.isChecked() == (choice != "manual")
    page.close()
