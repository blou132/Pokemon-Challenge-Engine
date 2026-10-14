"""Native Qt views of synthetic persisted observations; no live game claim."""
from copy import deepcopy
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.bridge.state import BridgeState
from app.core.challenge_engine import ChallengeEngine
from app.core.run_manager import RunManager
from app.models.profile import Profile
from app.models.run import history_event
from app.services.run_tracking_service import RunTrackingService
from app.ui.game_mode_page import GameModePage, TeamSlot
from app.ui.run_dialogs import RunDetailsDialog
from app.ui.widgets.rule_observation import rule_observation_text


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def page(qt_app, catalog):
    widget = GameModePage(catalog)
    yield widget
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


def pokemon(species=4, *, pid=0, trainer=0, level=5, slot=1, form=0):
    result = {"species_id": species, "level": level, "hp": 25, "max_hp": 30, "slot": slot}
    if pid is not None:
        result["personality_id"] = pid
    if trainer is not None:
        result["original_trainer_id"] = trainer
    if form is not None:
        result["form"] = form
    return result


def persisted_run(tmp_path, catalog, *, rules=("shiny_only", "level_cap"), party=None,
                  earlier=None, name="Observations de test"):
    states = {key: "required" if key in rules else "possible" for key in catalog.rules}
    monotype = {"type_id": "fire", "mode": "soft", "allowed_types": ["fire"],
                "allow_reroll": False, "roll_index": 0}
    challenge = ChallengeEngine(catalog).generate("white", "custom" if rules else "normal", states, 0, 42,
        settings={"rule_parameters": {"level_cap": {"max_level": 20}}}, monotype=monotype)
    manager = RunManager(tmp_path / "runs")
    run = manager.create(name, "white", challenge=challenge, game_code="IRAF", region="FR", revision=0)
    if party is not None:
        service = RunTrackingService(manager)
        service.activate(run.run_id)
        try:
            if earlier is not None:
                service.observe(earlier, game_id="white", game_code="IRAF", region="FR", revision=0,
                                emulator_running=True)
            service.observe(party, game_id="white", game_code="IRAF", region="FR", revision=0,
                            emulator_running=True)
        finally:
            service.close()
    return manager, manager.load(run.run_id)


def close(widget, app):
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_rules_tab_exposes_saved_cap_shiny_and_observation_scope(qt_app, tmp_path, catalog):
    manager, run = persisted_run(tmp_path, catalog, party=[pokemon(pid=8, level=21)])
    before = (manager.root / run.run_id / "run.json").read_bytes()
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    try:
        text = dialog.rules_view.toPlainText()
        assert "Règles figées" in text
        assert "Suivi automatique" in text and "Suivi partiel" in text
        assert "Niveau 21 / plafond 20 : dépassement observé." in text
        assert "Pokémon normal présent" in text
        assert "Utilisation en combat inconnue" in text
        assert "dernières observations enregistrées" in text
        assert json.loads(dialog.technical_view.toPlainText()) == run.rules_snapshot
        assert dialog.technical_view.isHidden()
        assert (manager.root / run.run_id / "run.json").read_bytes() == before
    finally:
        close(dialog, qt_app)


def test_team_tab_distinguishes_shiny_normal_and_unknown(qt_app, tmp_path, catalog):
    manager, run = persisted_run(tmp_path, catalog, party=[pokemon(), pokemon(7, pid=8, slot=2),
        pokemon(25, pid=None, trainer=None, slot=3)])
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    try:
        assert "★ Shiny" in dialog.team_table.item(0, 0).text()
        assert "Normal · non shiny" in dialog.team_table.item(1, 0).text()
        assert "Shiny : inconnu" in dialog.team_table.item(2, 0).text()
        assert "Statut shiny inconnu : identité incomplète." in dialog.rules_view.toPlainText()
    finally:
        close(dialog, qt_app)


def test_rules_tab_keeps_missing_variable_form_unknown(qt_app, tmp_path, catalog):
    manager, run = persisted_run(tmp_path, catalog, rules=("monotype",), party=[pokemon(479, form=None)])
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    try:
        text = dialog.rules_view.toPlainText()
        assert "Motisma" in text
        assert "Types non vérifiables" in text
        assert "non vérifiable" in text
        assert "non conforme" not in text.lower()
    finally:
        close(dialog, qt_app)


def test_game_mode_uses_frozen_cap_and_shiny_observations(page, tmp_path, catalog):
    _, run = persisted_run(tmp_path, catalog, party=[pokemon(level=21), pokemon(7, pid=8, slot=2)])
    page.set_persistent_run(run)
    assert page.stat_labels["level_cap"].text() == "20"
    assert "★ Shiny" == page.team_slots[0].shiny_label.text()
    assert "Normal · non shiny" == page.team_slots[1].shiny_label.text()
    assert "Niveau 21 / plafond 20" in page.rule_observation_label.text()
    assert not page.rule_observation_label.isHidden()
    assert page.rule_observation_label.textFormat() == Qt.TextFormat.PlainText
    # Editing or selecting a reusable profile cannot replace this run's snapshot.
    changed = deepcopy(run.rules_snapshot)
    changed["settings"]["rule_parameters"]["level_cap"]["max_level"] = 90
    from app.models.challenge import Challenge
    page.set_profile(Profile("other", "Autre modèle", Challenge.from_dict(changed)))
    assert page.stat_labels["level_cap"].text() == "20"
    assert "plafond 90" not in page.rule_observation_label.text()


