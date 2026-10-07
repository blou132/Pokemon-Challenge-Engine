"""Unified run/template UI on temporary storage; no real game is launched."""

from copy import deepcopy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from app.core.challenge_engine import ChallengeEngine
from app.ui.main_window import MainWindow
from app.ui.run_dialogs import NewRunDialog, RunChallengeDialog


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app, catalog, tmp_path):
    widget = MainWindow(catalog, tmp_path)
    yield widget
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


def choose(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def make_model(window):
    rules = {key: "required" if key in {"nuzlocke", "permanent_death"} else "possible"
             for key in window.catalog.rules}
    challenge = ChallengeEngine(window.catalog).generate("white", "custom", rules, 0, 42)
    return window.profiles.create("Modèle Blanc", challenge)


def test_library_is_primary_and_templates_have_no_competing_sidebar(window):
    assert window.pages.currentWidget() is window.runs_page
    assert window.nav_group.checkedButton() is window.runs_button
    buttons = window.nav_group.buttons()
    assert buttons[0] is window.runs_button
    assert {window.nav_group.id(button) for button in buttons} == {0, 2, 4, 5, 6}
    assert not any(word in button.text() for button in buttons
                   for word in ("Profils", "Nouveau challenge", "Modèles"))
    assert "modèle" in window.runs_page.empty_label.text()
    assert "personnalisé" in window.runs_page.empty_label.text()


def test_secondary_model_navigation_preserves_run_filters_and_editor_draft(window):
    window.runs_page.search_edit.setText("Mon aventure")
    choose(window.runs_page.game_combo, "white")
    window.runs_page.models_button.click()
    assert window.pages.currentWidget() is window.profile_page
    assert window.runs_button.isChecked()
    window.profile_page.create_button.click()
    assert window.pages.currentWidget() is window.challenge_page
    window.challenge_page.name_edit.setText("Mon brouillon")
    window.challenge_page.seed_edit.setText("12345")
    window.challenge_page.back_button.click()
    assert window.pages.currentWidget() is window.profile_page
    window.profile_page.create_button.click()
    assert window.challenge_page.name_edit.text() == "Mon brouillon"
    assert window.challenge_page.seed_edit.text() == "12345"
    window.challenge_page.back_button.click()
    window.profile_page.back_button.click()
    assert window.pages.currentWidget() is window.runs_page
    assert window.runs_page.search_edit.text() == "Mon aventure"
    assert window.runs_page.game_combo.currentData() == "white"
    assert window.runs.list_runs() == []
    assert window.profiles.list_profiles() == []


def test_home_uses_same_creation_dialog_with_each_game_preselected(window, monkeypatch):
    seen = []

    def cancel(dialog):
        seen.append(dialog.game_combo.currentData())
        assert dialog.source_combo.currentData() == "classic"
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(NewRunDialog, "exec", cancel)
    window.nav_buttons[0].click()
    buttons = window.home_page.findChildren(QPushButton)
    next(button for button in buttons if button.text().startswith("Nouvelle partie")).click()
    game_buttons = [button for button in buttons if button.text().startswith("Préparer une partie")]
    for button in game_buttons:
        button.click()
    games = [game.id for game in window.catalog.games.values() if game.status == "supported"]
    assert seen == ["black", *games]
    assert window.runs.list_runs() == []
    assert window.profiles.list_profiles() == []
    next(button for button in buttons if button.text() == "Mes parties").click()
    assert window.pages.currentWidget() is window.runs_page


@pytest.mark.parametrize("source", ["classic", "profile", "custom"])
def test_library_creates_all_three_kinds_and_shows_their_rules(window, monkeypatch, source):
    model = make_model(window)
    original = deepcopy(window.profiles.load(model.id))
    requested = []
    monkeypatch.setattr(window, "resume_run", requested.append)

    def configure(dialog):
        choose(dialog.editor.preset_combo, "classic_nuzlocke")
        dialog.editor.apply_preset()
        dialog.editor.seed_edit.setText("8541")
        dialog.accept()
        return dialog.result()

    def create(dialog):
        assert [dialog.source_combo.itemText(i) for i in range(3)] == [
            "Partie classique", "Depuis un modèle existant", "Challenge personnalisé"]
        choose(dialog.game_combo, "white")
        choose(dialog.source_combo, source)
        if source == "profile":
            choose(dialog.profile_combo, model.id)
        elif source == "custom":
            dialog.configure_button.click()
            assert dialog.custom_challenge is not None
        dialog.name_edit.setText("Mon aventure")
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted, dialog.error_label.text()
        return dialog.result()

    monkeypatch.setattr(RunChallengeDialog, "exec", configure)
    monkeypatch.setattr(NewRunDialog, "exec", create)
    window.runs_page.new_button.click()
    run, = window.runs.list_runs()
    assert run.name == "Mon aventure" and run.game_id == "white"
    assert requested == [run.run_id]
    assert run.profile_id == (model.id if source == "profile" else None)
    assert window.profiles.load(model.id) == original
    assert len(window.profiles.list_profiles()) == 1
    expected = {"classic": set(), "profile": {"nuzlocke", "permanent_death"},
                "custom": {"nuzlocke", "permanent_death", "species_clause"}}[source]
    assert set(run.rules_snapshot["active_rules"]) == expected
    assert run.badges is None and run.total_play_seconds == 0
    assert window.pages.currentWidget() is window.runs_page
    card, = window.runs_page.cards
    next(button for button in card.findChildren(QPushButton) if button.text() == "Détails et règles").click()
    details = window.runs_page._dialogs[run.run_id]
    rules = details.rules_view.toPlainText()
    assert "Règles figées" in rules
    assert all(window.catalog.rules[key].name in rules for key in expected)
    if source == "classic":
        assert "Classique · 0 règle active" in rules
    assert len(window.runs.list_runs()) == 1


def test_model_shortcut_preselects_source_without_importing_old_progress(window, monkeypatch):
    model = make_model(window)
    window.profiles.update(model.id, lambda profile: profile.progress["badges"].append("Ancien badge"))
    requested = []
    monkeypatch.setattr(window, "resume_run", requested.append)

    def create(dialog):
        assert dialog.game_combo.currentData() == "white"
        assert dialog.source_combo.currentData() == "profile"
        assert dialog.profile_combo.currentData() == model.id
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(NewRunDialog, "exec", create)
    window.runs_page.models_button.click()
    window.profile_page.start_run_button.click()
    run, = window.runs.list_runs()
    assert requested == [run.run_id]
    assert run.profile_id == model.id
    assert run.badges is None
    snapshot = deepcopy(run.rules_snapshot)

    def change_template(profile):
        profile.challenge = ChallengeEngine(window.catalog).generate("white", "normal", {}, 0, 99)

    window.profiles.update(model.id, change_template)
    assert window.profiles.load(model.id).progress["badges"] == ["Ancien badge"]
    assert window.runs.load(run.run_id).rules_snapshot == snapshot
    assert window.pages.currentWidget() is window.runs_page


def test_cancel_creation_preserves_existing_runs_and_models(window, monkeypatch):
    model = make_model(window)
    run = window.runs.create("Aventure existante", "white")
    original_model = deepcopy(window.profiles.load(model.id))
    original_run = deepcopy(window.runs.load(run.run_id).to_dict())
    monkeypatch.setattr(NewRunDialog, "exec", lambda dialog: QDialog.DialogCode.Rejected)
    window.runs_page.new_button.click()
    assert window.profiles.load(model.id) == original_model
    assert window.runs.load(run.run_id).to_dict() == original_run
    assert len(window.runs.list_runs()) == 1
