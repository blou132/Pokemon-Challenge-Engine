"""Synthetic creation consent and save-isolation UI checks; no game is patched."""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.models.challenge import Challenge
from app.ui.run_dialogs import NewRunDialog, RunChallengeDialog


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def configuration(*, transform=True):
    settings = {"enforcement": "soft", "rule_parameters": {}}
    if transform:
        settings["rom_transformation"] = {"kind": "zx", "categories": ["wild", "starters"], "balanced": False}
    return Challenge("white", "custom", ["randomizer"], {"randomizer": "required"}, settings, None, 512).to_dict()


@pytest.fixture
def dialog(qt_app, catalog, tmp_path):
    widget = NewRunDialog(catalog, [], {}, base_dir=tmp_path)
    widget.game_combo.setCurrentIndex(widget.game_combo.findData("white"))
    yield widget
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


def test_declarative_randomizer_cannot_create_silent_unmodified_run(dialog):
    dialog.set_custom_challenge(configuration(transform=False))
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "catégories Randomizer" in dialog.error_label.text()


def test_randomizer_rejects_save_import_before_confirmation(dialog, tmp_path, monkeypatch):
    dialog.set_custom_challenge(configuration())
    dialog.save_mode_combo.setCurrentIndex(dialog.save_mode_combo.findData("import"))
    save = tmp_path / "personal.dsv"
    save.write_bytes(b"synthetic save")
    dialog.save_edit.setText(str(save))
    calls = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: calls.append(args))
    dialog.accept()
    assert "sans ancienne sauvegarde" in dialog.error_label.text()
    assert not calls and dialog.result() != QDialog.DialogCode.Accepted
    assert save.read_bytes() == b"synthetic save"


@pytest.mark.parametrize("confirmed", [False, True])
def test_creation_confirms_derived_rom_seed_and_preserves_snapshot(dialog, monkeypatch, confirmed):
    original = configuration()
    dialog.set_custom_challenge(original)
    messages = []
    def answer(*args):
        messages.append(args[2])
        return QMessageBox.StandardButton.Yes if confirmed else QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", answer)
    dialog.accept()
    assert (dialog.result() == QDialog.DialogCode.Accepted) == confirmed
    assert len(messages) == 1 and "Seed : 512" in messages[0]
    assert "source restera intacte" in messages[0]
    assert dialog.selection()["challenge"] == original
    assert dialog.selection()["save_mode"] == "new"
    assert dialog.selection()["save_path"] is None


def test_embedded_editor_receives_persistent_base_without_creating_files(qt_app, catalog, tmp_path):
    widget = RunChallengeDialog(catalog, "white", base_dir=tmp_path)
    try:
        assert not list(tmp_path.iterdir())
        assert widget.editor is not None
    finally:
        widget.close()
        widget.deleteLater()
        qt_app.processEvents()


def test_legacy_launch_routes_randomizer_to_dedicated_adventure(catalog, monkeypatch):
    from app.ui import main_window
    calls = []
    def forbidden(*args):
        raise AssertionError("A Randomizer challenge must not launch the source ROM directly")
    monkeypatch.setattr(main_window, "LauncherService", forbidden)
    view = SimpleNamespace(catalog=catalog, run_controller=SimpleNamespace(active_run=None),
                           game_mode_window=None, new_run=lambda **kwargs: calls.append(kwargs))
    challenge = Challenge.from_dict(configuration())
    main_window.MainWindow.launch_challenge(view, challenge)
    assert calls == [{"challenge": challenge}]
