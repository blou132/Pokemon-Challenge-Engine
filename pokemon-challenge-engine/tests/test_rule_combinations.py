"""Synthetic combined-rule evidence; no encounter, battle or ROM-write claims."""

from copy import deepcopy

import pytest

from app.core.allowed_pokemon import latest_designation
from app.core.rule_observation import CAPABILITIES, evaluate_rules
from app.services.run_tracking_service import RunTrackingService
from test_allowed_pokemon import designate
from test_randomizer_rule_observation import setup, edge, checks
from test_rule_observation import member, observe, results, tracking


@pytest.mark.parametrize("initial_form", [None, 1])
def test_observed_base_form_before_random_evolution_is_preserved(tmp_path, monkeypatch, initial_form):
    manager, run, service, data = setup(tmp_path, monkeypatch,
        rules=("no_evolution", "unevolved", "permanent_death", "solo_run", "starter_only"))
    edge(data, 412, 19)
    observe(service, [member(species=412, form=initial_form)])
    declaration = deepcopy(latest_designation(designate(service)))
    original_snapshot = deepcopy(service.active_run.rules_snapshot)
    key = service.active_run.current_party[0]["pokemon_key"]
    observe(service, [member(species=412, form=0)])
    assert not checks(service.active_run, data)["no_evolution"]  # Form change is not evolution.
    observe(service, [member(species=19, form=0, hp=0)])
    service.flush(force=True)
    loaded = manager.load(run.run_id)
    assert loaded.current_party[0]["pokemon_key"] == key
    assert [entry.get("form") for entry in loaded.known_pokemon[key]["species_history"]] == [initial_form, 0, 0]
    actual = checks(loaded, data)
    assert [item.state for item in actual["no_evolution"]] == ["violation"]
    assert actual["unevolved"][0].state == "violation"
    assert actual["permanent_death"][0].state == "violation"
    for rule in ("solo_run", "starter_only"):
        assert any(item.state == "review" and "désigné manuellement présent" in item.message for item in actual[rule])
        assert not any(item.state == "violation" for item in actual[rule])
    assert latest_designation(loaded) == declaration
    assert loaded.rules_snapshot == original_snapshot


def test_name_only_capture_has_unknown_species_clause_without_name_guessing(tmp_path):
    manager, run, service = tracking(tmp_path, ["nuzlocke", "species_clause", "catch_limit"],
                                   params={"catch_limit": {"per_zone": 2}})
    service.manual_capture(pokemon="Ratentif", zone="Route 1")
    service.manual_capture(pokemon="Ratentif", zone="Route 1")
    actual = results(manager.load(run.run_id))
    assert [item.state for item in actual["species_clause"].checks] == ["unknown", "unknown"]
    assert [item.state for item in actual["nuzlocke"].checks] == ["review"]
    assert not actual["catch_limit"].checks


def test_legacy_history_without_form_is_preserved_when_new_evidence_arrives(tmp_path, monkeypatch):
    manager, run, service, data = setup(tmp_path, monkeypatch, rules=("no_evolution",))
    edge(data, 412, 19)
    observe(service, [member(species=412, form=None)])
    key = service.active_run.current_party[0]["pokemon_key"]
    service.close()
    legacy = manager.load(run.run_id)
    legacy.known_pokemon[key]["species_history"][0].pop("form")
    manager.save(legacy)
    original_entry = deepcopy(legacy.known_pokemon[key]["species_history"][0])
    reopened = RunTrackingService(manager)
    monkeypatch.setattr(reopened._transformation_provider, "for_run", lambda current: deepcopy(data))
    observe(reopened, [member(species=412, form=0)])
    observe(reopened, [member(species=19, form=0)])
    reopened.flush(force=True)
    loaded = manager.load(run.run_id)
    history = loaded.known_pokemon[key]["species_history"]
    assert history[0] == original_entry and "form" not in history[0]
    assert [entry.get("form") for entry in history] == [None, 0, 0]
    assert [item.state for item in checks(loaded, data)["no_evolution"]] == ["violation"]
    reopened.close()


