"""Synthetic observations exercise rules; these are not real-game validation."""

from copy import deepcopy
from dataclasses import asdict

import pytest

from app.core.nuzlocke_tracker import NuzlockeTracker
from app.events.game_event import GameObservation
from app.models.challenge import Challenge
from app.models.profile import Profile, validate_progress


def make_profile(*, clause=False, enabled=True, game="white", identifier="test_profile"):
    rules = (["nuzlocke"] if enabled else []) + (["species_clause"] if clause else [])
    challenge = Challenge(game, "custom", rules, {}, {"enforcement": "soft", "rule_parameters": {}}, None, 1)
    return Profile(identifier, "Test synthétique", challenge)


def observation(**changes):
    data = asdict(GameObservation(map_id=7, capture_zone_id="route_1", zone_name="Route 1", battle_active=False))
    data.update(changes)
    return GameObservation.from_dict(data)


def battle(**changes):
    return observation(**({"battle_active": True, "battle_type": "wild", "encounter_kind": "wild_standard",
                          "battle_id": "opponent-123", "species_id": 504, "level": 3, "hp": 12,
                          "max_hp": 12} | changes))


def feed(profile, value, sequence, session="session-one"):
    return NuzlockeTracker().consume(profile, value, session_id=session, sequence=sequence, timestamp=1000 + sequence)


def zone(profile, identifier="route_1"):
    return profile.progress["nuzlocke"]["zones"][identifier]


def test_zone_entry_and_first_encounter_are_separate():
    profile = make_profile()
    events = feed(profile, observation(), 1)
    assert [event.event for event in events] == ["zone_entered"]
    assert zone(profile)["used"] is False
    events = feed(profile, battle(), 2)
    assert [event.event for event in events] == ["wild_encounter_started"]
    assert zone(profile)["status"] == "encounter_started"
    assert zone(profile)["first_encounter"]["species_id"] == 504
    validate_progress(profile.progress)


@pytest.mark.parametrize("result,event", [("captured", "capture_success"), ("fainted", "wild_fainted"),
    ("escaped", "wild_escaped"), ("player_fled", "player_fled"), ("battle_ended_unknown", "battle_ended_unknown")])
def test_explicit_results_consume_once(result, event):
    profile = make_profile()
    feed(profile, battle(), 1)
    emitted = feed(profile, battle(outcome=result, battle_active=False), 2)
    assert [value.event for value in emitted] == [event]
    assert zone(profile)["used"] is True
    assert zone(profile)["first_encounter"]["result"] == result
    assert zone(profile)["status"] == ("captured" if result == "captured" else "failed")
    previous = deepcopy(profile.history)
    feed(profile, battle(outcome=result, battle_active=False), 3)
    assert profile.history == previous
    validate_progress(profile.progress)


def test_zero_hp_is_fainted_and_disappearance_is_never_capture():
    profile = make_profile()
    feed(profile, battle(), 1)
    feed(profile, battle(hp=0), 2)
    assert zone(profile)["first_encounter"]["result"] == "fainted"
    second = make_profile()
    feed(second, battle(), 1)
    feed(second, observation(), 2)
    assert zone(second)["first_encounter"]["result"] == "battle_ended_unknown"
    assert second.progress["nuzlocke"]["captured_species"] == []


def test_null_readings_do_not_finish_battle():
    profile = make_profile()
    feed(profile, battle(), 1)
    feed(profile, observation(battle_active=None), 2)
    assert zone(profile)["status"] == "encounter_started"
    assert profile.progress["nuzlocke"]["active_encounter"] is not None


def test_species_clause_ignores_exact_species_then_accepts_next():
    profile = make_profile(clause=True)
    feed(profile, battle(outcome="captured"), 1)
    feed(profile, battle(capture_zone_id="route_2", battle_id="second"), 2)
    assert zone(profile, "route_2")["status"] == "ignored_by_clause"
    assert zone(profile, "route_2")["used"] is False
    assert zone(profile, "route_2")["first_encounter"] is None
    feed(profile, battle(capture_zone_id="route_2", battle_id="third", species_id=505), 3)
    assert zone(profile, "route_2")["first_encounter"]["species_id"] == 505
    assert zone(profile, "route_2")["status"] == "encounter_started"


def test_clause_disabled_duplicate_consumes_and_no_nuzlocke_writes_nothing():
    profile = make_profile()
    profile.progress["captures"].append({"species_id": 504})
    feed(profile, battle(outcome="captured"), 1)
    assert zone(profile)["used"] is True
    disabled = make_profile(enabled=False)
    original = deepcopy(disabled)
    assert feed(disabled, battle(outcome="captured"), 1) == []
    assert disabled == original


def test_manual_species_ids_count_but_manual_placeholders_do_not():
    profile = make_profile(clause=True)
    profile.progress["captures"] = [{"manual": True}, {"species_id": 504}]
    feed(profile, battle(), 1)
    assert zone(profile)["last_ignored"]["result"] == "duplicate_ignored"


