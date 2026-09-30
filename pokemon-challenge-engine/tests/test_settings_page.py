"""Vérifie les interactions des paramètres et leur disposition sur petit écran."""

import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QScrollArea

from app.services.config_service import AppConfig, ConfigService
from app.ui.settings_page import SettingsPage
from app.ui.theme import STYLESHEET


@pytest.fixture
def settings(tmp_path: Path, catalog):
    application = QApplication.instance() or QApplication([])
    # Le plugin offscreen Windows ne découvre pas toujours les polices système.
    for font in ("segoeui.ttf", "segoeuib.ttf"):
        path = Path("C:/Windows/Fonts") / font
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    previous_style = application.styleSheet()
    application.setStyleSheet(STYLESHEET)
    service = ConfigService(tmp_path / "config.json")
    page = SettingsPage(service, AppConfig(), catalog.games.values())
    yield application, page, service
    page.close()
    page.deleteLater()
    application.processEvents()
    application.setStyleSheet(previous_style)


@pytest.mark.parametrize("size", [(1110, 680), (1660, 980)])
def test_settings_scrolls_without_horizontal_clipping(settings, size: tuple[int, int]) -> None:
    application, page, _ = settings
    page.resize(*size)
    page.show()
    application.processEvents()
    scroll = page.findChild(QScrollArea)
    assert scroll.horizontalScrollBar().maximum() == 0
    scroll.ensureWidgetVisible(page.save_button)
    application.processEvents()
    assert page.save_button.isVisible()
    location = page.save_button.mapTo(scroll.viewport(), page.save_button.rect().center())
    assert scroll.viewport().rect().contains(location)
    assert all(edit.width() > 100 for edit in page.rom_edits.values())


def test_save_emits_config_and_persists(settings) -> None:
    _, page, service = settings
    updates = []
    page.config_changed.connect(updates.append)
    page.desmume_edit.setText("D:/Mes jeux/DeSmuME.exe")
    page.rom_edits["black2"].setText("D:/Mes jeux/Pokemon Noir 2.nds")
    with patch("app.ui.settings_page.QMessageBox.information") as dialog:
        page.save_button.click()
    assert len(updates) == 1
    assert service.load() == updates[0]
    assert updates[0].desmume_path == "D:/Mes jeux/DeSmuME.exe"
    dialog.assert_called_once()


def test_four_gen5_rom_fields_keep_independent_paths(settings):
    _, page, service = settings
    assert set(page.rom_edits) == {"black", "white", "black2", "white2"}
    expected = {game_id: f"D:/ROM/{game_id}.nds" for game_id in page.rom_edits}
    for game_id, path in expected.items():
        page.rom_edits[game_id].setText(path)
    assert page.rom_edits["white"].accessibleName() == "Pokémon Blanc — ROM .nds"
    assert page.rom_edits["white2"].accessibleName() == "Pokémon Blanc 2 — ROM .nds"
    with patch("app.ui.settings_page.QMessageBox.information"):
        page.save_button.click()
    assert service.load().rom_paths == expected


def test_save_error_is_shown_without_signal(settings) -> None:
    _, page, service = settings
    updates = []
    page.config_changed.connect(updates.append)
    with patch.object(service, "save", side_effect=ValueError("Écriture impossible")), \
         patch("app.ui.settings_page.QMessageBox.warning") as dialog:
        page.save_button.click()
    assert not updates
    assert dialog.call_args.args[2] == "Écriture impossible"


def test_test_button_reports_invalid_paths_without_launch_or_save(settings) -> None:
    _, page, service = settings
    with patch("app.ui.settings_page.QMessageBox.warning") as dialog, \
         patch("app.services.launcher_service.subprocess.Popen") as popen:
        page.test_button.click()
    popen.assert_not_called()
    assert not service.path.exists()
    assert "DeSmuME" in dialog.call_args.args[2]
    assert "Pokémon Noir 2" in dialog.call_args.args[2]


def test_browse_populates_rom_without_writing(settings) -> None:
    _, page, service = settings
    chosen = "D:/ROM/Noir.nds"
    with patch("app.ui.settings_page.QFileDialog.getOpenFileName", return_value=(chosen, "")):
        page._browse(page.rom_edits["black"], "rom")
    assert page.rom_edits["black"].text() == str(Path(chosen))
    assert not service.path.exists()


def test_settings_uses_supported_game_ids_and_names_from_catalog(settings, catalog) -> None:
    application, _, service = settings
    supported = replace(catalog.games["black"], id="custom_game", name="Jeu du catalogue")
    planned = replace(catalog.games["black2"], id="future_game", name="Jeu futur", status="planned")
    page = SettingsPage(service, AppConfig(), iter([supported, planned]))
    try:
        assert set(page.rom_edits) == {"custom_game"}
        assert page.rom_edits["custom_game"].accessibleName() == "Jeu du catalogue — ROM .nds"
        with patch("app.ui.settings_page.LauncherService.validate", return_value=[]) as validate, \
             patch("app.ui.settings_page.QMessageBox.information") as dialog:
            page.test_button.click()
        validate.assert_called_once_with("custom_game")
        assert "Jeu du catalogue" in dialog.call_args.args[2]
        assert "Jeu futur" not in dialog.call_args.args[2]
    finally:
        page.close()
        page.deleteLater()
        application.processEvents()
