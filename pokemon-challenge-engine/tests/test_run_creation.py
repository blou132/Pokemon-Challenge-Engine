"""V0.4.1 run creation reuses the existing challenge engine and refreshes persisted data."""

from copy import deepcopy
import os
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QScrollArea

from app.core.challenge_engine import ChallengeEngine
from app.core.run_manager import RunManager
from app.models.profile import Profile
from app.models.challenge import Challenge
from app.ui.challenge_page import ChallengePage
from app.ui.run_dialogs import NewRunDialog, RunChallengeDialog
from app.ui.runs_page import RunsPage
from app.ui.theme import STYLESHEET


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def manager(tmp_path):
    return RunManager(tmp_path / "runs")


def close(widget, qt_app):
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


def choose(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def edit_rules(dialog, rules, *, seed=482193):
    editor = dialog.editor
    choose(editor.preset_combo, "custom")
    editor.apply_preset()
    choose(editor.mode_combo, "custom")
    for key, control in editor.state_controls.items():
        choose(control, "required" if key in rules else "possible")
    editor.seed_edit.setText(str(seed))
    return editor


def profile(catalog):
    states = {key: "required" if key in ("nuzlocke", "permanent_death", "species_clause") else "possible"
              for key in catalog.rules}
    return Profile("classic", "Classic Nuzlocke", ChallengeEngine(catalog).generate("white", "custom", states, 0, 482193))


def test_three_explicit_sources_and_classic_has_no_challenge_controls(qt_app, catalog):
    dialog = NewRunDialog(catalog, [], {})
    assert [dialog.source_combo.itemData(i) for i in range(3)] == ["classic", "profile", "custom"]
    assert dialog.profile_combo.isHidden()
    assert dialog.configure_button.isHidden()
    assert dialog.selection()["challenge"] is None
    assert "0 règle active" in dialog.rules_label.text()
    assert dialog.findChild(ChallengePage) is None
    close(dialog, qt_app)


def test_existing_profile_has_explicit_name_and_rules(qt_app, catalog):
    source = profile(catalog)
    dialog = NewRunDialog(catalog, [source], {}, profile=source)
    assert dialog.source_combo.currentData() == "profile"
    assert not dialog.profile_combo.isHidden()
    assert "Profil : Classic Nuzlocke" in dialog.rules_label.text()
    assert all(name in dialog.rules_label.text() for name in ("Nuzlocke", "Mort permanente", "Species Clause"))
    assert dialog.selection()["profile_id"] == source.id
    assert dialog.selection()["challenge"] is None
    close(dialog, qt_app)


def test_profile_source_without_selection_cannot_be_created(qt_app, catalog):
    dialog = NewRunDialog(catalog, [], {})
    choose(dialog.source_combo, "profile")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "Sélectionnez un profil" in dialog.error_label.text()
    close(dialog, qt_app)


def test_custom_source_requires_configuration(qt_app, catalog):
    dialog = NewRunDialog(catalog, [], {})
    choose(dialog.source_combo, "custom")
    assert not dialog.configure_button.isHidden()
    assert dialog.profile_combo.isHidden()
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "Configurez les règles" in dialog.error_label.text()
    close(dialog, qt_app)


def test_custom_reuses_editor_engine_and_does_not_write_profile(qt_app, catalog, tmp_path):
    dialog = RunChallengeDialog(catalog, "white")
    editor = edit_rules(dialog, ("nuzlocke", "permanent_death"))
    choose(editor.state_controls["species_clause"], "forbidden")
    assert isinstance(editor, ChallengePage)
    assert isinstance(editor.engine, ChallengeEngine)
    assert editor.profiles is None
    assert not editor.game_combo.isEnabled()
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    data = dialog.configuration()
    assert set(data["active_rules"]) == {"nuzlocke", "permanent_death"}
    assert data["rule_states"]["species_clause"] == "forbidden"
    assert data["seed"] == 482193
    assert data["settings"]["preset_id"] == "custom"
    assert editor.save_button.isHidden() and editor.launch_button.isHidden()
    editor.save_profile()
    assert not list(tmp_path.iterdir())
    close(dialog, qt_app)


def test_configuration_only_never_emits_launch(qt_app, catalog):
    from PySide6.QtTest import QSignalSpy
    dialog = RunChallengeDialog(catalog, "white")
    edit_rules(dialog, ("nuzlocke", "permanent_death"))
    dialog.accept()
    spy = QSignalSpy(dialog.editor.launch_requested)
    dialog.editor.request_launch()
    assert spy.count() == 0
    close(dialog, qt_app)


def test_existing_preset_seed_and_rules_are_kept(qt_app, catalog):
    dialog = RunChallengeDialog(catalog, "white")
    choose(dialog.editor.preset_combo, "classic_nuzlocke")
    dialog.editor.apply_preset()
    dialog.editor.seed_edit.setText("123456")
    dialog.editor.generate()
    expected = dialog.configuration()
    dialog.accept()
    assert dialog.configuration() == expected  # No regeneration of an existing preview.
    assert expected["settings"]["preset_id"] == "classic_nuzlocke"
    assert expected["seed"] == 123456
    assert set(expected["active_rules"]) == {"nuzlocke", "permanent_death", "species_clause"}
    close(dialog, qt_app)


def test_rule_parameter_changes_regenerate_stale_preview(qt_app, catalog):
    dialog = RunChallengeDialog(catalog, "white")
    editor = edit_rules(dialog, ("level_cap", "catch_limit"))
    editor.generate()
    editor.parameter_controls["level_cap"]["max_level"].setValue(38)
    editor.parameter_controls["catch_limit"]["per_zone"].setValue(2)
    assert editor.challenge is None
    dialog.accept()
    data = dialog.configuration()
    assert data["settings"]["rule_parameters"] == {"level_cap": {"max_level": 38}, "catch_limit": {"per_zone": 2}}
    close(dialog, qt_app)


def test_monotype_reuses_seed_driven_configuration(qt_app, catalog):
    dialog = RunChallengeDialog(catalog, "white")
    editor = edit_rules(dialog, ("monotype",), seed=87215)
    assert not editor.monotype_row.isHidden()
    dialog.accept()
    data = dialog.configuration()
    assert data["monotype"]["type_id"] in data["monotype"]["allowed_types"]
    assert data["active_rules"] == ["monotype"]
    close(dialog, qt_app)


def test_random_count_uses_existing_feasible_rule_selection(qt_app, catalog):
    dialog = RunChallengeDialog(catalog, "white")
    editor = edit_rules(dialog, ("nuzlocke", "permanent_death"))
    choose(editor.mode_combo, "random")
    choose(editor.state_controls["shiny_only"], "forbidden")
    editor.count_spin.setValue(5)
    dialog.accept()
    data = dialog.configuration()
    assert len(data["active_rules"]) == 5
    assert "shiny_only" not in data["active_rules"]
    assert {"nuzlocke", "permanent_death"} <= set(data["active_rules"])
    close(dialog, qt_app)


def test_invalid_dependency_is_rejected_by_existing_engine(qt_app, catalog):
    dialog = RunChallengeDialog(catalog, "white")
    editor = edit_rules(dialog, ("nuzlocke",))
    choose(editor.state_controls["permanent_death"], "forbidden")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert editor.challenge is None
    assert not dialog.error_label.isHidden()
    close(dialog, qt_app)


def test_custom_run_snapshot_has_no_profile_and_remains_independent(qt_app, catalog, manager):
    editor = RunChallengeDialog(catalog, "white")
    edit_rules(editor, ("nuzlocke", "permanent_death"))
    editor.accept()
    dialog = NewRunDialog(catalog, [profile(catalog)], {})
    choose(dialog.game_combo, "white")
    dialog.set_custom_challenge(editor.configuration())
    values = dialog.selection()
    assert values["source"] == "custom" and values["profile_id"] is None
    run = manager.create(values["name"], values["game_id"], challenge=Challenge.from_dict(values["challenge"]), profile_id=values["profile_id"])
    values["challenge"]["active_rules"].clear()
    dialog.custom_challenge["active_rules"].clear()
    saved = manager.load(run.run_id)
    assert saved.profile_id is None
    assert set(saved.rules_snapshot["active_rules"]) == {"nuzlocke", "permanent_death"}
    close(dialog, qt_app)
    close(editor, qt_app)


def test_switching_to_classic_discards_custom_source_in_selection(qt_app, catalog):
    dialog = NewRunDialog(catalog, [], {})
    custom = ChallengeEngine(catalog).generate(dialog.game_combo.currentData(), "normal", {}, 0, 42).to_dict()
    dialog.set_custom_challenge(custom)
    choose(dialog.source_combo, "classic")
    assert dialog.selection()["challenge"] is None
    assert dialog.selection()["profile_id"] is None
    assert dialog.configure_button.isHidden()
    close(dialog, qt_app)


def test_changing_game_invalidates_custom_snapshot(qt_app, catalog):
    dialog = NewRunDialog(catalog, [], {})
    choose(dialog.game_combo, "white")
    dialog.set_custom_challenge(ChallengeEngine(catalog).generate("white", "normal", {}, 0, 42).to_dict())
    choose(dialog.game_combo, "black")
    assert dialog.selection()["challenge"] is None
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    close(dialog, qt_app)


def test_wrong_game_custom_configuration_is_rejected(qt_app, catalog):
    dialog = NewRunDialog(catalog, [], {})
    choose(dialog.game_combo, "white")
    with pytest.raises(ValueError, match="jeu"):
        dialog.set_custom_challenge(ChallengeEngine(catalog).generate("black", "normal", {}, 0, 42).to_dict())
    assert dialog.custom_challenge is None
    close(dialog, qt_app)


def test_cancel_custom_editor_preserves_previous_configuration(qt_app, catalog, monkeypatch):
    dialog = NewRunDialog(catalog, [], {})
    game_id = dialog.game_combo.currentData()
    custom = ChallengeEngine(catalog).generate(game_id, "normal", {}, 0, 42).to_dict()
    dialog.set_custom_challenge(custom)
    original = deepcopy(dialog.custom_challenge)
    def cancel(editor):
        editor.editor.seed_edit.setText("999")
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(RunChallengeDialog, "exec", cancel)
    dialog.configure_button.click()
    assert dialog.custom_challenge == original
    close(dialog, qt_app)


def test_save_reference_is_shared_only_after_explicit_choice(qt_app, catalog):
    dialog = NewRunDialog(catalog, [], {"white": {"save_path": "user.dsv", "rom_path": "white.nds"}})
    choose(dialog.game_combo, "white")
    assert dialog.selection()["save_path"] is None
    assert dialog.selection()["launch_profile"]["save_path"] == ""
    assert not dialog.configured_save_button.isHidden()
    dialog.configured_save_button.click()
    assert dialog.selection()["save_path"] == "user.dsv"
    assert dialog.selection()["launch_profile"]["save_path"] == "user.dsv"
    close(dialog, qt_app)


def test_created_run_immediately_appears_with_confirmation(qt_app, catalog, manager):
    page = RunsPage(catalog, manager)
    assert not page.cards
    run = manager.create("Pokémon Blanc — Classique", "white")
    assert page.notify_created(run.run_id)
    assert page.visible_run_ids == [run.run_id]
    assert page.summary.text() == "1 partie affichée · 1 enregistrée"
    assert page.creation_feedback.text() == "Partie créée"
    assert page.cards[0].highlighted
    assert page.cards[0].findChild(QFrame).property("selectedRun") is True
    close(page, qt_app)


@pytest.mark.parametrize("filter_name,value", [("search_edit", "Noir"), ("game_combo", "black"),
                                                ("challenge_combo", "nuzlocke"), ("status_combo", "finished")])
def test_new_run_cannot_be_hidden_by_stale_filter(qt_app, catalog, manager, filter_name, value):
    page = RunsPage(catalog, manager)
    control = getattr(page, filter_name)
    control.setText(value) if filter_name == "search_edit" else choose(control, value)
    run = manager.create("Blanc Classique", "white")
    assert page.notify_created(run.run_id)
    assert page.visible_run_ids == [run.run_id]
    assert "Filtres réinitialisés" in page.creation_feedback.text()
    close(page, qt_app)


def test_matching_filters_preserved_and_new_highlight_does_not_activate(qt_app, catalog, manager):
    first = manager.create("Blanc A", "white")
    manager.set_active_id(first.run_id)
    page = RunsPage(catalog, manager)
    page.set_active_run(first.run_id)
    choose(page.game_combo, "white")
    page.search_edit.setText("Blanc")
    second = manager.create("Blanc B", "white")
    page.notify_created(second.run_id)
    assert page.game_combo.currentData() == "white"
    assert page.search_edit.text() == "Blanc"
    assert page.active_run_id == first.run_id and manager.active_id == first.run_id
    assert page.highlighted_run_id == second.run_id
    assert len(page.cards) == 2
    assert [card.run_id for card in page.cards if card.highlighted] == [second.run_id]
    close(page, qt_app)


def test_failed_readback_never_claims_run_created(qt_app, catalog, manager):
    page = RunsPage(catalog, manager)
    assert page.notify_created(str(uuid4())) is False
    assert page.creation_feedback.isHidden()
    assert not page.cards
    assert not page.warning.isHidden()
    close(page, qt_app)


@pytest.mark.parametrize("size", [(1366, 768), (1920, 1080)])
def test_creation_and_custom_editor_fit_target_viewports(qt_app, catalog, size):
    dialog = NewRunDialog(catalog, [profile(catalog)], {}, profile=profile(catalog))
    dialog.setStyleSheet(STYLESHEET)
    dialog.show()
    qt_app.processEvents()
    assert dialog.width() < size[0] and dialog.height() < size[1]
    assert not dialog.grab().isNull()
    editor = RunChallengeDialog(catalog, "white")
    editor.setStyleSheet(STYLESHEET)
    editor.resize(min(1000, size[0] - 50), size[1] - 68)
    editor.show()
    qt_app.processEvents()
    scroll = editor.editor.findChild(QScrollArea)
    assert scroll.verticalScrollBar().maximum() > 0
    assert editor.width() < size[0] and editor.height() < size[1]
    assert not editor.grab().isNull()
    close(editor, qt_app)
    close(dialog, qt_app)
