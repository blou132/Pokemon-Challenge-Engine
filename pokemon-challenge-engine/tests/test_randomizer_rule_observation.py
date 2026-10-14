"""Synthetic derived-ROM evidence, never a played randomizer claim."""

from copy import deepcopy

import pytest

from app.core.rule_observation import RunPokemonData, evaluate_rules
from app.core.run_manager import RunManager
from app.models.challenge import Challenge
from app.services.run_tracking_service import RunTrackingService
from app.ui.widgets.rule_observation import rule_observation_text
from test_rule_observation import member, mono, observe
from test_run_randomizer_isolation import randomizer, transformation, environment, create, tree


def setup(tmp_path, monkeypatch, *, categories=("types", "evolutions"), rules=()):
    manager = RunManager(tmp_path / "runs")
    challenge = Challenge("white", "custom", ["randomizer", *rules], {},
        {"enforcement": "soft", "rule_parameters": {"level_cap": {"max_level": 20}},
         "rom_transformation": {"kind": "zx", "categories": list(categories), "balanced": False}}, mono(), 512)
    run = manager.create("Derived", "white", challenge=challenge, rom_fingerprint="a" * 64)
    data = {"source": "verified-derived-rom", "game_id": "white", "rom_sha256": run.rom_fingerprint,
            "categories": list(categories), "starters": [1, 4, 7],
            "pokemon": [{"species_id": species, "form": 0, "types": ["normal"],
                         "evolutions": [], "identity_evolutions": []} for species in range(1, 650)]}
    service = RunTrackingService(manager)
    service.activate(run.run_id)
    monkeypatch.setattr(service._transformation_provider, "for_run", lambda current: deepcopy(data))
    return manager, run, service, data


def checks(run, data, **kwargs):
    return {item.rule_id: item.checks for item in evaluate_rules(run, transformation=data, **kwargs)}


def edge(data, source, target, *, creation=False):
    row = data["pokemon"][source - 1]
    row["evolutions"].append(target)
    if not creation:
        row["identity_evolutions"].append(target)


def test_effective_types_stages_shiny_and_cap_survive_reload(tmp_path, monkeypatch, catalog):
    manager, run, service, data = setup(tmp_path, monkeypatch, rules=("monotype", "unevolved", "shiny_only", "level_cap"))
    data["pokemon"][500]["types"] = ["fire"]  # Oshawott is Water in vanilla.
    edge(data, 1, 501)
    observe(service, [member(species=501, pid=0, trainer=0, level=21)])
    service.flush(force=True)
    loaded = manager.load(run.run_id)
    before = loaded.to_dict()
    result = checks(loaded, data)
    assert result["monotype"][0].state == "compliant"
    assert result["unevolved"][0].state == "violation"
    assert result["shiny_only"][0].state == "compliant"
    assert result["level_cap"][0].state == "violation"
    assert result["randomizer"][0].state == "compliant"
    assert "ROM dérivée vérifiée" in rule_observation_text(loaded, catalog, transformation=data)
    assert checks(loaded, None)["monotype"][0].state == "unknown"
    assert loaded.to_dict() == before


@pytest.mark.parametrize("form", [None, 1, 31])
def test_missing_transformed_form_never_falls_back_to_base_or_vanilla(tmp_path, monkeypatch, form):
    _, _, service, data = setup(tmp_path, monkeypatch, rules=("monotype",))
    data["pokemon"][478]["types"] = ["fire"]
    observe(service, [member(species=479, form=form)])
    assert checks(service.active_run, data)["monotype"][0].state == "unknown"


def test_exact_extracted_alternate_form_is_used(tmp_path, monkeypatch):
    _, _, service, data = setup(tmp_path, monkeypatch, rules=("monotype",))
    data["pokemon"].append({"species_id": 479, "form": 2, "types": ["fire"],
                            "evolutions": [], "identity_evolutions": []})
    observe(service, [member(species=479, form=2)])
    assert checks(service.active_run, data)["monotype"][0].state == "compliant"


def test_vanilla_tables_only_when_verified_category_is_unchanged(tmp_path, monkeypatch):
    _, _, service, data = setup(tmp_path, monkeypatch, categories=("wild",), rules=("monotype", "unevolved"))
    observe(service, [member(species=498, form=None)])
    verified = checks(service.active_run, data)
    assert verified["monotype"][0].state == verified["unevolved"][0].state == "compliant"
    unverified = checks(service.active_run, None)
    assert unverified["monotype"][0].state == unverified["unevolved"][0].state == "unknown"


@pytest.mark.parametrize("change", ["game", "sha", "source", "categories", "missing_species", "invalid_type"])
def test_stale_or_mismatched_context_is_not_evidence(tmp_path, monkeypatch, change):
    _, _, service, data = setup(tmp_path, monkeypatch, rules=("monotype",))
    observe(service, [member()])
    if change == "game": data["game_id"] = "black"
    elif change == "sha": data["rom_sha256"] = "b" * 64
    elif change == "source": data["source"] = "declared"
    elif change == "categories": data["categories"] = ["wild"]
    elif change == "missing_species": data["pokemon"].pop()
    else: data["pokemon"][0]["types"] = ["fairy"]
    result = checks(service.active_run, data)
    assert result["monotype"][0].state == result["randomizer"][0].state == "unknown"


def test_randomized_forward_path_preserves_identity_and_no_evolution_history(tmp_path, monkeypatch):
    manager, run, service, data = setup(tmp_path, monkeypatch, rules=("no_evolution", "permanent_death"))
    edge(data, 498, 501)
    edge(data, 501, 503)
    observe(service, [member(species=498)])
    key = service.active_run.current_party[0]["pokemon_key"]
    observe(service, [member(species=503)])
    service.flush(force=True)
    stored = manager.load(run.run_id)
    assert stored.current_party[0]["pokemon_key"] == key
    assert stored.current_party[0]["identity_confidence"] == "strong"
    assert [item["form"] for item in stored.known_pokemon[key]["species_history"]] == [0, 0]
    assert checks(stored, data)["no_evolution"][0].state == "violation"


