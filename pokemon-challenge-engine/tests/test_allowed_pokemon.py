"""Manual designations over synthetic observations, never proof of starter origin/combat."""

from copy import deepcopy

import pytest

from app.core.allowed_pokemon import DESIGNATION_EVENT, eligible_individuals, latest_designation
from app.core.pokemon_identity import pokemon_identity
from app.core import run_manager as storage
from app.models.run import Run, history_event
from app.services.run_tracking_service import RunTrackingService
from test_rule_observation import member, observe, results, tracking
from test_randomizer_rule_observation import setup as randomizer_setup, edge


def designate(service, key=None, *, remove=False, note=""):
    run = service.active_run
    previous = latest_designation(run)
    return service.designate_allowed_pokemon(
        None if remove else key or run.current_party[0]["pokemon_key"], note,
        previous_event_id=previous["event_id"] if previous else None, confirmed=True)


@pytest.mark.parametrize("species", [495, 498, 501])
def test_starter_species_never_assigns_an_individual_automatically(tmp_path, species):
    _, _, service = tracking(tmp_path, ["starter_only", "solo_run"])
    observe(service, [member(species=species)])
    assert latest_designation(service.active_run) is None
    assert results(service.active_run)["starter_only"].checks == ()


def test_selection_is_manual_replayable_and_does_not_change_snapshot(tmp_path):
    manager, run, service = tracking(tmp_path, ["starter_only", "solo_run"])
    snapshot = deepcopy(run.rules_snapshot)
    old_fields = set(run.to_dict())
    observe(service, [member(species=19)])  # Explicit declaration, not a vanilla species classifier.
    selected = designate(service)
    event = latest_designation(selected)
    assert event["source"] == "manual" and event["payload"]["purpose"] == "starter"
    assert selected.rules_snapshot == snapshot and set(selected.to_dict()) == old_fields
    assert all(check.state in {"review", "unknown"}
               for result in results(selected).values() for check in result.checks)
    assert "Origine starter déclarée, non prouvée" in results(selected)["starter_only"].checks[0].message
    service.close()
    reopened = RunTrackingService(manager)
    assert latest_designation(reopened.active_run) == event
    assert reopened.active_run.rules_snapshot == snapshot
    assert results(reopened.active_run) == results(selected)
    reopened.close()


def test_same_species_with_different_identity_never_replaces_selected_individual(tmp_path):
    _, _, service = tracking(tmp_path, ["starter_only", "solo_run"])
    observe(service, [member()])
    selected = latest_designation(designate(service))
    observe(service, [member(pid=999)])
    assert latest_designation(service.active_run) == selected
    checks = results(service.active_run)["starter_only"].checks
    assert checks[0].state == "unknown" and "n'est pas identifié" in checks[0].message
    assert checks[1].state == "review" and "Autre individu" in checks[1].message
    assert all(check.state not in {"compliant", "violation"} for check in checks)


def test_correction_removal_and_reselection_append_auditable_chain(tmp_path):
    manager, run, service = tracking(tmp_path, ["solo_run"])
    observe(service, [member(), member(pid=999, slot=2)])
    first = deepcopy(latest_designation(designate(service)))
    second_key = service.active_run.current_party[1]["pokemon_key"]
    second = deepcopy(latest_designation(designate(service, second_key, note="Correction explicite")))
    removed = deepcopy(latest_designation(designate(service, remove=True, note="Retrait")))
    assert removed["payload"]["pokemon_key"] is None and removed["payload"]["pokemon"] is None
    assert any("retirée" in check.message for check in results(service.active_run)["solo_run"].checks)
    fourth = latest_designation(designate(service, second_key))
    events = [event for event in manager.load(run.run_id).history if event["type"] == DESIGNATION_EVENT]
    assert events == [first, second, removed, fourth]
    assert [event["payload"]["previous_event_id"] for event in events] == [None, first["event_id"], second["event_id"], removed["event_id"]]


def test_confirmation_and_stale_form_guards(tmp_path):
    _, _, service = tracking(tmp_path, ["solo_run"])
    observe(service, [member()])
    key = service.active_run.current_party[0]["pokemon_key"]
    before = service.active_run.to_dict()
    with pytest.raises(ValueError, match="Confirmez"):
        service.designate_allowed_pokemon(key)
    assert service.active_run.to_dict() == before
    designate(service)
    with pytest.raises(ValueError, match="a changé"):
        service.designate_allowed_pokemon(key, confirmed=True)


@pytest.mark.parametrize("party", [[member(pid=None)], [member(), member(slot=2)]])
def test_weak_identity_or_clones_cannot_be_designated(tmp_path, party):
    _, _, service = tracking(tmp_path, ["starter_only", "solo_run"])
    observe(service, party)
    assert not eligible_individuals(service.active_run)
    with pytest.raises(ValueError, match="identité fiable"):
        service.designate_allowed_pokemon(pokemon_identity(member()), confirmed=True)
    assert latest_designation(service.active_run) is None


def test_previous_clone_suspends_comparison_even_after_one_leaves(tmp_path):
    _, _, service = tracking(tmp_path, ["starter_only", "solo_run"])
    observe(service, [member()])
    event = latest_designation(designate(service))
    observe(service, [member(), member(slot=2)])
    observe(service, [member()])
    assert not eligible_individuals(service.active_run)
    assert latest_designation(service.active_run) == event
    assert {check.state for check in results(service.active_run)["starter_only"].checks} == {"unknown"}


