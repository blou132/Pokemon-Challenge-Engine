"""Optional form survives run persistence; malformed imports never become evidence."""

from copy import deepcopy

import pytest

from app.models.run import Run
from test_run_tracking import observe, pokemon, setup_run


@pytest.mark.parametrize("form", [None, 0, 1, 31])
def test_optional_form_persists_across_run_reload(setup_run, form):
    manager, run, service, _ = setup_run
    observe(service, [pokemon() | {"form": form}])
    service.flush(force=True)
    stored = manager.load(run.run_id)
    assert stored.current_party[0]["form"] == form
    assert next(iter(stored.known_pokemon.values()))["form"] == form
    assert Run.from_dict(stored.to_dict()).current_party[0]["form"] == form


def test_old_run_without_form_keeps_unknown_form(setup_run):
    manager, run, service, _ = setup_run
    observe(service)
    service.flush(force=True)
    restored = Run.from_dict(manager.load(run.run_id).to_dict())
    assert "form" not in restored.current_party[0]
    assert "form" not in next(iter(restored.known_pokemon.values()))


@pytest.mark.parametrize("form", [-1, 32, True, False, 1.0, "0", {}, []])
def test_invalid_form_in_observation_preserves_last_valid_team(setup_run, form):
    _, _, service, _ = setup_run
    observe(service, [pokemon() | {"form": 1}])
    before = deepcopy(service.active_run.current_party)
    with pytest.raises(ValueError, match="[Ff]orme"):
        observe(service, [pokemon() | {"form": form}])
    assert service.active_run.current_party == before
    assert not service.session_active


@pytest.mark.parametrize("form", [-1, 32, True, False, 1.0, "0", {}, []])
@pytest.mark.parametrize("container", ["current_party", "known_pokemon", "captures"])
def test_invalid_form_in_serialized_run_is_rejected_without_rewriting(setup_run, form, container):
    manager, run, service, _ = setup_run
    observe(service, [pokemon() | {"form": 1}])
    service.manual_capture(pokemon=pokemon() | {"form": 1})
    stored = manager.load(run.run_id)
    raw = stored.to_dict()
    if container == "current_party":
        raw[container][0]["form"] = form
    elif container == "known_pokemon":
        next(iter(raw[container].values()))["form"] = form
    else:
        raw[container][0]["pokemon"]["form"] = form
    with pytest.raises(ValueError, match="[Ff]orme"):
        Run.from_dict(raw)
    assert manager.load(run.run_id) == stored


def test_form_change_keeps_individual_identity_without_inventing_evolution(setup_run):
    manager, run, service, _ = setup_run
    observe(service, [pokemon(species=479) | {"form": 0}])
    key = service.active_run.current_party[0]["pokemon_key"]
    observe(service, [pokemon(species=479) | {"form": 2}])
    service.flush(force=True)
    stored = manager.load(run.run_id)
    assert stored.current_party[0]["pokemon_key"] == key
    assert stored.current_party[0]["form"] == 2
    assert len(stored.known_pokemon) == 1
    assert len(stored.known_pokemon[key]["species_history"]) == 1
    assert not stored.deaths
