"""Synthetic evidence tests, not a claim of a played shiny or battle event."""
from copy import deepcopy

import pytest

from app.core.rule_observation import CAPABILITIES, evaluate_rules, level_cap
from app.core.run_manager import RunManager
from app.core.shiny import shiny_status
from app.models.challenge import Challenge
from app.models.run import history_event
from app.services.run_tracking_service import RunTrackingService


def member(*, species=498, pid=123, trainer=456, slot=1, level=5, hp=20, form=0):
    return dict(species_id=species, personality_id=pid, original_trainer_id=trainer,
                slot=slot, level=level, hp=hp, max_hp=30, form=form)


def tracking(tmp_path, rules, *, params=None, monotype=None):
    manager = RunManager(tmp_path / "runs")
    challenge = Challenge("white", "custom", list(rules), {},
                          {"enforcement": "soft", "rule_parameters": params or {}}, monotype, 10)
    run = manager.create("Observed", "white", challenge=challenge)
    service = RunTrackingService(manager)
    service.activate(run.run_id)
    return manager, run, service


def observe(service, party):
    service.observe(party, game_id="white", emulator_running=True)


def results(run, **kwargs):
    return {item.rule_id: item for item in evaluate_rules(run, **kwargs)}


def mono(mode="soft", target="fire"):
    return dict(type_id=target, mode=mode, allowed_types=[target], allow_reroll=False, roll_index=0)


@pytest.mark.parametrize("xor,expected", [(0, True), (1, True), (7, True), (8, False), (65535, False)])
@pytest.mark.parametrize("trainer", [0, 0x1234ABCD, 0xFFFFFFFF])
def test_shiny_gen5_xor_boundary_and_ot(trainer, xor, expected):
    tid, sid = trainer & 65535, trainer >> 16
    pid = (0x9ABC << 16) | (0x9ABC ^ tid ^ sid ^ xor)
    assert shiny_status(member(pid=pid, trainer=trainer)) is expected


@pytest.mark.parametrize("value", [None, True, False, -1, 0x100000000, "123", 0.0])
@pytest.mark.parametrize("field", ["personality_id", "original_trainer_id"])
def test_missing_or_invalid_shiny_identity_stays_unknown(value, field):
    pokemon = member()
    pokemon[field] = value
    assert shiny_status(pokemon) is None


@pytest.mark.parametrize("generation", [4, 6, True, 5.0, None])
def test_shiny_formula_not_applied_to_other_generations(generation):
    assert shiny_status(member(), generation) is None


def test_all_catalog_rules_have_explicit_capability(catalog):
    assert set(CAPABILITIES) == set(catalog.rules)
    for capability in CAPABILITIES.values():
        assert capability.level in {"automatic", "partial", "unavailable", "configured"}
        assert capability.explanation


def test_three_simultaneous_team_rules_and_reload(tmp_path):
    manager, run, service = tracking(tmp_path, ["shiny_only", "monotype", "level_cap"],
        params={"level_cap": {"max_level": 20}}, monotype=mono())
    observe(service, [member(species=498, pid=0, trainer=0, level=20),
                      member(species=501, slot=2, level=21)])
    before = service.active_run.to_dict()
    actual = results(service.active_run)
    for rule in ("shiny_only", "monotype", "level_cap"):
        assert [check.state for check in actual[rule].checks] == ["compliant", "violation"]
    assert level_cap(service.active_run) == 20
    service.flush(force=True)
    assert results(manager.load(run.run_id)) == actual
    assert service.active_run.to_dict() == before  # Evaluation has no writes.


@pytest.mark.parametrize("mode,expected", [("soft", "compliant"), ("strict", "violation"), ("pure", "violation")])
def test_monotype_order_and_two_types(tmp_path, mode, expected):
    _, _, service = tracking(tmp_path, ["monotype"], monotype=mono(mode, "flying"))
    observe(service, [member(species=6)])  # Fire/Flying, ordered.
    assert results(service.active_run)["monotype"].checks[0].state == expected


