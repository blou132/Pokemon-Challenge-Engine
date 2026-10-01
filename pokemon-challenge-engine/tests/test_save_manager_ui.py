"""Interactions du gestionnaire de sauvegardes sur fichiers synthétiques."""

import os
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea

from app.services.save_manager_service import SaveManagerService
from app.ui.save_manager_page import SaveManagerPage


@pytest.fixture
def page(tmp_path, catalog):
    application = QApplication.instance() or QApplication([])
    widget = SaveManagerPage(SaveManagerService(tmp_path / "backups"), catalog.games.values())
    yield application, widget
    widget.close()
    widget.deleteLater()
    application.processEvents()


def select_save(page, tmp_path):
    _, widget = page
    source = tmp_path / "chosen.dsv"
    source.write_bytes(b"synthetic")
    widget.set_context("white", {"save_path": str(source)})
    return source


def test_no_automatic_backups_enabled_by_default(page):
    _, widget = page
    settings = widget.current_settings()
    assert not settings["backup_on_launch"] and not settings["backup_on_close"] and not settings["backup_periodic"]
    assert settings["save_state_policy"] == "unmanaged"
    assert not widget.service.root.exists()
    assert widget.states_table.item(0, 1).text() == "Non disponible"


def test_context_switch_does_not_reassign_previous_games_save(page, tmp_path):
    source = select_save(page, tmp_path)
    _, widget = page
    widget.game_combo.setCurrentIndex(widget.game_combo.findData("black"))
    assert widget.save_edit.text() == ""
    widget.game_combo.setCurrentIndex(widget.game_combo.findData("white"))
    assert widget.save_edit.text() == str(source)


def test_manual_backup_emits_verified_record_and_keeps_original(page, tmp_path):
    source = select_save(page, tmp_path)
    _, widget = page
    events = []
    widget.backup_created.connect(events.append)
    widget.backup_button.click()
    assert len(events) == 1
    assert source.read_bytes() == b"synthetic"
    assert widget.backup_table.rowCount() == 1
    assert "SHA-256" in widget.status_label.text()


def test_backup_failure_is_readable(page):
    _, widget = page
    assert widget.backup_now() is None
    assert "chemin" in widget.status_label.text()
    assert not widget.service.root.exists()


def test_settings_only_emit_after_explicit_save(page, tmp_path):
    select_save(page, tmp_path)
    _, widget = page
    events = []
    widget.settings_changed.connect(lambda game, settings: events.append((game, settings)))
    widget.on_launch.setChecked(True)
    widget.retention_combo.setCurrentIndex(widget.retention_combo.findData(0))
    widget.retention_custom.setValue(17)
    assert not events
    widget.save_button.click()
    assert events[0][0] == "white"
    assert events[0][1]["backup_on_launch"] and events[0][1]["backup_retention"] == 17
    assert not widget.service.root.exists()


def test_automatic_backups_require_a_selected_save(page):
    _, widget = page
    events = []
    widget.settings_changed.connect(lambda *args: events.append(args))
    widget.periodic.setChecked(True)
    widget.save_button.click()
    assert not events
    assert "d'abord" in widget.status_label.text()


def test_slots_report_detected_and_empty_but_not_invented_preview(page, tmp_path):
    _, widget = page
    (tmp_path / "example.ds5").write_bytes(b"state")
    widget.set_context("white", {"save_state_directory": str(tmp_path), "save_state_stem": "example",
                                 "save_state_policy": "forbidden"})
    assert widget.states_table.item(5, 1).text() == "Existe"
    assert widget.states_table.item(4, 1).text() == "Vide"
    assert widget.policy_combo.currentText() == "Interdit"


def test_restore_cancellation_is_read_only(page, tmp_path):
    source = select_save(page, tmp_path)
    _, widget = page
    widget.backup_now()
    source.write_bytes(b"current")
    widget.backup_table.selectRow(0)
    with patch("app.ui.save_manager_page.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
        widget.restore_button.click()
    assert source.read_bytes() == b"current"
    assert widget.backup_table.rowCount() == 1


def test_restore_confirmation_keeps_current_as_backup(page, tmp_path):
    source = select_save(page, tmp_path)
    _, widget = page
    widget.backup_now()
    source.write_bytes(b"current")
    widget.backup_table.selectRow(0)
    with patch("app.ui.save_manager_page.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
        widget.restore_button.click()
    assert source.read_bytes() == b"synthetic"
    assert widget.backup_table.rowCount() == 2


def test_restore_disabled_while_owned_emulator_runs(page):
    _, widget = page
    widget.set_emulator_running(True)
    assert not widget.restore_button.isEnabled()


def test_restore_refuses_external_emulator_before_confirmation(page, tmp_path):
    source = select_save(page, tmp_path)
    _, widget = page
    widget.backup_now()
    widget.backup_table.selectRow(0)
    widget.set_running_probe(lambda: True)
    with patch("app.ui.save_manager_page.QMessageBox.question") as dialog:
        widget.restore_button.click()
    dialog.assert_not_called()
    assert "toutes les instances" in widget.status_label.text()
    assert source.read_bytes() == b"synthetic"


def test_restore_rechecks_external_process_after_confirmation(page, tmp_path):
    source = select_save(page, tmp_path)
    _, widget = page
    widget.backup_now()
    source.write_bytes(b"current")
    widget.backup_table.selectRow(0)
    widget.set_running_probe(Mock(side_effect=[False, True]))
    with patch("app.ui.save_manager_page.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
        widget.restore_button.click()
    assert source.read_bytes() == b"current"
    assert "Fermez" in widget.status_label.text()


@pytest.mark.parametrize("probe", [lambda: None, Mock(side_effect=OSError("unavailable"))])
def test_uncertain_emulator_state_refuses_restore(page, tmp_path, probe):
    select_save(page, tmp_path)
    _, widget = page
    widget.backup_now()
    widget.backup_table.selectRow(0)
    widget.set_running_probe(probe)
    with patch("app.ui.save_manager_page.QMessageBox.question") as dialog:
        widget.restore_button.click()
    dialog.assert_not_called()
    assert "refusée" in widget.status_label.text()


@pytest.mark.parametrize("size", [(1040, 650), (1600, 950)])
def test_page_scrolls_at_small_and_large_sizes(page, size):
    application, widget = page
    widget.resize(*size)
    widget.show()
    application.processEvents()
    scroll = widget.findChild(QScrollArea)
    assert scroll.horizontalScrollBar().maximum() == 0
    scroll.ensureWidgetVisible(widget.save_button)
    application.processEvents()
    position = widget.save_button.mapTo(scroll.viewport(), widget.save_button.rect().center())
    assert scroll.viewport().rect().contains(position)
    assert widget.save_edit.width() > 100
