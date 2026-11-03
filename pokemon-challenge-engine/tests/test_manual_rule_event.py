"""Manual evidence is persisted, reversible and never presented as RAM detection."""
from copy import deepcopy

import pytest

from app.core.manual_rule_event import ACTIONS, EVENT_TYPE, active_declarations
from app.models.run import Run, history_event
from app.services.run_tracking_service import RunTrackingService
from test_rule_observation import member, observe, results, tracking


RULES = ["no_items", "no_healing", "no_pokemon_center"]


def declare(service, kind, **kwargs):
    return service.record_rule_event(kind, confirmed=True, **kwargs)


@pytest.mark.parametrize("kind", [kind for kind, action in ACTIONS.items() if set(action.rules).intersection(RULES)])
def test_action_applies_to_only_the_declared_rules_and_survives_resume(tmp_path, kind):
    manager, initial, service = tracking(tmp_path, RULES)
    snapshot = deepcopy(initial.rules_snapshot)
    run = declare(service, kind, note="Test manuel explicite")
    event = list(active_declarations(run.history).values())[0]
    assert event["source"] == "manual"
    assert run.rules_snapshot == snapshot
    for rule in RULES:
        checks = results(run)[rule].checks
        assert bool(checks) == (rule in ACTIONS[kind].rules)
        assert all(check.scope == "manual" and check.state == "violation" for check in checks)
        assert all("déclaré manuellement" in check.message for check in checks)
    service.close()
    reopened = RunTrackingService(manager)
    assert active_declarations(reopened.active_run.history) == {event["event_id"]: event}
    assert results(reopened.active_run) == results(run)
    assert reopened.active_run.rules_snapshot == snapshot
    reopened.close()


def test_correction_and_withdrawal_preserve_the_original_history(tmp_path):
    manager, initial, service = tracking(tmp_path, RULES)
    first = declare(service, "battle_healing_item").history[-1]
    second = declare(service, "pokemon_center", corrects_event_id=first["event_id"], note="Soin au Centre, pas une Potion").history[-1]
    run = service.active_run
    assert not results(run)["no_items"].checks and not results(run)["no_healing"].checks
    assert len(results(run)["no_pokemon_center"].checks) == 1
    third = declare(service, None, corrects_event_id=second["event_id"], note="Déclaration faite dans la mauvaise partie").history[-1]
    saved = manager.load(initial.run_id)
    assert [e for e in saved.history if e["type"] == EVENT_TYPE] == [first, second, third]
    assert not active_declarations(saved.history)
    assert not any(value.checks for value in results(saved).values())


@pytest.mark.parametrize("kwargs", [dict(confirmed=False), dict(confirmed=1), dict(confirmed="yes")])
def test_explicit_confirmation_is_required(tmp_path, kwargs):
    _, _, service = tracking(tmp_path, RULES)
    before = service.active_run.to_dict()
    with pytest.raises(ValueError, match="Confirmez"):
        service.record_rule_event("pokemon_center", **kwargs)
    assert service.active_run.to_dict() == before


@pytest.mark.parametrize("kind", [None, "pokeball", "held_item", "invented", True, []])
def test_unknown_allowed_or_unqualified_actions_are_not_violations(tmp_path, kind):
    _, _, service = tracking(tmp_path, RULES)
    before = service.active_run.to_dict()
    with pytest.raises(ValueError):
        declare(service, kind)
    assert service.active_run.to_dict() == before


def test_inactive_rule_and_foreign_or_stale_correction_are_rejected(tmp_path):
    _, _, service = tracking(tmp_path, ["no_healing"])
    with pytest.raises(ValueError, match="aucune règle active"):
        declare(service, "pokemon_center")
    first = declare(service, "healing_move").history[-1]
    with pytest.raises(ValueError, match="raison"):
        declare(service, None, corrects_event_id=first["event_id"])
    declare(service, None, corrects_event_id=first["event_id"], note="Erreur")
    before = service.active_run.to_dict()
    with pytest.raises(ValueError, match="déjà été corrigée"):
        declare(service, None, corrects_event_id=first["event_id"], note="Deuxième clic")
    with pytest.raises(ValueError, match="cette partie"):
        declare(service, None, corrects_event_id="foreign", note="Autre partie")
    assert service.active_run.to_dict() == before


def test_hp_and_zone_changes_never_generate_manual_action_evidence(tmp_path):
    _, _, service = tracking(tmp_path, RULES)
    observe(service, [member(hp=1)])
    service.observe([member(hp=30)], {"name": "Centre Pokémon"}, game_id="white", emulator_running=True)
    assert not active_declarations(service.active_run.history)
    assert not any(value.checks for value in results(service.active_run).values())


@pytest.mark.parametrize("mutation", ["automatic", "unknown_kind", "foreign", "double_correction", "missing_note", "missing_field"])
def test_untrusted_persistent_declarations_are_validated(tmp_path, mutation):
    _, _, service = tracking(tmp_path, RULES)
    first = declare(service, "healing_move").history[-1]
    data = service.active_run.to_dict()
    event = data["history"][-1]
    if mutation == "automatic":
        event["source"] = "automatic"
    elif mutation == "unknown_kind":
        event["payload"]["kind"] = "other"
    elif mutation == "foreign":
        event["payload"]["corrects_event_id"] = "missing"
    elif mutation == "missing_field":
        del event["payload"]["zone"]
    else:
        correction = history_event(EVENT_TYPE, "manual", {"kind": None, "note": "Correction",
            "zone": None, "corrects_event_id": first["event_id"]}, first["timestamp"])
        data["history"].append(correction)
        if mutation == "missing_note":
            correction["payload"]["note"] = ""
        else:
            data["history"].append(history_event(EVENT_TYPE, "manual", correction["payload"], first["timestamp"]))
    with pytest.raises(ValueError):
        Run.from_dict(data)


def test_read_only_evaluation_does_not_mutate_declarations(tmp_path):
    _, _, service = tracking(tmp_path, RULES)
    run = declare(service, "battle_healing_item")
    before = run.to_dict()
    results(run, include_history=True)
    assert run.to_dict() == before


@pytest.mark.parametrize("kind,rules", [
    ("unauthorized_battler", ["solo_run", "starter_only"]),
    ("non_shiny_battler", ["shiny_only"]),
    ("pokemon_evolved", ["no_evolution"]),
])
def test_declared_combat_and_evolution_violations_survive_reload(tmp_path, kind, rules):
    manager, initial, service = tracking(tmp_path, rules)
    declare(service, kind)
    loaded = manager.load(initial.run_id)
    for rule in rules:
        checks = results(loaded)[rule].checks
        assert len(checks) == 1
        assert checks[0].scope == "manual" and checks[0].state == "violation"
        assert "Aucune détection automatique" in checks[0].message