def test_missing_form_unknown_then_observed_rotom_form(tmp_path):
    _, _, service = tracking(tmp_path, ["monotype"], monotype=mono(target="fire"))
    observe(service, [member(species=479, form=None)])
    assert results(service.active_run)["monotype"].checks[0].state == "unknown"
    observe(service, [member(species=479, form=1)])
    assert results(service.active_run)["monotype"].checks[0].state == "compliant"


@pytest.mark.parametrize("cap", [None, True, 0, 101, "20"])
def test_invalid_historical_cap_not_assumed_default(tmp_path, cap):
    _, _, service = tracking(tmp_path, ["level_cap"], params={"level_cap": {"max_level": cap}})
    observe(service, [member(level=100)])
    assert level_cap(service.active_run) is None
    assert results(service.active_run)["level_cap"].checks[0].state == "unknown"


@pytest.mark.parametrize("value", [20, [], None, "invalid"])
def test_legacy_rule_parameters_with_wrong_shape_remain_unknown(tmp_path, value):
    manager, run, service = tracking(tmp_path, ["level_cap", "catch_limit"],
                                    params={"level_cap": value, "catch_limit": value})
    observe(service, [member()])
    service.manual_capture(species_id=498, zone="Route 1")
    actual = results(manager.load(run.run_id))
    assert actual["level_cap"].checks[0].state == "unknown"
    assert actual["catch_limit"].checks[0].state == "unknown"


def test_randomizer_does_not_use_vanilla_types_or_stages(tmp_path):
    _, _, service = tracking(tmp_path, ["randomizer", "monotype", "unevolved"], monotype=mono())
    observe(service, [member(species=498)])
    actual = results(service.active_run)
    assert actual["monotype"].checks[0].state == "unknown"
    assert actual["unevolved"].checks[0].state == "unknown"
    assert actual["randomizer"].capability.level == "configured"
    assert actual["randomizer"].checks[0].state == "unknown"
    assert actual["randomizer"].checks[0].scope == "rom"


def test_known_pokemon_outside_team_still_evaluated(tmp_path):
    _, _, service = tracking(tmp_path, ["shiny_only"])
    observe(service, [member()])
    observe(service, [member(pid=0, trainer=0)])
    checks = results(service.active_run)["shiny_only"].checks
    assert [(check.scope, check.state) for check in checks] == [("party", "compliant"), ("known", "violation")]


def test_past_alerts_survive_party_change_save_and_reload(tmp_path):
    manager, run, service = tracking(tmp_path, ["level_cap"], params={"level_cap": {"max_level": 20}})
    observe(service, [member(level=25)])
    observe(service, [member(level=25, hp=19)])
    observe(service, [member(level=15)])
    service.flush(force=True)
    checks = results(manager.load(run.run_id), include_history=True)["level_cap"].checks
    assert [(check.scope, check.state) for check in checks] == [("party", "compliant"), ("history", "violation")]


def test_no_evolution_stable_identity_and_sourced_forward_path(tmp_path):
    manager, run, service = tracking(tmp_path, ["no_evolution", "unevolved"])
    observe(service, [member(species=498)])
    observe(service, [member(species=499)])
    service.flush(force=True)
    actual = results(manager.load(run.run_id))
    assert actual["no_evolution"].checks[0].state == "violation"
    assert actual["unevolved"].checks[0].state == "violation"


@pytest.mark.parametrize("first,second", [(499, 498), (134, 135), (290, 292), (498, 501)])
def test_ambiguous_change_never_proves_evolution(tmp_path, first, second):
    _, _, service = tracking(tmp_path, ["no_evolution"])
    observe(service, [member(species=first)])
    observe(service, [member(species=second)])
    assert not results(service.active_run)["no_evolution"].checks


