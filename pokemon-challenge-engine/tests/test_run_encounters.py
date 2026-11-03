"""Persisted declarations are evidence of what was declared, never RAM events."""
from copy import deepcopy

import pytest

from app.core.manual_rule_event import capture_records
from app.models.run import Run
from app.services.run_tracking_service import RunTrackingService
from test_rule_observation import member, observe, results, tracking


RULES = ["nuzlocke", "permanent_death", "species_clause", "catch_limit"]


def encounter(service, species=504, outcome="captured", zone="Route 1", kind="wild_standard", **kwargs):
    return service.record_rule_event("wild_encounter", confirmed=True, zone=zone,
        details={"species_id": species, "outcome": outcome, "encounter_kind": kind}, **kwargs)


def nuzlocke(service):
    return results(service.active_run)["nuzlocke"].checks


@pytest.mark.parametrize("outcome", ["captured", "fainted", "player_fled", "escaped", "unknown"])
def test_declared_first_encounter_consumes_zone_after_resume(tmp_path, outcome):
    manager, initial, service = tracking(tmp_path, RULES, params={"catch_limit": {"per_zone": 2}})
    encounter(service, outcome=outcome)
    snapshot = deepcopy(service.active_run.rules_snapshot)
    service.close()
    resumed = RunTrackingService(manager)
    assert resumed.active_run.run_id == initial.run_id
    encounter(resumed, species=506)
    actual = results(manager.load(initial.run_id))
    assert any(item.state == "violation" and item.species_id == 506 for item in actual["nuzlocke"].checks)
    assert all(item.scope == "manual" for item in actual["nuzlocke"].checks)
    assert not actual["catch_limit"].checks  # A higher cap never reopens Nuzlocke.
    assert len(capture_records(resumed.active_run)) == (2 if outcome == "captured" else 1)
    assert resumed.active_run.rules_snapshot == snapshot
    resumed.close()


def test_verified_species_reroll_does_not_consume_new_zone(tmp_path):
    _, _, service = tracking(tmp_path, RULES)
    encounter(service, zone="Route 1")
    encounter(service, outcome="duplicate_ignored", zone="Route 2")
    encounter(service, species=506, zone="Route 2")
    actual = results(service.active_run)
    assert [item.state for item in actual["species_clause"].checks] == ["compliant"]
    assert not any(item.state in ("unknown", "violation") for item in actual["nuzlocke"].checks)
    assert len(capture_records(service.active_run)) == 2


def test_reroll_cannot_reopen_a_consumed_zone(tmp_path):
    _, _, service = tracking(tmp_path, RULES)
    encounter(service)
    encounter(service, outcome="duplicate_ignored")
    encounter(service, species=506)
    assert any(item.state == "violation" for item in nuzlocke(service))
    clause = results(service.active_run)["species_clause"].checks[0]
    assert "ne se rouvre pas" in clause.message


def test_future_capture_cannot_justify_an_earlier_reroll(tmp_path):
    _, _, service = tracking(tmp_path, RULES)
    encounter(service, outcome="duplicate_ignored")
    encounter(service, zone="Route 2")
    encounter(service, species=506)
    encounter(service, species=507)
    actual = results(service.active_run)
    assert actual["species_clause"].checks[0].state == "unknown"
    assert any(item.species_id == 506 and item.state == "unknown" for item in actual["nuzlocke"].checks)
    assert any(item.species_id == 507 and item.state == "violation" for item in actual["nuzlocke"].checks)


def test_corrected_capture_keeps_its_original_timeline_position(tmp_path):
    manager, initial, service = tracking(tmp_path, RULES)
    first = encounter(service, species=504, zone="Route 0").history[-1]
    encounter(service, species=506, outcome="duplicate_ignored")
    second = encounter(service, species=507).history[-1]
    encounter(service, species=506, zone="Route 0", corrects_event_id=first["event_id"], note="Mauvaise espèce")
    actual = results(manager.load(initial.run_id))
    assert actual["species_clause"].checks[0].state == "compliant"
    assert not any(item.state in ("unknown", "violation") for item in actual["nuzlocke"].checks)
    assert [entry["pokemon"]["species_id"] for entry in capture_records(service.active_run)] == [506, 507]
    assert first in service.active_run.history and second in service.active_run.history


def test_correction_and_withdrawal_recompute_zone_and_counts_without_erasing_history(tmp_path):
    manager, initial, service = tracking(tmp_path, RULES, params={"catch_limit": {"per_zone": 1}})
    first = encounter(service, outcome="escaped").history[-1]
    second = encounter(service, species=506).history[-1]
    assert any(item.state == "violation" for item in nuzlocke(service))
    corrected = encounter(service, outcome="captured", zone="Route 2", corrects_event_id=first["event_id"], note="Autre zone").history[-1]
    assert not any(item.state == "violation" for item in nuzlocke(service))
    assert len(capture_records(service.active_run)) == 2
    service.record_rule_event(None, confirmed=True, corrects_event_id=corrected["event_id"], note="Déclaration en double")
    loaded = manager.load(initial.run_id)
    assert [entry["capture_id"] for entry in capture_records(loaded)] == [second["event_id"]]
    assert first in loaded.history and corrected in loaded.history
    assert loaded.captures is None  # No duplicate materialized list to get out of sync.