def test_disconnected_mode_labels_persisted_evidence_as_offline(page, tmp_path, catalog):
    _, run = persisted_run(tmp_path, catalog, party=[pokemon(pid=8, level=21)])
    page.set_persistent_run(run)
    page.set_bridge_state(BridgeState(status="disconnected", game_id="white"))
    assert "hors ligne" in page.team_note.text()
    assert "déconnecté" in page.connection_badge.text()
    assert "dernières observations enregistrées" in page.rule_observation_label.text()
    assert "Normal · non shiny" in page.team_slots[0].shiny_label.text()
    assert "Niveau 21 / plafond 20" in page.rule_observation_label.text()


def test_bridge_for_other_game_never_replaces_run_observations(page, tmp_path, catalog):
    _, run = persisted_run(tmp_path, catalog, party=[pokemon(pid=8)])
    page.set_persistent_run(run)
    page.set_bridge_state(BridgeState(status="receiving", game_id="black2", party_size=1,
                                      party=[pokemon(25, pid=0)]))
    assert "hors ligne" in page.team_note.text()
    assert "Salamèche" in page.team_slots[0].name_label.text()
    assert "Pikachu" not in page.team_slots[0].name_label.text()
    assert page.team_slots[0].shiny_label.text() == "Normal · non shiny"


def test_empty_observations_do_not_render_global_compliance(page, tmp_path, catalog):
    _, run = persisted_run(tmp_path, catalog)
    page.set_persistent_run(run)
    text = page.rule_observation_label.text()
    assert "Aucune conclusion sur la conformité de la partie." in text
    assert "1 conforme" not in text
    assert page.team_slots[0].shiny_label.text() == "Shiny : inconnu"


def test_detaching_persistent_run_clears_challenge_evidence_from_diagnostic(page, tmp_path, catalog):
    _, run = persisted_run(tmp_path, catalog, party=[pokemon(pid=8, level=21)])
    page.set_persistent_run(run)
    page.set_persistent_run(None)
    assert page.rule_observation_label.isHidden()
    assert page.mode_label.text() == "Diagnostic uniquement"
    assert page.stat_labels["level_cap"].text() == "Non disponible"
    assert "Normal · non shiny" not in page.team_slots[0].shiny_label.text()


def test_switch_to_classic_clears_cap_and_hides_challenge_observations(page, tmp_path, catalog):
    _, challenge_run = persisted_run(tmp_path, catalog, party=[pokemon(pid=8, level=21)])
    _, classic_run = persisted_run(tmp_path, catalog, rules=(), party=[pokemon()], name="Partie classique")
    page.set_persistent_run(challenge_run)
    page.set_persistent_run(classic_run)
    assert page.rule_observation_label.isHidden()
    assert page.stat_labels["level_cap"].text() == "Non renseigné"
    assert page.mode_label.text() == "Classique"
    assert page.team_slots[0].shiny_label.text() == "★ Shiny"


def test_rules_tab_retains_past_level_violation_with_history_scope(qt_app, tmp_path, catalog):
    manager, run = persisted_run(tmp_path, catalog, rules=("level_cap",),
                                 earlier=[pokemon(level=21)], party=[pokemon(level=10)])
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    try:
        text = dialog.rules_view.toPlainText()
        assert "Niveau 10 / plafond 20 : conforme." in text
        assert "Historique ·" in text and "Niveau 21 / plafond 20 : dépassement observé." in text
        assert "1 conforme" in text
    finally:
        close(dialog, qt_app)


@pytest.mark.parametrize("party,message", [
    (None, "Observation d'équipe historique inexploitable"),
    ([None], "Observation d'équipe historique inexploitable"),
    ([{"species_id": [4], "level": 21}], "Pokémon historique incomplet ou invalide"),
    ([{"species_id": 4, "level": 21, "pokemon_key": []}], "Pokémon historique incomplet ou invalide"),
])
def test_legacy_unusable_history_does_not_break_rules_tab(qt_app, tmp_path, catalog, party, message):
    manager, run = persisted_run(tmp_path, catalog, rules=("level_cap",), party=[pokemon()])
    # Older run files permit arbitrary JSON inside event.payload. Loading a
    # valid archive must not crash merely because it contains unusable evidence.
    event = history_event("party_changed", "automatic", {"party": party})
    manager.update(run.run_id, lambda stored: stored.history.append(event))
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    try:
        text = dialog.rules_view.toPlainText()
        assert message in text
        assert "Niveau 5 / plafond 20 : conforme." in text
    finally:
        close(dialog, qt_app)


def test_unsupported_action_rules_remain_unavailable_after_hp_gain(tmp_path, catalog):
    prior, current = pokemon(), pokemon()
    prior["hp"] = 10
    _, run = persisted_run(tmp_path, catalog, rules=("no_items", "no_healing", "no_pokemon_center"),
                            earlier=[prior], party=[current])
    text = rule_observation_text(run, catalog, detailed=True)
    assert text.count("Non disponible") == 3
    assert "non conforme" not in text.lower()
    assert "ne prouve pas" in text


def test_shiny_presentation_rejects_unverified_generation(qt_app):
    slot = TeamSlot(1)
    try:
        slot.set_pokemon(pokemon(), generation=4)
        assert slot.shiny_label.text() == "Shiny : inconnu"
        slot.set_pokemon(pokemon(), generation=5)
        assert slot.shiny_label.text() == "★ Shiny"
        slot.set_pokemon(None)
        assert slot.shiny_label.text() == "Shiny : inconnu"
    finally:
        close(slot, qt_app)