def test_party_addition_heal_and_center_do_not_invent_actions(tmp_path):
    rules = ["nuzlocke", "no_items", "no_healing", "no_pokemon_center", "starter_only", "catch_limit"]
    _, _, service = tracking(tmp_path, rules)
    observe(service, [member(hp=1)])
    service.observe([member(hp=30), member(species=501, pid=9, slot=2)], zone="Centre Pokémon",
                    game_id="white", emulator_running=True)
    actual = results(service.active_run, include_history=True)
    assert service.active_run.captures is None
    assert all(not value.checks for value in actual.values())


def test_manual_capture_limits_and_species_clause_are_explicit(tmp_path):
    _, _, service = tracking(tmp_path, ["nuzlocke", "species_clause", "catch_limit"],
                             params={"catch_limit": {"per_zone": 2}})
    for species in (498, 501, 498):
        service.manual_capture(species_id=species, zone="Route 1")
    actual = results(service.active_run)
    assert len(actual["nuzlocke"].checks) == 2
    assert len(actual["catch_limit"].checks) == 1
    assert len(actual["species_clause"].checks) == 1
    assert all(check.scope == "manual" and check.state == "review" for result in actual.values() for check in result.checks)


def test_unknown_zones_not_merged_or_deduced_from_party(tmp_path):
    _, _, service = tracking(tmp_path, ["catch_limit"], params={"catch_limit": {"per_zone": 1}})
    service.manual_capture(species_id=498)
    service.manual_capture(species_id=501)
    assert all(check.state == "unknown" for check in results(service.active_run)["catch_limit"].checks)


def test_solo_multiple_party_members_is_review_not_proven_battle_violation(tmp_path):
    _, _, service = tracking(tmp_path, ["solo_run"])
    observe(service, [member(), member(pid=8, slot=2)])
    check = results(service.active_run)["solo_run"].checks[0]
    assert check.state == "review" and check.scope == "party"
    assert "combat" in check.message


def test_standalone_permanent_death_records_and_corrects(tmp_path):
    manager, run, service = tracking(tmp_path, ["permanent_death"])
    observe(service, [member(hp=20)])
    observe(service, [member(hp=0)])
    service.flush(force=True)
    stored = manager.load(run.run_id)
    assert len(stored.deaths) == 1
    assert stored.deaths[0]["source"] == "automatic"
    assert results(stored)["permanent_death"].checks[0].state == "violation"
    # A later death does not retroactively turn earlier team observations into violations.
    assert all(check.scope != "history" for check in results(stored, include_history=True)["permanent_death"].checks)
    service.correct_death(stored.deaths[0]["death_id"], confirmed=True)
    assert not results(service.active_run)["permanent_death"].checks


def test_empty_party_is_not_global_compliance(tmp_path):
    _, _, service = tracking(tmp_path, ["shiny_only", "level_cap"])
    assert all(not item.checks for item in evaluate_rules(service.active_run))


@pytest.mark.parametrize("party", [None, "unavailable", [None], ["pokemon"], {},
                                 [{"pokemon_key": []}], [{"species_id": []}]])
def test_opaque_legacy_history_does_not_crash_or_prove_compliance(tmp_path, party):
    manager, run, service = tracking(tmp_path, ["shiny_only"])
    historical = service.active_run
    historical.history.append(history_event("party_changed", "automatic", {"party": party}))
    manager.save(historical)
    checks = results(manager.load(run.run_id), include_history=True)["shiny_only"].checks
    assert len(checks) == 1 and checks[0].state == "unknown"


def test_dead_member_absent_from_team_is_not_presence_violation(tmp_path):
    _, _, service = tracking(tmp_path, ["permanent_death"])
    observe(service, [member(hp=20)])
    observe(service, [member(hp=0)])
    observe(service, [member(pid=9)])
    assert not results(service.active_run)["permanent_death"].checks


def test_evaluation_never_mutates_snapshot_or_observations(tmp_path):
    _, _, service = tracking(tmp_path, list(CAPABILITIES), monotype=mono())
    observe(service, [member()])
    original = deepcopy(service.active_run.to_dict())
    evaluate_rules(service.active_run, include_history=True)
    assert service.active_run.to_dict() == original
