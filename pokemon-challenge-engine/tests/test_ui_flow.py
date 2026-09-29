"""Parcours de l'interface Qt sur stockage temporaire, sans émulateur réel."""

from copy import deepcopy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.core.monotype import select_type
from app.ui.main_window import MainWindow
from app.ui.monotype_wheel import MonotypeDialog


@pytest.fixture(scope="module")
def qt_app():
    """Une seule application Qt, compatible avec les autres tests du dépôt."""
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def window(qt_app, catalog, tmp_path):
    widget = MainWindow(catalog, tmp_path)
    yield widget
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


def choose(combo, value):
    """Reproduire la sélection utilisateur, y compris un choix déjà affiché."""
    index = combo.findData(value)
    assert index >= 0, f"Option absente : {value}"
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def generate_classic(window):
    page = window.challenge_page
    choose(page.preset_combo, "classic_nuzlocke")
    page.seed_edit.setText("482193")
    page.generate_button.click()
    assert page.challenge is not None, page.feedback.text()
    return page


def save_classic(window, name="Noir · Run test"):
    page = generate_classic(window)
    page.name_edit.setText(name)
    page.save_button.click()
    profiles = window.profiles.list_profiles()
    assert profiles
    return profiles[-1]


def test_custom_preset_and_normal_generate_from_ui(window):
    page = generate_classic(window)
    assert page.challenge.mode == "custom"
    assert set(page.challenge.active_rules) == {"nuzlocke", "permanent_death", "species_clause"}
    assert page.challenge.seed == 482193
    assert "Seed : 482193" in page.preview.toPlainText()
    assert page.save_button.isEnabled()
    assert page.launch_button.isEnabled()

    choose(page.mode_combo, "normal")
    assert page.challenge is None
    assert not page.rules_table.isEnabled()
    assert not page.wheel_button.isEnabled()
    page.generate_button.click()
    assert page.challenge.mode == "normal"
    assert page.challenge.active_rules == []
    assert page.challenge.monotype is None
    assert "0 règle(s)" in page.preview.toPlainText()


def test_reselecting_current_preset_restores_its_rules(window):
    page = generate_classic(window)
    choose(page.state_controls["no_items"], "required")
    choose(page.state_controls["species_clause"], "forbidden")
    page.generate_button.click()
    assert page.challenge is not None
    assert "no_items" in page.challenge.active_rules
    assert page.preset_combo.currentData() == "classic_nuzlocke"

    choose(page.preset_combo, "classic_nuzlocke")

    assert page.challenge is None
    assert not page.save_button.isEnabled()
    assert page.state_controls["no_items"].currentData() == "possible"
    assert page.state_controls["species_clause"].currentData() == "required"
    page.generate_button.click()
    assert set(page.challenge.active_rules) == {"nuzlocke", "permanent_death", "species_clause"}


def test_rule_visual_states_follow_choices_and_preset_changes(window):
    page = window.challenge_page
    required = page.state_controls["nuzlocke"]
    other = page.state_controls["no_items"]
    assert required.property("state") == "required"
    assert other.property("state") == "possible"
    choose(other, "forbidden")
    assert other.property("state") == "forbidden"
    choose(page.preset_combo, "hardcore_nuzlocke")
    assert other.property("state") == "required"


def test_reopened_challenge_displays_custom_and_preserves_its_options(window):
    page = window.challenge_page
    choose(page.preset_combo, "monotype")
    choose(page.state_controls["no_items"], "required")
    choose(page.state_controls["shiny_only"], "forbidden")
    choose(page.enforcement_combo, "strict")
    page.parameter_controls["level_cap"]["max_level"].setValue(37)
    page.seed_edit.setText("482193")
    page.generate_button.click()
    expected = deepcopy(page.challenge)
    assert expected is not None, page.feedback.text()
    choose(page.preset_combo, "hardcore_nuzlocke")

    page.load_challenge(expected, "Monotype conservé")

    assert page.preset_combo.currentData() == "custom"
    assert page.states() == expected.rule_states
    assert page.monotype_config == expected.monotype
    assert page.seed_edit.text() == str(expected.seed)
    assert page.enforcement_combo.currentData() == "strict"
    assert page.parameter_controls["level_cap"]["max_level"].value() == 37
    assert page.challenge.to_dict() == expected.to_dict()
    page.generate_button.click()
    assert page.challenge.active_rules == expected.active_rules
    assert page.challenge.monotype == expected.monotype


