"""Synthetic UI/process tests; no emulator, real ROM or user save is opened."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QLabel

from app.services.config_service import AppConfig
from app.services.emulator_settings_service import EmulatorSettingsService
from app.services.emulator_window_manager import EmulatorWindow, EmulatorWindowManager
from app.services.game_mode_config import defaults
from app.services.game_mode_service import GameModeService
from app.services.save_manager_service import SaveManagerService
from app.ui.game_mode_settings import LaunchProfilePage
from app.ui.main_window import MainWindow
from app.ui.save_manager_page import SaveManagerPage
from test_run_integration import create, qt_app
from test_run_ui_edges import select_run


@pytest.mark.parametrize("speed", ["x1", "x2", "x4", "MAX"])
def test_native_speed_and_ini_export_are_refused_without_side_effects(tmp_path, monkeypatch, speed):
    service = GameModeService(tmp_path, AppConfig())
    service._run_options = {"emulator_kind": "melonds"}
    original = service.state
    apply = Mock()
    monkeypatch.setattr(EmulatorSettingsService, "apply_launch_profile", apply)
    with pytest.raises(ValueError, match="Interface settings"):
        service.request_speed(speed)
    with pytest.raises(ValueError, match="melonDS"):
        service._apply_launch_settings(service._run_options)
    assert service.state == original
    apply.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_native_buttons_shortcuts_and_handlers_do_not_use_desmume(qt_app, catalog, tmp_path, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    run = create(window.runs, tmp_path, catalog)
    run.launch_profile.update(emulator_kind="melonds", emulator_path="synthetic-melonDS.exe")
    window.runs.save(run)
    inspected = []
    original = EmulatorSettingsService.inspect

    def inspect(adapter):
        inspected.append(adapter.executable)
        assert adapter.executable != "synthetic-melonDS.exe"
        return original(adapter)

    monkeypatch.setattr(EmulatorSettingsService, "inspect", inspect)
    try:
        mode = select_run(window, run, qt_app, monkeypatch)
        shortcuts = mode.service.config["shortcuts"] | {"speed_x2": "Ctrl+2", "fullscreen": "Ctrl+F11"}
        mode.set_shortcuts(shortcuts)
        assert not mode._shortcuts["speed_x2"].isEnabled()
        assert mode._shortcuts["fullscreen"].isEnabled()
        requested = QSignalSpy(mode.page.speed_requested)
        for button in mode.page.speed_buttons.values():
            assert not button.isEnabled() and not button.isChecked()
            button.click()
        assert requested.count() == 0
        assert all(not button.isEnabled() for button in mode.page.controls_buttons)
        speed = Mock()
        monkeypatch.setattr(mode.service, "request_speed", speed)
        mode.request_speed("MAX")
        speed.assert_not_called()
        assert "Interface settings" in mode.page.status_label.text()
        for tab in ("controls", "controls_reset", "graphics"):
            mode.open_settings(tab)
            assert mode.settings_dialog is None
            assert "Config >" in mode.page.status_label.text()
        mode.open_settings("launch")
        assert not mode.settings_tabs.isTabEnabled(mode._tab_ids["controls"])
        assert not mode.settings_tabs.isTabEnabled(mode._tab_ids["graphics"])
        assert mode.settings_tabs.isTabEnabled(mode._tab_ids["saves"])
        assert "Input and hotkeys" in mode.page.controls_source.text()
        assert "Interface settings" in mode.page.speed_label.text()
        run.launch_profile["emulator_kind"] = "desmume"
        run.launch_profile["emulator_path"] = "synthetic-desmume.exe"
        mode.set_persistent_run(run)
        assert mode._shortcuts["speed_x2"].isEnabled()
        assert all(button.isEnabled() for button in mode.page.speed_buttons.values())
    finally:
        window.close()
        qt_app.processEvents()


def test_launch_preferences_disable_native_unsupported_settings_and_restore_legacy(qt_app, catalog, tmp_path):
    profiles = defaults(AppConfig(), tmp_path)["launch_profiles"]
    profiles["white"]["emulator_kind"] = "melonds"
    page = LaunchProfilePage(catalog, profiles)
    try:
        page.set_context("white")
        assert page.native_note.isHidden() is False
        assert page.path_labels["ini_path"].text() == "Configuration melonDS (.toml)"
        for widget in (page.controls_profile, page.graphics_preset, page.speed_combo, page.apply_settings, page.auto_lua):
            assert not widget.isEnabled()
        assert page.auto_lua.isHidden() and page.apply_settings.isHidden()
        assert not page.challenge_combo.isEnabled()
        changed = QSignalSpy(page.settings_changed)
        page._save()
        assert changed.count() == 1 and changed.at(0)[1]["apply_settings"] is False
        page.set_context("black")
        assert page.native_note.isHidden()
        assert page.path_labels["ini_path"].text() == "Configuration DeSmuME (facultatif)"
        assert page.speed_combo.isEnabled() and page.apply_settings.isEnabled()
        assert not page.auto_lua.isHidden()
    finally:
        page.close()
        page.deleteLater()
        qt_app.processEvents()


def test_native_save_states_are_read_only_inventory_with_correct_menu(qt_app, catalog, tmp_path):
    slots = tmp_path / "states"
    slots.mkdir()
    state = slots / "adventure.ml1"
    state.write_bytes(b"synthetic state")
    page = SaveManagerPage(SaveManagerService(tmp_path / "backups"), catalog.games.values())
    try:
        page.set_context("white", {"emulator_kind": "melonds", "save_state_directory": str(slots), "save_state_stem": "adventure"})
        assert page.states_table.item(1, 1).text() == "Existe"
        assert ".ml0" in page.states_stem_note.text()
        assert "File > Save state / Load state" in page.states_policy_note.text()
        assert "DeSmuME" not in page.states_policy_note.text()
        assert not any("DeSmuME" in widget.text() for widget in page.findChildren(QLabel))
        page.refresh_button.click()
        assert state.read_bytes() == b"synthetic state"
        assert list(slots.iterdir()) == [state]
        page.set_context("black", {})
        assert ".ds0" in page.states_stem_note.text()
        assert "DeSmuME" in page.states_policy_note.text()
    finally:
        page.close()
        page.deleteLater()
        qt_app.processEvents()


def test_native_window_placement_only_moves_owned_unambiguous_window(tmp_path, monkeypatch):
    manager = EmulatorWindowManager()
    executable = str((tmp_path / "melonDS.exe").resolve())
    window = EmulatorWindow(1234, 42, "melonDS 1.1", executable, (0, 0, 400, 600))
    manager.user = SimpleNamespace(SetWindowPos=Mock(return_value=True), PostMessageW=Mock())
    monkeypatch.setattr(manager, "windows", lambda pid=None: [window] if pid == 42 else [])
    rect = (100, 100, 500, 700)
    assert manager.arrange(42, rect, executable=executable) == window
    manager.user.SetWindowPos.assert_called_once_with(1234, None, *rect, 0x0004 | 0x0010)
    manager.user.PostMessageW.assert_not_called()
    for pid, path in ((9, executable), (42, str(tmp_path / "other.exe"))):
        with pytest.raises(ValueError):
            manager.arrange(pid, rect, executable=path)
    monkeypatch.setattr(manager, "windows", lambda pid=None: [window, window])
    with pytest.raises(ValueError):
        manager.arrange(42, rect, executable=executable)
    assert manager.user.SetWindowPos.call_count == 1
