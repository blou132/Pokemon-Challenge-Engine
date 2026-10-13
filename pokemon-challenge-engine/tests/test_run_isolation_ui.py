"""Native Qt choices over synthetic files; no real emulator or save validation."""

from copy import deepcopy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.core.run_manager import RunManager
from app.ui.run_dialogs import NewRunDialog, RunDetailsDialog
from app.ui.runs_page import RunsPage


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def dialog(qt_app, catalog, tmp_path):
    source = tmp_path / "source.dsv"
    source.write_bytes(b"synthetic existing save")
    widget = NewRunDialog(catalog, [], {"white": {"game_id": "white", "rom_path": "white.nds",
                                               "save_path": str(source)}})
    choose(widget.game_combo, "white")
    yield widget
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


def choose(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def detection(path):
    return {"game_states": {"white": {"status": "ready", "message": "Prêt", "save_path": str(path),
                                      "profile": {"rom_path": "prepared.nds", "save_path": str(path)}}}}


def test_new_adventure_never_inherits_detected_save(dialog, tmp_path):
    report = detection(tmp_path / "source.dsv")
    original = deepcopy(report)
    dialog.set_detection_state(report, select_ready=True)
    values = dialog.selection()
    assert values["save_mode"] == "new"
    assert values["save_path"] is None
    assert values["launch_profile"]["save_path"] == ""
    assert dialog.save_edit.text() == ""
    assert dialog.save_edit.isHidden() and dialog.configured_save_button.isHidden()
    assert report == original


def test_import_mode_offers_detected_save_without_selecting_it(dialog, tmp_path):
    dialog.set_detection_state(detection(tmp_path / "source.dsv"))
    choose(dialog.save_mode_combo, "import")
    assert not dialog.save_edit.isHidden()
    assert not dialog.configured_save_button.isHidden()
    assert dialog.selection()["save_path"] is None
    dialog.configured_save_button.click()
    assert dialog.selection()["save_mode"] == "import"
    assert dialog.selection()["save_path"] == str(tmp_path / "source.dsv")


def test_discovery_refresh_preserves_explicit_import_choice(dialog, tmp_path):
    choose(dialog.save_mode_combo, "import")
    chosen = str(tmp_path / "chosen.dsv")
    dialog.save_edit.setText(chosen)
    dialog.set_detection_state(detection(tmp_path / "different.dsv"))
    assert dialog.selection()["save_path"] == chosen


def test_switching_game_clears_other_games_save_import(dialog, tmp_path):
    choose(dialog.save_mode_combo, "import")
    dialog.save_edit.setText(str(tmp_path / "source.dsv"))
    choose(dialog.game_combo, "black2")
    assert dialog.selection()["save_mode"] == "new"
    assert dialog.selection()["save_path"] is None
    assert dialog.save_edit.text() == ""


def test_switching_to_new_adventure_discards_import_without_confirmation(dialog, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: calls.append(args))
    choose(dialog.save_mode_combo, "import")
    dialog.save_edit.setText(str(tmp_path / "source.dsv"))
    choose(dialog.save_mode_combo, "new")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.selection()["save_path"] is None
    assert dialog.save_edit.text() == ""
    assert calls == []


@pytest.mark.parametrize("invalid", ["", "missing.dsv", "wrong.sav", "directory.dsv"])
def test_import_requires_an_existing_dsv_file(dialog, tmp_path, monkeypatch, invalid):
    (tmp_path / "wrong.sav").write_bytes(b"synthetic raw save")
    (tmp_path / "directory.dsv").mkdir()
    calls = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: calls.append(args))
    choose(dialog.save_mode_combo, "import")
    dialog.save_edit.setText(str(tmp_path / invalid) if invalid else "")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "fichier .dsv existant" in dialog.error_label.text()
    assert calls == []


def test_import_confirmation_identifies_source_and_preserves_original(dialog, tmp_path, monkeypatch):
    source = tmp_path / "source.dsv"
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    choose(dialog.save_mode_combo, "import")
    dialog.configured_save_button.click()
    calls = []

    def answer(*args):
        calls.append(args)
        return QMessageBox.StandardButton.No if len(calls) == 1 else QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", answer)
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert str(source.resolve()) in calls[0][2]
    assert "propre copie" in calls[0][2]
    assert calls[0][4] == QMessageBox.StandardButton.No
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.selection()["save_path"] == str(source)
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    assert list(tmp_path.iterdir()) == [source]  # The controller performs the copy after acceptance.


def test_details_emit_delete_and_isolate_without_mutating_run(qt_app, catalog, tmp_path):
    manager = RunManager(tmp_path / "runs")
    run = manager.create("Ancienne partie", "white")
    before = manager.load(run.run_id).to_dict()
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    actions = QSignalSpy(dialog.action_requested)
    dialog.delete_button.click()
    dialog.isolate_button.click()
    assert actions.count() == 2
    assert actions.at(0) == [run.run_id, "delete", {}]
    assert actions.at(1) == [run.run_id, "isolate", {}]
    assert manager.load(run.run_id).to_dict() == before
    assert dialog.status_combo.findData("archived") >= 0
    dialog.close()
    dialog.deleteLater()
    qt_app.processEvents()


def test_library_forwards_delete_and_removes_details_after_confirmed_deletion(qt_app, catalog, tmp_path):
    manager = RunManager(tmp_path / "runs")
    run = manager.create("Partie à supprimer", "white")
    kept = manager.create("Partie conservée", "white")
    page = RunsPage(catalog, manager)
    dialog = page.open_details(run.run_id)
    actions = QSignalSpy(page.action_requested)
    dialog.delete_button.click()
    assert actions.at(0) == [run.run_id, "delete", {}]
    assert not page.notify_deleted(run.run_id)
    assert len(page.visible_run_ids) == 2
    page.set_active_run(run.run_id)
    page.highlight_run(run.run_id)
    # Simulate only the completion notification; owned-file deletion is tested
    # by its service, independently from this UI test.
    (tmp_path / "runs" / run.run_id / "run.json").unlink()
    assert page.notify_deleted(run.run_id)
    assert page.visible_run_ids == [kept.run_id]
    assert page.active_run_id is None and page.highlighted_run_id is None
    assert run.run_id not in page._dialogs
    assert "supprimée" in page.creation_feedback.text()
    assert manager.load(kept.run_id).name == kept.name
    page.close()
    page.deleteLater()
    qt_app.processEvents()