def test_random_generation_exact_deterministic_and_with_constraints(window):
    page = window.challenge_page
    choose(page.preset_combo, "chaos")
    choose(page.state_controls["monotype"], "required")
    choose(page.state_controls["shiny_only"], "forbidden")
    page.count_spin.setValue(5)
    page.seed_edit.setText("4281")
    page.generate_button.click()
    first = deepcopy(page.challenge)
    assert first is not None, page.feedback.text()
    assert first.mode == "random"
    assert len(first.active_rules) == 5
    assert len(first.active_rules) == len(set(first.active_rules))
    assert "monotype" in first.active_rules
    assert "shiny_only" not in first.active_rules
    assert first.monotype["type_id"] == select_type(first.monotype["allowed_types"], 4281)
    page.generate_button.click()
    assert page.challenge.active_rules == first.active_rules
    assert page.challenge.monotype == first.monotype


@pytest.mark.parametrize("control", ["seed", "game", "mode", "count", "rule", "parameter", "enforcement"])
def test_changing_configuration_invalidates_preview_and_actions(window, control):
    page = generate_classic(window)
    if control == "seed":
        page.seed_edit.setText("482194")
    elif control == "game":
        page.game_combo.setCurrentIndex(1)
    elif control == "mode":
        choose(page.mode_combo, "random")
    elif control == "count":
        page.count_spin.setValue(page.count_spin.value() + 1)
    elif control == "rule":
        choose(page.state_controls["no_items"], "required")
    elif control == "parameter":
        values = next(iter(page.parameter_controls.values()))
        spin = next(iter(values.values()))
        spin.setValue(spin.value() + 1)
    else:
        choose(page.enforcement_combo, "strict")
    assert page.challenge is None
    assert not page.save_button.isEnabled()
    assert not page.launch_button.isEnabled()
    assert "Réglages modifiés" in page.preview.toPlainText()


@pytest.mark.parametrize("seed", ["abc", "-1", "9223372036854775808", "１２３"])
def test_invalid_seed_reports_error_without_stale_challenge(window, seed):
    page = generate_classic(window)
    page.seed_edit.setText(seed)
    page.generate_button.click()
    assert page.challenge is None
    assert not page.save_button.isEnabled()
    assert "seed" in page.feedback.text()
    assert not page.feedback.isHidden()


def test_impossible_rule_combination_shows_error(window):
    page = generate_classic(window)
    choose(page.state_controls["permanent_death"], "forbidden")
    page.generate_button.click()
    assert page.challenge is None
    assert not page.save_button.isEnabled()
    assert "interdite" in page.feedback.text()


def test_save_reload_and_copy_through_connected_pages(window):
    page = generate_classic(window)
    expected = page.challenge.to_dict()
    page.name_edit.setText("Noir · Run test")
    page.save_button.click()
    assert "sauvegardé" in page.feedback.text()
    assert window.profile_page.list_widget.count() == 1
    assert "1 profil(s)" in window.home_page.profile_count.text()

    window.nav_buttons[3].click()
    profiles_page = window.profile_page
    selected = profiles_page.selected_profile
    assert selected is not None
    assert selected.challenge.to_dict() == expected
    assert profiles_page.open_button.isEnabled()
    profiles_page.open_button.click()
    assert window.pages.currentIndex() == 1
    assert page.challenge.to_dict() == expected
    assert page.name_edit.text() == "Noir · Run test · copie"
    assert page.seed_edit.text() == "482193"
    page.save_button.click()
    profiles = window.profiles.list_profiles()
    assert len(profiles) == 2
    assert len({profile.id for profile in profiles}) == 2
    assert window.profiles.load(selected.id).challenge.to_dict() == expected


def test_corrupt_profile_is_reported_and_does_not_hide_valid_profiles(window, tmp_path):
    profile = save_classic(window)
    broken = tmp_path / "profiles" / "corrompu"
    broken.mkdir()
    (broken / "challenge.json").write_text("{invalide", encoding="utf-8")
    window.navigate(3)
    page = window.profile_page
    assert page.list_widget.count() == 1
    assert page.selected_profile.id == profile.id
    assert "corrompu" in page.warning.text()
    assert not page.warning.isHidden()
    assert page.open_button.isEnabled()


def test_corrupt_progress_uses_visible_fallback_and_preserves_file(window, tmp_path, monkeypatch):
    profile = save_classic(window)
    progress_file = tmp_path / "profiles" / profile.id / "progress.json"
    progress_file.write_text("{invalide", encoding="utf-8")
    original = progress_file.read_bytes()
    window.navigate(3)
    page = window.profile_page
    assert page.selected_profile is not None
    assert page.badges.value() == 0
    assert "progress.json" in page.warning.text()
    assert not page.warning.isHidden()
    messages = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: messages.append(args[2]))
    page.badges.setValue(2)
    page.progress_button.click()
    assert messages and "corrompu" in messages[-1]
    assert progress_file.read_bytes() == original