@pytest.mark.parametrize("kind", ["wild_special", "static", "gift", "egg", "scripted"])
def test_special_captures_have_separate_nuzlocke_convention_but_count_for_catch_limit(tmp_path, kind):
    _, _, service = tracking(tmp_path, RULES, params={"catch_limit": {"per_zone": 1}})
    encounter(service, kind=kind)
    encounter(service, species=506)
    actual = results(service.active_run)
    assert len(actual["nuzlocke"].checks) == 2
    assert all(item.state == "review" for item in actual["nuzlocke"].checks)
    assert "spéciale" in actual["nuzlocke"].checks[0].message
    assert len(actual["catch_limit"].checks) == 1
    assert "2 captures" in actual["catch_limit"].checks[0].message


def test_legacy_capture_and_encounter_order_is_shared_by_counters_and_species_checks(tmp_path):
    _, _, service = tracking(tmp_path, RULES, params={"catch_limit": {"per_zone": 1}})
    encounter(service, species=504)
    service.manual_capture(species_id=506, zone="Route 1")
    encounter(service, species=504, zone="Route 2")
    records = capture_records(service.active_run)
    assert [entry["pokemon"]["species_id"] for entry in records] == [504, 506, 504]
    actual = results(service.active_run)
    assert any(item.state == "review" and item.species_id == 506 and "type de rencontre" in item.message
               for item in actual["nuzlocke"].checks)
    assert actual["species_clause"].checks[-1].species_id == 504
    assert actual["catch_limit"].checks[0].species_id == 506


def test_legacy_capture_without_encounter_kind_keeps_first_encounter_unknown(tmp_path):
    _, _, service = tracking(tmp_path, RULES)
    service.manual_capture(species_id=504, zone="Route 1")
    encounter(service, species=506)
    assert nuzlocke(service)[0].state == "unknown"
    assert not any(item.state == "violation" for item in nuzlocke(service))


@pytest.mark.parametrize("zone", [None, "", {}, {"map_id": 12}, {"id": "one", "zone_id": "two"}])
def test_unknown_zone_is_not_treated_as_available_or_merged(tmp_path, zone):
    _, _, service = tracking(tmp_path, RULES)
    encounter(service, outcome="escaped", zone=zone)
    assert nuzlocke(service)[0].state == "unknown"
    encounter(service, species=506, zone="Route 1")
    assert not any(item.state == "violation" for item in nuzlocke(service))


def test_zone_identifiers_share_namespace_and_exact_manual_names_do_not(tmp_path):
    _, _, service = tracking(tmp_path, RULES)
    encounter(service, outcome="escaped", zone={"capture_zone_id": "route-1"})
    encounter(service, zone={"id": "route-1"})
    assert any(item.state == "violation" for item in nuzlocke(service))
    encounter(service, species=506, zone="route-1")
    assert not any(item.state == "violation" and item.species_id == 506 for item in nuzlocke(service))


@pytest.mark.parametrize("field,value", [("species_id", True), ("species_id", 0), ("species_id", 650),
    ("outcome", "won"), ("outcome", []), ("encounter_kind", "trainer"), ("encounter_kind", None)])
def test_invalid_details_are_rejected_before_write_and_again_on_load(tmp_path, field, value):
    _, _, service = tracking(tmp_path, RULES)
    run = encounter(service)
    before = run.to_dict()
    payload = deepcopy(run.history[-1]["payload"])
    payload["details"][field] = value
    with pytest.raises(ValueError):
        service.record_rule_event(**payload, confirmed=True)
    assert service.active_run.to_dict() == before
    before["history"][-1]["payload"] = payload
    with pytest.raises(ValueError):
        Run.from_dict(before)


@pytest.mark.parametrize("rules,kind", [(["catch_limit"], "wild_standard"), (RULES, "gift")])
def test_reroll_requires_species_clause_and_ordinary_wild_encounter(tmp_path, rules, kind):
    _, _, service = tracking(tmp_path, rules)
    with pytest.raises(ValueError, match="Species Clause"):
        encounter(service, outcome="duplicate_ignored", kind=kind)


def test_party_and_hp_changes_do_not_create_encounters(tmp_path):
    _, _, service = tracking(tmp_path, RULES)
    observe(service, [member()])
    observe(service, [member(hp=0), member(species=506, slot=2, pid=456)])
    assert capture_records(service.active_run) == []
    assert not nuzlocke(service)
