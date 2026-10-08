"""Synthetic Qt/tracker checks; these do not validate a real game capture or KO."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QPushButton

from app.core.run_manager import RunManager
from app.models.challenge import Challenge
from app.services.run_tracking_service import RunTrackingService
from app.ui.game_mode_page import GameModePage


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


def create_run(manager, rules=()):
    challenge = Challenge("white", "custom", list(rules), {},
                          {"enforcement": "soft", "rule_parameters": {}}, None, 42)
    return manager.create("Blanc", "white", challenge=challenge, game_code="IRAF", region="FR", revision=0)


def observe(tracker, hp, *, reliable=True):
    pokemon = {"slot": 1, "species_id": 498, "level": 10, "hp": hp, "max_hp": 30}
    if reliable:
        pokemon.update(personality_id=123, original_trainer_id=456)
    return tracker.observe([pokemon], game_id="white", game_code="IRAF", region="FR", revision=0,
                           emulator_running=True)


@pytest.mark.parametrize("command", ["manual_capture", "manual_death", "badge_increment", "badge_decrement", "add_note"])
def test_compact_menu_preserves_existing_commands(page, tmp_path, command):
    page.set_persistent_run(create_run(RunManager(tmp_path / "runs")))
    spy = QSignalSpy(page.run_action_requested)

    assert page.run_bar.findChildren(QPushButton) == [page.manual_actions_button]
    assert page.manual_actions_button.menu() is page.manual_actions_menu
    assert page.manual_actions[command] in page.manual_actions_menu.actions()
    page.manual_actions[command].trigger()

    assert spy.count() == 1
    assert spy.at(0) == [command]


def test_actions_are_disabled_until_a_run_is_bound_and_after_unbinding(page, tmp_path):
    spy = QSignalSpy(page.run_action_requested)
    assert page.run_bar.isHidden()
    assert not page.manual_actions_button.isEnabled()
    for action in page.manual_actions.values():
        assert not action.isEnabled()
        action.trigger()
    assert spy.count() == 0

    page.set_persistent_run(create_run(RunManager(tmp_path / "runs")))
    assert not page.run_bar.isHidden()
    assert page.manual_actions_button.isEnabled()
    assert all(action.isEnabled() for action in page.manual_actions.values())

    page.set_persistent_run(None)
    assert page.run_bar.isHidden()
    assert page.death_tracking_label.isHidden()
    for action in page.manual_actions.values():
        assert not action.isEnabled()
        action.trigger()
    assert spy.count() == 0


@pytest.mark.parametrize("rules", [(), ("nuzlocke",), ("permanent_death",), ("nuzlocke", "permanent_death")])
def test_death_tracking_notice_matches_actual_rules_without_manual_capture_or_badges(page, tmp_path, rules):
    manager = RunManager(tmp_path / "runs")
    run = create_run(manager, rules)
    tracker = RunTrackingService(manager)
    tracker.activate(run.run_id)
    try:
        page.set_persistent_run(observe(tracker, 30))
        page.set_persistent_run(observe(tracker, 0))
        automatic = len(rules) == 2
        deaths = tracker.active_run.deaths or []
        assert len(deaths) == (1 if automatic else 0)
        assert not page.death_tracking_label.isHidden()
        if automatic:
            assert "individu fiable" in page.death_tracking_label.text()
            assert "PV > 0 à 0" in page.death_tracking_label.text()
            assert deaths[0]["source"] == "automatic"
            assert page.stat_labels["deaths"].text() == "1"
            assert "Mort dans cette partie" in page.team_slots[0].status_label.text()
            assert manager.load(run.run_id).death_count == 1
        else:
            assert "inactive" in page.death_tracking_label.text()
        assert tracker.active_run.captures is None
        assert tracker.active_run.badges is None
        assert "manuel" in page.manual_actions["manual_capture"].text()
        assert "Manuel" in page.stat_labels["badges"].text()
    finally:
        tracker.close()


@pytest.mark.parametrize("observation", ["zero_first", "weak_identity", "disconnected"])
def test_unreliable_death_observation_stays_pending_and_manual_fallback_accessible(page, tmp_path, observation):
    manager = RunManager(tmp_path / "runs")
    run = create_run(manager, ("nuzlocke", "permanent_death"))
    tracker = RunTrackingService(manager)
    tracker.activate(run.run_id)
    try:
        if observation != "zero_first":
            observe(tracker, 30, reliable=observation != "weak_identity")
        if observation == "disconnected":
            tracker.heartbeat(False, "white")
        page.set_persistent_run(observe(tracker, 0, reliable=observation != "weak_identity"))

        assert tracker.active_run.death_count is None
        assert tracker.active_run.deaths is None
        assert len(tracker.pending_deaths) == 1
        assert "1 à confirmer" in page.stat_labels["deaths"].text()
        assert page.manual_actions["manual_death"].isEnabled()
        assert "secours manuel" in page.manual_actions["manual_death"].text()
        assert "Détails > Progression" in page.manual_actions["manual_death"].toolTip()
    finally:
        tracker.close()