def test_progress_save_updates_storage_and_history(window, monkeypatch):
    profile = save_classic(window)
    window.navigate(3)
    page = window.profile_page
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    page.badges.setValue(3)
    page.captures.setValue(4)
    page.deaths.setValue(1)
    page.level_cap.setValue(24)
    page.zones.setText("Route 1, Arabelle, Route 1")
    page.progress_button.click()
    saved = window.profiles.load(profile.id)
    assert len(saved.progress["badges"]) == 3
    assert len(saved.progress["captures"]) == 4
    assert len(saved.progress["deaths"]) == 1
    assert saved.progress["current_level_cap"] == 24
    assert saved.progress["zones"] == ["Route 1", "Arabelle"]
    assert saved.history[-1]["event"] == "manual_progress_update"
    assert page.badges.value() == 3


def test_seed_change_never_reopens_wheel_with_stale_confirmable_type(window, monkeypatch):
    """Le type visible/confirmable doit correspondre à la seed courante."""
    page = window.challenge_page
    choose(page.preset_combo, "monotype")
    page.seed_edit.setText("4281")
    page.generate_button.click()
    initial = deepcopy(page.monotype_config)
    next_seed = next(seed for seed in range(100) if select_type(initial["allowed_types"], seed) != initial["type_id"])
    seen = []

    class CancelledWheel:
        DialogCode = QDialog.DialogCode

        def __init__(self, types, seed, configuration, parent):
            seen.append((seed, deepcopy(configuration)))

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr("app.ui.challenge_page.MonotypeDialog", CancelledWheel)
    page.seed_edit.setText(str(next_seed))
    page.wheel_button.click()
    assert seen
    seed, configuration = seen[0]
    assert seed == next_seed
    assert configuration is None or not configuration.get("type_id") or configuration["type_id"] == select_type(configuration["allowed_types"], seed, configuration["roll_index"])


def test_new_seed_preserves_monotype_preferences_and_allows_first_draw(window, catalog):
    page = window.challenge_page
    choose(page.preset_combo, "monotype")
    page.seed_edit.setText("4281")
    page.monotype_config = {
        "type_id": select_type(["fire", "water"], 4281, 2),
        "allowed_types": ["fire", "water"], "mode": "strict",
        "allow_reroll": False, "roll_index": 2,
    }
    page.generate_button.click()
    confirmed = page.challenge.monotype["type_id"]
    assert confirmed == page.monotype_config["type_id"]
    page.seed_edit.setText("41")
    assert page.monotype_config["allowed_types"] == ["fire", "water"]
    assert page.monotype_config["mode"] == "strict"
    assert page.monotype_config["allow_reroll"] is False
    assert page.monotype_config["roll_index"] == 0
    assert not page.monotype_config.get("type_id")
    assert "nouveau tirage requis" in page.monotype_label.text()
    wheel = MonotypeDialog(catalog.types, 41, page.monotype_config)
    try:
        wheel.animation_duration_ms = 1
        assert wheel.roll_button.isEnabled()
        assert not wheel.confirm_button.isEnabled()
        completed = QSignalSpy(wheel.wheel.spin_finished)
        wheel.roll_button.click()
        assert completed.count() > 0 or completed.wait(3000)
        page.monotype_config = wheel.configuration()
        accepted_type = page.monotype_config["type_id"]
        assert accepted_type == select_type(["fire", "water"], 41, 0)
        page.generate_button.click()
        assert page.challenge.monotype["type_id"] == accepted_type
        assert page.challenge.monotype["allow_reroll"] is False
    finally:
        wheel.close()
        wheel.deleteLater()


def test_regeneration_after_seed_change_and_reload_preserve_monotype(window):
    page = window.challenge_page
    choose(page.preset_combo, "monotype")
    page.seed_edit.setText("4281")
    page.generate_button.click()
    page.seed_edit.setText("14")
    assert not page.monotype_config.get("type_id")
    page.generate_button.click()
    expected = deepcopy(page.challenge)
    assert expected.monotype["type_id"] == select_type(expected.monotype["allowed_types"], 14, 0)
    page.seed_edit.setText("15")
    page.load_challenge(expected, "Monotype sauvegardé")
    assert page.seed_edit.text() == "14"
    assert page.monotype_config == expected.monotype
    assert "nouveau tirage requis" not in page.monotype_label.text()
    page.generate_button.click()
    assert page.challenge.monotype == expected.monotype


def test_invalid_launch_paths_show_error_without_starting_process(window, monkeypatch):
    page = generate_classic(window)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

    def unexpected_launch(*args, **kwargs):
        pytest.fail("Un chemin invalide ne doit lancer aucun processus.")

    monkeypatch.setattr("app.services.launcher_service.LauncherService.launch", unexpected_launch)
    page.launch_button.click()
    assert warnings
    assert "Paramètres" in warnings[-1]

