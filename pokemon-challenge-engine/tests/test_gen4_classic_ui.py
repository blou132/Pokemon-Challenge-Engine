"""Qt capability gates over synthetic fixtures; no emulation is performed."""

import pytest

from app.core.run_manager import RunManager
from app.ui.run_dialogs import NewRunDialog
from app.ui.game_mode_page import GameModePage
from test_new_run_emulator_default import installed_component, component
from test_run_creation import qt_app, choose, close


@pytest.mark.parametrize("game_id", ["diamond", "pearl", "platinum", "heartgold", "soulsilver"])
def test_new_run_exposes_gen4_only_as_classic_melonds(qt_app, catalog, tmp_path, installed_component, game_id):
    dialog = NewRunDialog(catalog, [], {}, base_dir=tmp_path)
    try:
        choose(dialog.source_combo, "custom")
        choose(dialog.game_combo, game_id)
        assert dialog.game_combo.count() == 9
        assert dialog.source_combo.currentData() == "classic"
        assert dialog.emulator_combo.currentData() == "melonds"
        assert dialog.save_mode_combo.currentData() == "new"
        assert "non disponibles" in dialog.rules_label.text()
        assert not dialog.source_combo.model().item(dialog.source_combo.findData("custom")).isEnabled()
        assert not dialog.source_combo.model().item(dialog.source_combo.findData("profile")).isEnabled()
        assert not dialog.emulator_combo.model().item(dialog.emulator_combo.findData("desmume")).isEnabled()
        assert not dialog.save_mode_combo.model().item(dialog.save_mode_combo.findData("import")).isEnabled()
        selected = dialog.selection()
        assert selected["source"] == "classic" and selected["challenge"] is None
        assert selected["launch_profile"]["emulator_kind"] == "melonds"
        # Programmatic callers cannot bypass disabled entries.
        choose(dialog.source_combo, "custom")
        with pytest.raises(ValueError, match="Gen IV"):
            dialog.selection()
        choose(dialog.game_combo, "white")
        assert dialog.source_combo.model().item(dialog.source_combo.findData("custom")).isEnabled()
        assert dialog.save_mode_combo.model().item(dialog.save_mode_combo.findData("import")).isEnabled()
        assert dialog.emulator_combo.model().item(dialog.emulator_combo.findData("desmume")).isEnabled()
    finally:
        close(dialog, qt_app)


def test_missing_melonds_explains_why_gen4_cannot_be_created(qt_app, catalog, tmp_path, monkeypatch):
    from app.services import melonds_runtime
    monkeypatch.setattr(melonds_runtime, "find_installation", lambda base: None)
    dialog = NewRunDialog(catalog, [], {}, base_dir=tmp_path)
    try:
        choose(dialog.game_combo, "diamond")
        dialog.accept()
        assert "indisponible" in dialog.error_label.text()
    finally:
        close(dialog, qt_app)


def test_game_mode_gen4_does_not_promise_team_or_rule_tracking(qt_app, catalog, tmp_path):
    manager = RunManager(tmp_path / "runs")
    run = manager.create("Gen IV classique", "heartgold", launch_profile={"emulator_kind": "melonds"})
    page = GameModePage(catalog)
    try:
        page.set_persistent_run(run)
        assert "Gen IV non disponible" in page.team_note.text()
        assert "non disponibles" in page.rules_label.text()
        assert page.manual_actions["add_note"].isEnabled()
        assert all(not action.isEnabled() for key, action in page.manual_actions.items() if key != "add_note")
    finally:
        close(page, qt_app)