@pytest.mark.parametrize("kind", ["wild_special", "static", "gift", "egg", "fossil", "scripted"])
def test_special_encounters_do_not_consume(kind):
    profile = make_profile()
    emitted = feed(profile, battle(encounter_kind=kind), 1)
    assert emitted[-1].event == "special_encounter_ignored"
    assert zone(profile)["status"] == "unused"
    assert zone(profile)["used"] is False


@pytest.mark.parametrize("kind", ["trainer", "double", "scripted"])
def test_incompatible_battles_never_consume(kind):
    profile = make_profile()
    emitted = feed(profile, battle(battle_type=kind, outcome="captured", hp=0), 1)
    assert emitted[-1].event == "invalid_encounter"
    assert zone(profile)["used"] is False


@pytest.mark.parametrize("change", [{"capture_zone_id": None}, {"battle_id": None}, {"species_id": None},
                                    {"battle_type": "unknown"}, {"encounter_kind": "unknown"}])
def test_missing_required_evidence_does_not_start(change):
    profile = make_profile()
    feed(profile, battle(**change), 1)
    assert profile.progress["nuzlocke"]["active_encounter"] is None
    assert not any(value["used"] for value in profile.progress["nuzlocke"]["zones"].values())


def test_changing_zone_and_return_does_not_reset_consumed_zone():
    profile = make_profile()
    feed(profile, battle(outcome="captured"), 1)
    feed(profile, observation(capture_zone_id="route_2", map_id=8), 2)
    feed(profile, battle(battle_id="another"), 3)
    assert zone(profile)["used"] is True
    assert zone(profile)["first_encounter"]["battle_id"] == "opponent-123"
    assert profile.history[-1]["event"] == "zone_already_used"
    assert len([event for event in profile.history if event["event"] == "zone_entered"]) == 3


def test_finish_uses_encounter_origin_after_map_changes():
    profile = make_profile()
    feed(profile, battle(), 1)
    feed(profile, battle(capture_zone_id="route_2", outcome="captured", battle_active=False), 2)
    assert zone(profile)["used"] is True
    assert zone(profile, "route_2")["used"] is False


def test_same_battle_cannot_consume_second_zone_after_map_change():
    profile = make_profile()
    feed(profile, battle(), 1)
    feed(profile, battle(capture_zone_id="route_2"), 2)
    feed(profile, battle(capture_zone_id="route_2", outcome="captured"), 3)
    feed(profile, battle(capture_zone_id="route_2", outcome="captured"), 4)
    assert zone(profile)["used"] is True
    assert zone(profile, "route_2")["status"] == "unused"
    assert sum(event["event"] == "wild_encounter_started" for event in profile.history) == 1


@pytest.mark.parametrize("changes", [{"battle_type": "trainer"}, {"battle_type": "double"},
                                      {"encounter_kind": "scripted"}])
def test_contradictory_battle_classification_never_claims_capture(changes):
    profile = make_profile()
    feed(profile, battle(), 1)
    feed(profile, battle(outcome="captured", **changes), 2)
    assert zone(profile)["first_encounter"]["result"] == "battle_ended_unknown"
    assert profile.progress["nuzlocke"]["captured_species"] == []


def test_duplicate_and_old_observations_and_reconnection_are_idempotent():
    profile = make_profile()
    feed(profile, battle(), 10)
    original = deepcopy(profile)
    assert feed(profile, battle(), 10) == []
    assert feed(profile, observation(capture_zone_id="wrong"), 9) == []
    assert profile == original
    feed(profile, battle(), 1, session="session-two")
    feed(profile, battle(outcome="captured"), 2, session="session-two")
    feed(profile, battle(outcome="captured"), 1, session="session-three")
    assert sum(event["event"] == "wild_encounter_started" for event in profile.history) == 1
    assert sum(event["event"] == "capture_success" for event in profile.history) == 1
    assert len({event["id"] for event in profile.history}) == len(profile.history)


def test_next_battle_without_end_keeps_unknown_instead_of_borrowing_capture():
    profile = make_profile()
    feed(profile, battle(), 1)
    feed(profile, battle(battle_id="different", outcome="captured"), 2)
    assert zone(profile)["first_encounter"]["result"] == "battle_ended_unknown"


def test_unknown_type_can_be_resolved_later():
    profile = make_profile()
    feed(profile, battle(battle_type="unknown"), 1)
    feed(profile, battle(), 2)
    assert zone(profile)["status"] == "encounter_started"


@pytest.mark.parametrize("changes", [{"hp": True}, {"hp": 13}, {"map_id": -1}, {"species_id": 650},
                                     {"battle_active": 1}, {"outcome": []}, {"encounter_kind": "invented"}])
def test_invalid_observation_is_rejected(changes):
    with pytest.raises(ValueError):
        battle(**changes)
