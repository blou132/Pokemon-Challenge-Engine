"""Preview → exact saved ID → fresh application → restore, on temporary profiles."""

from copy import deepcopy
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.profile_manager import ProfileManager
from app.ui.main_window import MainWindow


CLASSIC_RULES = {"nuzlocke", "permanent_death", "species_clause"}


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app, catalog, tmp_path):
    window = MainWindow(catalog, tmp_path)
    yield window
    window.close()
    window.deleteLater()
    qt_app.processEvents()


def choose(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def classic(page):
    choose(page.game_combo, "white2")
    choose(page.preset_combo, "classic_nuzlocke")
    page.seed_edit.setText("6530407519846614198")
    page.generate_button.click()
    assert page.challenge.mode == "custom"
    assert set(page.challenge.active_rules) == CLASSIC_RULES
    assert "3 règle(s)" in page.preview.toPlainText()
    page.name_edit.setText("noir test")


def test_new_three_rule_profile_is_selected_over_same_named_normal_profile(window):
    page = window.challenge_page
    classic(page)
    choose(page.mode_combo, "normal")
    page.generate_button.click()
    page.save_button.click()
    old_id = window.profile_page.selected_profile.id
    assert window.profile_page.selected_profile.challenge.active_rules == []

    classic(page)
    saved = QSignalSpy(page.saved)
    page.save_button.click()
    assert saved.count() == 1
    new_profile = saved.at(0)[0]
    assert new_profile.id != old_id
    assert window.profiles.load(new_profile.id).challenge.active_rules == sorted(CLASSIC_RULES)
    assert window.profile_page.selected_profile.id == new_profile.id
    assert window.profile_page.selected_profile.challenge.mode == "custom"
    assert "3 règle(s)" in window.profile_page.preview.toPlainText()
    window.navigate(3)
    assert window.profile_page.selected_profile.id == new_profile.id
    assert window.profiles.load(old_id).challenge.mode == "normal"
    assert window.profiles.load(old_id).challenge.active_rules == []


def test_white2_classic_roundtrip_and_restore_exact_options_after_restart(qt_app, catalog, tmp_path):
    first = MainWindow(catalog, tmp_path)
    try:
        page = first.challenge_page
        classic(page)
        expected = deepcopy(page.challenge.to_dict())
        saved = QSignalSpy(page.saved)
        page.save_button.click()
        assert saved.count() == 1
        profile_id = saved.at(0)[0].id
        raw = json.loads((tmp_path / "profiles" / profile_id / "challenge.json").read_text(encoding="utf-8"))
        assert raw["mode"] == "custom"
        assert raw["game_id"] == "white2"
        assert raw["active_rules"] == sorted(CLASSIC_RULES)
        assert raw["seed"] == 6530407519846614198
        assert raw["settings"]["preset_id"] == "classic_nuzlocke"
    finally:
        first.close()
        first.deleteLater()
        qt_app.processEvents()

    second = MainWindow(catalog, tmp_path)
    try:
        reloaded = ProfileManager(tmp_path / "profiles").load(profile_id)
        assert reloaded.challenge.to_dict() == expected
        second.navigate(3)
        assert second.profile_page.selected_profile.id == profile_id
        assert "3 règle(s)" in second.profile_page.preview.toPlainText()
        second.profile_page.open_button.click()
        page = second.challenge_page
        assert page.challenge.to_dict() == expected
        assert page.game_combo.currentData() == "white2"
        assert page.mode_combo.currentData() == "custom"
        assert page.preset_combo.currentData() == "classic_nuzlocke"
        assert page.states() == expected["rule_states"]
        assert page.seed_edit.text() == str(expected["seed"])
        assert {key for key, value in page.states().items() if value == "required"} == CLASSIC_RULES
        page.generate_button.click()
        assert set(page.challenge.active_rules) == CLASSIC_RULES
        assert page.challenge.mode == "custom"
        assert page.challenge.settings["preset_id"] == "classic_nuzlocke"
    finally:
        second.close()
        second.deleteLater()
        qt_app.processEvents()


def test_new_preview_does_not_silently_replace_an_existing_profile(window):
    page = window.challenge_page
    classic(page)
    choose(page.mode_combo, "normal")
    page.generate_button.click()
    page.save_button.click()
    saved_id = window.profile_page.selected_profile.id
    original = window.profiles.load(saved_id).challenge.to_dict()
    classic(page)
    assert "non enregistré" in page.feedback.text().casefold()
    assert window.profiles.load(saved_id).challenge.to_dict() == original
    assert len(window.profiles.list_profiles()) == 1


def test_customized_preset_restores_custom_without_reapplying_preset(window):
    page = window.challenge_page
    classic(page)
    choose(page.state_controls["no_items"], "required")
    choose(page.state_controls["shiny_only"], "forbidden")
    page.generate_button.click()
    expected = page.challenge.to_dict()
    assert expected["settings"]["preset_id"] == "custom"
    page.save_button.click()
    profile = window.profile_page.selected_profile
    choose(page.preset_combo, "monotype")
    window.open_profile(profile)
    assert page.preset_combo.currentData() == "custom"
    assert page.states() == expected["rule_states"]
    assert page.challenge.to_dict() == expected


def test_failed_readback_never_reports_a_successful_save(window, monkeypatch):
    page = window.challenge_page
    classic(page)
    signals = QSignalSpy(page.saved)
    def unreadable(profile_id):
        raise ValueError("Fichier inaccessible pendant la relecture")
    monkeypatch.setattr(window.profiles, "load", unreadable)
    page.save_button.click()
    assert signals.count() == 0
    assert "relecture" in page.feedback.text()


def test_inactive_profile_level_cap_is_hidden_and_cannot_overwrite_old_progress(window, monkeypatch):
    page = window.challenge_page
    classic(page)
    page.save_button.click()
    profile = window.profile_page.selected_profile
    profile.progress["current_level_cap"] = 28  # Historical manual data remains local and preserved.
    window.profiles.save(profile)
    window.profile_page.refresh(select_profile_id=profile.id)
    assert window.profile_page.level_cap.isHidden()
    assert not window.profile_page.level_cap.isEnabled()
    window.profile_page.level_cap.setValue(1)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.profile_page.save_progress()
    assert window.profiles.load(profile.id).progress["current_level_cap"] == 28


def test_active_parameters_survive_fresh_manager_and_restore(window):
    page = window.challenge_page
    classic(page)
    # Catch Limit belongs to its own rule and conflicts with Nuzlocke.
    # Exercise a valid custom configuration without weakening that constraint.
    choose(page.preset_combo, "custom")
    for rule_id in ("monotype", "level_cap", "catch_limit"):
        choose(page.state_controls[rule_id], "required")
    page.parameter_controls["level_cap"]["max_level"].setValue(37)
    page.parameter_controls["catch_limit"]["per_zone"].setValue(2)
    page.generate_button.click()
    assert page.challenge is not None, page.feedback.text()
    expected = page.challenge.to_dict()
    page.save_button.click()
    selected = window.profile_page.selected_profile
    loaded = ProfileManager(window.profiles.root).load(selected.id)
    assert loaded.challenge.to_dict() == expected
    window.open_profile(loaded)
    assert page.challenge.to_dict() == expected
    assert page.parameter_controls["level_cap"]["max_level"].value() == 37
    assert page.parameter_controls["catch_limit"]["per_zone"].value() == 2
    assert page.monotype_config == expected["monotype"]
