"""Qt controls/display pages against synthetic configurations."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from app.services.emulator_capabilities import EmulatorCapabilities
from app.services.emulator_settings_service import DEFAULT_CONTROLS, SettingsSnapshot
from app.ui.controls_page import ControlsPage
from app.ui.graphics_page import GraphicsPage


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


class FakeSettings:
    def __init__(self, known=True):
        self.known = known
        self.applied = []

    def inspect(self):
        return SettingsSnapshot(EmulatorCapabilities(known_build=self.known), Path("desmume.ini"),
            DEFAULT_CONTROLS if self.known else {}, {"FastForward": 9, "Pause": 19},
            {"internal_resolution": 1, "vsync": 0, "output_filter": 0, "aspect_ratio": 1,
             "integer_scaling": 0, "layout": 0, "rotation": 0} if self.known else {})

    def apply(self, **changes):
        self.applied.append(changes)
        from app.services.emulator_settings_service import SettingsChange
        return SettingsChange(Path("desmume.ini.pce-backup"))


def test_reset_only_changes_draft_and_export_preserves_modified_hotkeys(qt_app, tmp_path):
    fake = FakeSettings()
    page = ControlsPage(fake, tmp_path / "controls.local.json")
    assert not page.hotkey_boxes["IncreaseSpeed"].isEnabled()
    page.reset_controls()
    assert not fake.applied
    page._export()
    assert fake.applied[0]["controls"] == DEFAULT_CONTROLS
    assert fake.applied[0]["hotkeys"] is None
    page.close()


def test_unknown_emulator_hides_unverified_graphics_and_disables_export(qt_app, tmp_path):
    fake = FakeSettings(False)
    controls = ControlsPage(fake, tmp_path / "controls.local.json")
    graphics = GraphicsPage(fake)
    assert not controls.export_button.isEnabled()
    assert graphics.panel.isHidden()
    assert "pas une configuration détectée" in controls.status.text()
    controls.close()
    graphics.close()


def test_preset_is_draft_until_explicit_apply(qt_app):
    fake = FakeSettings()
    page = GraphicsPage(fake)
    page.set_preset("hd")
    assert fake.applied == []
    page._apply()
    assert fake.applied[0]["graphics"]["internal_resolution"] == 2
    page.close()


def test_app_shortcuts_refuse_conflicts_and_emit_config(qt_app, tmp_path):
    page = ControlsPage(FakeSettings(), tmp_path / "controls.local.json")
    spy = QSignalSpy(page.app_shortcuts_changed)
    page.set_app_shortcuts({"fullscreen": "Ctrl+F", "game_mode": "Ctrl+F"})
    page._save_shortcuts()
    assert spy.count() == 0
    page.set_app_shortcuts({"fullscreen": "X"})
    page._save_shortcuts()
    assert spy.count() == 0
    page.set_app_shortcuts({"fullscreen": "Up"})
    page._save_shortcuts()
    assert spy.count() == 0
    page.set_app_shortcuts({"fullscreen": "Ctrl+F", "game_mode": "Ctrl+G"})
    page._save_shortcuts()
    assert spy.count() == 1
    page.close()
