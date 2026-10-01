"""Parcours Qt synthétiques du suivi ; aucune ROM ni entrée DeSmuME."""

from dataclasses import replace
import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox, QScrollArea

from app.core.challenge_engine import ChallengeEngine
from app.core.nuzlocke_tracker import NuzlockeTracker
from app.events.game_event import GameObservation
from app.services.tracking_service import TrackingState
from app.ui.main_window import MainWindow
from app.ui.theme import STYLESHEET
from app.ui.tracking_panel import TrackingPanel
from app.ui.widgets.nuzlocke import NuzlockeWidget, UNAVAILABLE, species_name
from test_bridge_ui import publish, qt_app, until


@pytest.fixture
def window(qt_app, catalog, tmp_path):
    widget = MainWindow(catalog, tmp_path)
    yield widget
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


def create_profile(window, name="Blanc — Nuzlocke", game_id="white", nuzlocke=True):
    challenge = ChallengeEngine(window.catalog).generate(
        game_id, "custom" if nuzlocke else "normal",
        {"nuzlocke": "required"} if nuzlocke else {}, 1, 123)
    profile = window.profiles.create(name, challenge)
    window.refresh_home()
    return profile


def fingerprint_profiles(window):
    return {path.relative_to(window.profiles.root): path.read_bytes()
            for path in window.profiles.root.rglob("*.json")}


def test_profiles_are_never_implicitly_activated(window):
    page = window.bridge_page
    create_profile(window)
    assert page.profile_combo.count() == 2
    assert page.profile_combo.currentData() is None
    assert window.bridge_controller._thread is None
    assert page.tracking_panel.compact.profile_label.text() == "Aucun — diagnostic uniquement"
    assert page.tracking_panel.compact.availability_label.text() == UNAVAILABLE


def test_profile_selection_loads_saved_profile_without_writing(qt_app, window):
    profile = create_profile(window)
    before = fingerprint_profiles(window)
    page = window.bridge_page
    page.profile_combo.setCurrentIndex(page.profile_combo.findData(profile.id))
    until(qt_app, lambda: window.bridge_controller.tracking_state.profile_id == profile.id)
    assert page.game_combo.currentData() == "white"
    assert page.tracking_panel.compact.profile_label.text() == profile.name
    assert fingerprint_profiles(window) == before
    window.refresh_home()
    assert page.profile_combo.currentData() == profile.id


def test_profile_choice_is_locked_until_connection_is_stopped(qt_app, window):
    profile = create_profile(window)
    page = window.bridge_page
    page.profile_combo.setCurrentIndex(page.profile_combo.findData(profile.id))
    page.prepare_button.click()
    assert not page.profile_combo.isEnabled()
    until(qt_app, lambda: window.bridge_controller.state.status == "waiting")
    assert not page.profile_combo.isEnabled()
    page.stop_button.click()
    until(qt_app, lambda: window.bridge_controller.state.status == "stopped")
    assert page.profile_combo.isEnabled()
    page.profile_combo.setCurrentIndex(0)
    until(qt_app, lambda: window.bridge_controller.tracking_state.profile_id is None)


def test_incompatible_real_identity_disables_tracking_and_keeps_files(qt_app, window):
    profile = create_profile(window)
    before = fingerprint_profiles(window)
    page = window.bridge_page
    page.profile_combo.setCurrentIndex(page.profile_combo.findData(profile.id))
    page.game_combo.setCurrentIndex(page.game_combo.findData("black"))
    page.prepare_button.click()
    controller = window.bridge_controller
    until(qt_app, lambda: controller.state.status == "waiting")
    publish(controller.bridge, 1)
    until(qt_app, lambda: controller.tracking_state.status == "mismatch")
    assert "incompatible" in page.tracking_panel.compact.status_label.text()
    assert page.tracking_panel.compact.message_label.text()
    assert fingerprint_profiles(window) == before


def test_diagnostics_without_profile_does_not_write_progress(qt_app, window):
    create_profile(window)
    before = fingerprint_profiles(window)
    page = window.bridge_page
    page.prepare_button.click()
    controller = window.bridge_controller
    until(qt_app, lambda: controller.state.status == "waiting")
    publish(controller.bridge, 1)
    until(qt_app, lambda: controller.state.connected)
    assert controller.tracking_state.profile_id is None
    assert not controller.tracking_state.enabled
    assert fingerprint_profiles(window) == before


def test_profile_without_nuzlocke_stays_disabled(qt_app, window):
    profile = create_profile(window, nuzlocke=False)
    before = fingerprint_profiles(window)
    page = window.bridge_page
    page.profile_combo.setCurrentIndex(page.profile_combo.findData(profile.id))
    until(qt_app, lambda: window.bridge_controller.tracking_state.profile_id == profile.id)
    assert not window.bridge_controller.tracking_state.enabled
    assert "désactivé" in page.tracking_panel.compact.status_label.text()
    assert fingerprint_profiles(window) == before


def test_incomplete_identity_keeps_tracking_waiting_without_writes(qt_app, window):
    profile = create_profile(window)
    before = fingerprint_profiles(window)
    page = window.bridge_page
    page.profile_combo.setCurrentIndex(page.profile_combo.findData(profile.id))
    page.prepare_button.click()
    controller = window.bridge_controller
    until(qt_app, lambda: controller.state.status == "waiting")
    publish(controller.bridge, 1, game_id=None, game_code=None, game_region=None, rom_revision=None)
    until(qt_app, lambda: controller.state.connected)
    assert controller.tracking_state.status == "waiting"
    assert "incomplète" in page.tracking_panel.compact.message_label.text()
    assert fingerprint_profiles(window) == before