@pytest.mark.parametrize("field", ["species_id", "form", "species_history"])
def test_inconsistent_older_strong_record_is_not_offered_as_verified_individual(tmp_path, field):
    _, _, service = tracking(tmp_path, ["solo_run"])
    observe(service, [member()])
    run = service.active_run
    known = next(iter(run.known_pokemon.values()))
    if field == "species_history":
        known[field][-1]["species_id"] = 501
    else:
        known[field] = 501 if field == "species_id" else 1
    # The existing run format accepts these legacy inconsistencies. A strong
    # label alone must not authorize a new individual designation.
    loaded = Run.from_dict(run.to_dict())
    assert not eligible_individuals(loaded)


def test_forward_evolution_and_slot_change_preserve_explicit_designation(tmp_path):
    _, _, service = tracking(tmp_path, ["starter_only", "solo_run"])
    observe(service, [member(species=498)])
    event = deepcopy(latest_designation(designate(service)))
    observe(service, [member(species=500, slot=3)])
    checks = results(service.active_run)["starter_only"].checks
    assert checks[0].state == "review" and checks[0].species_id == 500
    assert "désigné manuellement présent" in checks[0].message
    assert latest_designation(service.active_run) == event
    assert event["payload"]["pokemon"]["species_id"] == 498


@pytest.mark.parametrize("first,second", [(500, 498), (134, 135), (290, 292)])
def test_backward_sibling_or_creation_change_does_not_claim_continuity(tmp_path, first, second):
    _, _, service = tracking(tmp_path, ["starter_only", "solo_run"])
    observe(service, [member(species=first)])
    designate(service)
    observe(service, [member(species=second)])
    assert {check.state for check in results(service.active_run)["starter_only"].checks} == {"unknown"}


def test_randomized_evolution_requires_verified_individual_graph(tmp_path, monkeypatch):
    _, _, service, data = randomizer_setup(tmp_path, monkeypatch, rules=("starter_only", "solo_run"))
    edge(data, 498, 19)
    observe(service, [member(species=498)])
    designate(service)
    observe(service, [member(species=19)])
    known = results(service.active_run, transformation=data)["starter_only"].checks
    assert known[0].state == "review" and "désigné manuellement présent" in known[0].message
    unknown = results(service.active_run)["starter_only"].checks
    assert unknown[0].state == "unknown" and "graphe" in unknown[0].message
    monkeypatch.setattr(service._transformation_provider, "for_run", lambda run: None)
    observe(service, [member(species=20)])
    assert not eligible_individuals(service.active_run)


def test_removed_designation_and_empty_party_never_produce_battle_violation(tmp_path):
    _, _, service = tracking(tmp_path, ["starter_only", "solo_run"])
    observe(service, [member()])
    designate(service)
    observe(service, [])
    assert {check.state for check in results(service.active_run)["starter_only"].checks} == {"unknown"}
    designate(service, remove=True)
    assert {check.state for check in results(service.active_run)["starter_only"].checks} == {"unknown"}


def test_old_run_without_designation_roundtrips_unchanged(tmp_path):
    _, run, _ = tracking(tmp_path, ["solo_run"])
    old = run.to_dict()
    assert Run.from_dict(old).to_dict() == old
    assert latest_designation(Run.from_dict(old)) is None


@pytest.mark.parametrize("change", ["source", "purpose", "predecessor", "key", "weak", "extra"])
def test_malformed_designations_are_rejected_on_loading(tmp_path, change):
    _, _, service = tracking(tmp_path, ["solo_run"])
    observe(service, [member()])
    data = designate(service).to_dict()
    event = data["history"][-1]
    if change == "source": event["source"] = "automatic"
    elif change == "purpose": event["payload"]["purpose"] = "starter"
    elif change == "predecessor": event["payload"]["previous_event_id"] = event["event_id"]
    elif change == "key": event["payload"]["pokemon_key"] = "gen5:wrong"
    elif change == "weak": event["payload"]["pokemon"]["identity_confidence"] = "weak"
    else: event["payload"]["extra"] = True
    with pytest.raises(ValueError):
        Run.from_dict(data)


def test_designation_survives_long_history_without_trimming(tmp_path):
    manager, run, service = tracking(tmp_path, ["solo_run"])
    observe(service, [member()])
    event = deepcopy(latest_designation(designate(service)))
    loaded = manager.load(run.run_id)
    loaded.history.extend(history_event("note_added", "manual", {"text": "Après la désignation"}, event["timestamp"])
                          for _ in range(1500))
    manager.save(loaded)
    replayed = manager.load(run.run_id)
    assert latest_designation(replayed) == event
    assert len(replayed.history) == len(loaded.history)


def test_storage_limit_keeps_previously_saved_designation_and_exposes_failure(tmp_path, monkeypatch):
    manager, run, service = tracking(tmp_path, ["solo_run"])
    observe(service, [member()])
    event = latest_designation(designate(service))
    path = manager.root / run.run_id / "run.json"
    before = path.read_bytes()
    monkeypatch.setattr(storage, "MAX_RUN_BYTES", len(before) + 8)
    with pytest.raises(ValueError, match="limite de stockage"):
        service.add_note("x" * 1000)
    assert path.read_bytes() == before
    assert service.dirty and service.last_error
    assert latest_designation(manager.load(run.run_id)) == event


def test_individual_from_another_run_is_not_available_for_selection(tmp_path):
    manager, first, service = tracking(tmp_path, ["solo_run"])
    observe(service, [member()])
    key = service.active_run.current_party[0]["pokemon_key"]
    second = manager.create("Autre", "white", challenge=first.rules_snapshot)
    service.activate(second.run_id)
    with pytest.raises(ValueError, match="identité fiable"):
        service.designate_allowed_pokemon(key, confirmed=True)
    assert latest_designation(manager.load(first.run_id)) is None
    assert latest_designation(service.active_run) is None