@pytest.mark.parametrize("case", ["backward", "siblings", "cycle", "creation", "clones"])
def test_randomized_graph_never_relaxes_identity_ambiguity_guards(tmp_path, monkeypatch, case):
    _, _, service, data = setup(tmp_path, monkeypatch, rules=("no_evolution", "permanent_death"))
    first, second = 498, 501
    if case == "backward": edge(data, second, first)
    elif case == "siblings":
        edge(data, 1, first)
        edge(data, 1, second)
    elif case == "cycle":
        edge(data, first, second)
        edge(data, second, first)
    else: edge(data, first, second, creation=case == "creation")
    observe(service, [member(species=first)])
    party = [member(species=second, hp=0)]
    if case == "clones": party.append(member(species=second, hp=0, slot=2))
    observe(service, party)
    current = service.active_run
    assert all(pokemon["pokemon_key"] is None for pokemon in current.current_party)
    assert not current.deaths
    assert not any(item.state == "violation" for item in checks(current, data)["no_evolution"])


def test_creation_counts_as_evolved_stage_but_not_individual_evolution(tmp_path, monkeypatch):
    _, run, _, data = setup(tmp_path, monkeypatch)
    edge(data, 290, 292, creation=True)
    lookup = RunPokemonData(run, data)
    assert lookup.unevolved(292) is False
    assert lookup.evolution(290, 292, 0, 0) is False


def test_missing_identity_graph_is_unknown_without_guessing_from_species_targets(tmp_path, monkeypatch):
    _, _, service, data = setup(tmp_path, monkeypatch, rules=("no_evolution",))
    edge(data, 498, 501)
    for row in data["pokemon"]: row.pop("identity_evolutions")
    observe(service, [member(species=498)])
    observe(service, [member(species=501)])
    current = service.active_run
    assert current.current_party[0]["pokemon_key"] is None
    assert not next(iter(current.known_pokemon.values())).get("identity_ambiguous")
    assert checks(current, data)["no_evolution"][0].state == "unknown"


def test_provider_error_is_explicit_recoverable_and_never_uses_vanilla_graph(tmp_path, monkeypatch):
    _, _, service, data = setup(tmp_path, monkeypatch, rules=("no_evolution",))
    edge(data, 498, 501)
    observe(service, [member(species=498)])
    def failed(run):
        raise ValueError("Manifeste modifié")
    monkeypatch.setattr(service._transformation_provider, "for_run", failed)
    observe(service, [member(species=501)])
    assert service.transformation_error == "Manifeste modifié"
    assert service.active_run.current_party[0]["identity_confidence"] == "weak"
    monkeypatch.setattr(service._transformation_provider, "for_run", lambda run: deepcopy(data))
    observe(service, [member(species=501)])
    assert service.transformation_error is None
    assert service.active_run.current_party[0]["identity_confidence"] == "strong"


def test_old_species_only_history_is_not_reinterpreted_as_proven_random_evolution(tmp_path, monkeypatch):
    _, _, service, data = setup(tmp_path, monkeypatch, rules=("no_evolution",))
    edge(data, 498, 501)
    observe(service, [member(species=498)])
    observe(service, [member(species=501)])
    old = service.active_run
    for pokemon in old.known_pokemon.values():
        for item in pokemon["species_history"]: item.pop("form")
    result = checks(old, data)["no_evolution"]
    assert result and all(item.state == "unknown" for item in result)


def test_real_copy_pipeline_provider_feeds_evaluation_without_rehashing_frames(randomizer, monkeypatch):
    # Only Java is simulated; isolation, manifests, hashes, provider and saves are real.
    from app.services import rom_transformation_service

    env, _ = randomizer
    original = tree(env.source)
    challenge = Challenge("white", "custom", ["randomizer", "monotype"], {},
        {"enforcement": "soft", "rule_parameters": {},
         "rom_transformation": {"kind": "zx", "categories": ["wild", "types"], "balanced": False}}, mono(), 512)
    isolated = env.service.isolate(create(env, challenge=challenge))
    service = RunTrackingService(env.manager)
    service.activate(isolated.run_id)
    service.observe([member(species=498)], game_id="white", game_code="IRAF", region="FR", revision=0, emulator_running=True)
    data = service._transformation_provider.for_run(service.active_run)
    assert data["game_id"] == "white"
    assert checks(service.active_run, data)["monotype"][0].state == "violation"  # Extracted Normal, vanilla Fire.
    def no_hash(*args):
        raise AssertionError("An unchanged next observation must use the provider signature cache")
    monkeypatch.setattr(rom_transformation_service, "file_hash", no_hash)
    service.observe([member(species=498, level=6)], game_id="white", game_code="IRAF", region="FR", revision=0, emulator_running=True)
    service.flush(force=True)
    stored = env.manager.load(isolated.run_id)
    assert checks(stored, data)["monotype"][0].state == "violation"
    assert tree(env.source) == original


@pytest.mark.parametrize("first_form,second_form", [(None, 0), (0, None), (1, 0), (0, 1)])
def test_effective_species_graph_does_not_assume_alternate_form_relationship(tmp_path, monkeypatch, first_form, second_form):
    _, run, _, data = setup(tmp_path, monkeypatch)
    edge(data, 498, 501)
    assert RunPokemonData(run, data).evolution(498, 501, first_form, second_form) is None