def test_new_window_restores_saved_capture_when_profile_is_selected(qt_app, window):
    profile = create_profile(window)
    observation = GameObservation(
        map_id=12, capture_zone_id="fixture_route", zone_name="Route synthétique",
        battle_active=True, battle_type="wild", encounter_kind="wild_standard",
        battle_id="synthetic-battle", species_id=504, level=3, hp=8, max_hp=12, outcome="captured")
    NuzlockeTracker().consume(profile, observation, session_id="synthetic-session", sequence=1)
    window.profiles.save(profile)
    before = fingerprint_profiles(window)
    restored = MainWindow(window.catalog, window.bridge_controller.base_dir)
    try:
        page = restored.bridge_page
        page.profile_combo.setCurrentIndex(page.profile_combo.findData(profile.id))
        until(qt_app, lambda: restored.bridge_controller.tracking_state.profile_id == profile.id)
        assert page.tracking_panel.compact.zone_label.text() == "Route synthétique"
        assert page.tracking_panel.compact.availability_label.text() == "Utilisée"
        assert page.tracking_panel.compact.result_label.text() == "Capturé"
        assert page.tracking_panel.history_table.rowCount() == 3
        assert fingerprint_profiles(window) == before
    finally:
        restored.close()
        restored.deleteLater()
        qt_app.processEvents()


@pytest.mark.parametrize("result,expected", [
    ("captured", "Capturé"), ("fainted", "Pokémon sauvage K.O."),
    ("escaped", "Le Pokémon sauvage a fui"), ("player_fled", "Le joueur a fui"),
    ("battle_ended_unknown", "Combat terminé, résultat inconnu"),
    ("duplicate_ignored", "Doublon ignoré — Species Clause"),
    ("invalid_encounter", "Rencontre non admissible"),
    ("special_encounter_ignored", "Rencontre spéciale ignorée"),
])
def test_compact_widget_renders_known_outcomes_without_guessing(qt_app, result, expected):
    widget = NuzlockeWidget()
    state = TrackingState(
        profile_id="test-profile", profile_name="Ma partie", status="waiting",
        message="État sauvegardé ; jeu non connecté.", current_map_id=12,
        current_zone_id="fixture_route_1", zone_name="Route de test",
        zone_used=True, zone_status="captured" if result == "captured" else "failed",
        encounter={"species_id": 504, "level": 3, "result": result},
    )
    widget.update_state(state)
    assert widget.zone_label.text() == "Route de test"
    assert widget.availability_label.text() == "Utilisée"
    assert widget.encounter_label.text() == "Ratentif · Niveau 3"
    assert widget.result_label.text() == expected
    widget.update_state(replace(state, current_zone_id=None, zone_name=None, zone_used=None,
                                zone_status=None, encounter=None))
    assert widget.zone_label.text() == UNAVAILABLE
    assert widget.availability_label.text() == UNAVAILABLE
    assert widget.encounter_label.text() == UNAVAILABLE
    assert widget.result_label.text() == UNAVAILABLE
    widget.close()


def test_tracking_panel_shows_automatic_history_and_documents_limits(qt_app):
    panel = TrackingPanel()
    events = tuple({"event": "capture_success", "timestamp": 1700000000 + index,
                    "capture_zone_id": f"fixture_zone_{index}", "species_id": 506,
                    "level": 4, "result": "captured"} for index in range(22))
    panel.update_state(TrackingState(history=events + ({"event": "manual_progress_update"},)))
    assert panel.history_table.rowCount() == 20
    assert panel.history_table.item(0, 2).text() == "fixture_zone_21"
    assert panel.history_table.item(0, 3).text() == "Ponchiot · Niv. 4"
    assert panel.history_table.item(0, 4).text() == "Capturé"
    assert "lectures de combat non documentées" in panel.validation_note.text()
    assert "En attente de validation sur la machine utilisateur." in panel.validation_note.text()
    panel.close()


def test_manual_progress_save_preserves_events_written_since_page_was_opened(window, monkeypatch):
    profile = create_profile(window)
    window.navigate(3)
    page = window.profile_page
    assert page.selected_profile.id == profile.id
    saved = window.profiles.load(profile.id)
    saved.history.append({"event": "zone_entered", "event_id": "synthetic:newer", "zone_id": "fixture_route"})
    window.profiles.save(saved)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes)
    page.badges.setValue(1)
    page.progress_button.click()
    reloaded = window.profiles.load(profile.id)
    assert any(event.get("event_id") == "synthetic:newer" for event in reloaded.history)
    assert reloaded.history[-1]["event"] == "manual_progress_update"
    assert reloaded.progress["badges"] == ["Badge 1"]


def test_tracking_panel_fits_minimum_window_and_remains_accessible(qt_app, window):
    previous = qt_app.styleSheet()
    qt_app.setStyleSheet(STYLESHEET)
    try:
        window.resize(1060, 640)
        window.navigate(5)
        window.show()
        qt_app.processEvents()
        page = window.bridge_page
        scroll = page.findChild(QScrollArea)
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.widget().width() <= scroll.viewport().width()
        scroll.ensureWidgetVisible(page.tracking_panel.compact.result_label)
        qt_app.processEvents()
        result = page.tracking_panel.compact.result_label
        assert scroll.viewport().rect().contains(result.mapTo(scroll.viewport(), result.rect().center()))
    finally:
        qt_app.setStyleSheet(previous)


def test_french_species_labels_cover_gen5_without_network():
    data = json.loads((Path(__file__).resolve().parents[1] / "data" / "species_fr.json").read_text(encoding="utf-8"))
    assert len(data["names"]) == 650
    assert data["source_revision"] in data["source"]
    assert species_name(511) == "Feuillajou"
    assert species_name(649) == "Genesect"
    assert species_name(None) == UNAVAILABLE
    assert species_name(650) == UNAVAILABLE