@pytest.mark.parametrize("gap", ["missing", "weak", "duplicate", "opaque", "before_only", "other_individual", "missing_graph"])
def test_designation_requires_a_reliable_form_bridge_after_its_declaration(tmp_path, monkeypatch, gap):
    manager, run, service, data = setup(tmp_path, monkeypatch, rules=("starter_only", "solo_run"))
    edge(data, 412, 19)
    if gap == "before_only":
        observe(service, [member(species=412, form=0)])
    observe(service, [member(species=412, form=None)])
    declaration = deepcopy(latest_designation(designate(service)))
    observe(service, [member(species=412, form=0)])
    bridge = deepcopy(service.active_run.history[-1])
    observe(service, [member(species=19)])
    service.flush(force=True)
    loaded = manager.load(run.run_id)
    event = next(item for item in loaded.history if item["event_id"] == bridge["event_id"])
    if gap in ("missing", "before_only"):
        loaded.history.remove(event)
    elif gap == "weak":
        event["payload"]["party"][0].update(pokemon_key=None, identity_confidence="weak")
    elif gap == "duplicate":
        event["payload"]["party"].append(deepcopy(event["payload"]["party"][0]) | {"slot": 2})
    elif gap == "opaque":
        event["payload"]["party"] = "unavailable"
    elif gap == "other_individual":
        event["payload"]["party"][0].update(personality_id=9, pokemon_key="gen5:00000009:000001c8")
    manager.save(loaded)
    loaded = manager.load(run.run_id)
    before = deepcopy(loaded.to_dict())
    actual = checks(loaded, None if gap == "missing_graph" else data)
    assert all(item.state == "unknown" for item in actual["starter_only"])
    assert latest_designation(loaded) == declaration
    assert loaded.to_dict() == before


def test_all_fifteen_rules_remain_independent_with_effective_types_and_evolutions(tmp_path, monkeypatch):
    manager, run, service, data = setup(tmp_path, monkeypatch,
        rules=tuple(rule for rule in CAPABILITIES if rule != "randomizer"),
        params={"catch_limit": {"per_zone": 2}})
    edge(data, 412, 19)
    data["pokemon"][18]["types"] = ["fire"]
    observe(service, [member(species=412, pid=0, trainer=0)])
    designate(service)
    observe(service, [member(species=19, pid=0, trainer=0, level=21, hp=0)])
    for species in (412, 19, 19):
        service.manual_capture(species_id=species, zone={"capture_zone_id": "route-1"})
    service.observe([member(species=19, pid=0, trainer=0, level=21, hp=30)], zone="Centre Pokémon",
                    game_id="white", emulator_running=True)
    service.flush(force=True)
    loaded = manager.load(run.run_id)
    before = deepcopy(loaded.to_dict())
    actual = {item.rule_id: item for item in evaluate_rules(loaded, transformation=data, include_history=True)}
    assert set(actual) == set(CAPABILITIES)
    for rule in ("randomizer", "monotype", "shiny_only"):
        assert actual[rule].checks[0].state == "compliant"
    for rule in ("no_evolution", "unevolved", "level_cap", "permanent_death"):
        assert any(item.state == "violation" for item in actual[rule].checks)
    for rule, count in (("nuzlocke", 2), ("catch_limit", 1), ("species_clause", 1)):
        assert len(actual[rule].checks) == count
        assert all(item.scope == "manual" and item.state == "review" for item in actual[rule].checks)
    for rule in ("no_items", "no_healing", "no_pokemon_center"):
        assert actual[rule].capability.level == "unavailable"
        assert not actual[rule].checks
    for rule in ("solo_run", "starter_only"):
        assert any(item.state == "review" for item in actual[rule].checks)
        assert all(item.state in ("review", "unknown") for item in actual[rule].checks)
    assert loaded.to_dict() == before
