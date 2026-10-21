"""Pure evidence reuse plus artifact invalidation, never emulator gameplay."""

from copy import copy, deepcopy
from dataclasses import FrozenInstanceError

import pytest

from app.core.rule_observation import CAPABILITIES, RunPokemonData, evaluate_rules
from app.core.transformation_snapshot import TransformationSnapshot
from test_randomizer_rule_observation import setup, edge
from test_rule_observation import member, observe
from test_run_randomizer_isolation import randomizer, environment, create, transformation, challenge


def test_snapshot_is_detached_and_copies_share_only_immutable_evidence(tmp_path, monkeypatch):
    _, run, _, data = setup(tmp_path, monkeypatch)
    edge(data, 498, 501)
    snapshot = TransformationSnapshot(data)
    data["pokemon"][497]["types"][0] = "water"
    data["pokemon"][497]["identity_evolutions"].clear()
    data["categories"].clear()
    assert snapshot["pokemon"][497]["types"] == ("normal",)
    assert copy(snapshot) is deepcopy(snapshot) is snapshot
    lookup = RunPokemonData(run, snapshot)
    assert lookup.evolution(498, 501, 0, 0) is True
    with pytest.raises(TypeError):
        snapshot["game_id"] = "black"
    with pytest.raises(TypeError):
        snapshot["pokemon"][497]["types"] = ["water"]
    with pytest.raises(TypeError):
        snapshot["pokemon"][497]["types"][0] = "water"
    with pytest.raises(FrozenInstanceError):
        snapshot.tables = None
    with pytest.raises(TypeError):
        lookup.rows[498, 0] = ("water",)
    with pytest.raises(TypeError):
        lookup.identity_graph[498] = frozenset()
    assert RunPokemonData(run, snapshot).evolution(498, 501, 0, 0) is True


def test_cached_graph_is_reused_but_still_bound_to_the_current_run(tmp_path, monkeypatch):
    _, run, _, data = setup(tmp_path, monkeypatch)
    snapshot = TransformationSnapshot(data)
    first = RunPokemonData(run, snapshot)
    def repeated_validation(*args, **kwargs):
        raise AssertionError("An immutable complete snapshot must not rebuild its tables")
    monkeypatch.setattr("app.core.rule_observation.pokemon_tables", repeated_validation)
    second = RunPokemonData(deepcopy(run), deepcopy(snapshot))
    assert first.rows is second.rows
    assert first.parents is second.parents
    assert first.identity_graph is second.identity_graph
    for change in ("sha", "game", "categories", "generation", "inactive"):
        other = deepcopy(run)
        if change == "sha": other.rom_fingerprint = "b" * 64
        elif change == "game": other.game_id = "black"
        elif change == "categories": other.rules_snapshot["settings"]["rom_transformation"]["categories"] = ["wild"]
        elif change == "generation": other.generation = 4
        else: other.rules_snapshot["active_rules"].remove("randomizer")
        assert not RunPokemonData(other, snapshot).verified


@pytest.mark.parametrize("change", ["valid", "source", "game", "sha", "categories", "missing_species", "invalid_type",
                                   "duplicate_form", "invalid_edge", "missing_identity_graph", "creation", "cycle", "alternate_form"])
def test_frozen_and_legacy_evidence_have_identical_rule_results(tmp_path, monkeypatch, change):
    _, _, service, data = setup(tmp_path, monkeypatch,
        rules=tuple(rule for rule in CAPABILITIES if rule != "randomizer"),
        params={"catch_limit": {"per_zone": 1}})
    edge(data, 498, 501)
    observe(service, [member(species=498)])
    observe(service, [member(species=501, hp=0, level=21)])
    if change == "source": data["source"] = "declared"
    elif change == "game": data["game_id"] = "black"
    elif change == "sha": data["rom_sha256"] = "b" * 64
    elif change == "categories": data["categories"] = ["wild"]
    elif change == "missing_species": data["pokemon"].pop()
    elif change == "invalid_type": data["pokemon"][497]["types"] = ["fairy"]
    elif change == "duplicate_form": data["pokemon"].append(deepcopy(data["pokemon"][0]))
    elif change == "invalid_edge": data["pokemon"][497]["evolutions"] = [650]
    elif change == "missing_identity_graph": data["pokemon"][497].pop("identity_evolutions")
    elif change == "creation": data["pokemon"][497]["identity_evolutions"] = []
    elif change == "cycle": edge(data, 501, 498)
    elif change == "alternate_form":
        alternate = deepcopy(data["pokemon"][497])
        alternate["form"], alternate["types"] = 1, ["fire"]
        data["pokemon"].append(alternate)
    run = service.active_run
    before = run.to_dict()
    assert evaluate_rules(run, transformation=TransformationSnapshot(data), include_history=True) == evaluate_rules(
        run, transformation=data, include_history=True)
    assert run.to_dict() == before


def test_mutable_legacy_evidence_is_revalidated_after_an_edit(tmp_path, monkeypatch):
    _, run, _, data = setup(tmp_path, monkeypatch)
    assert RunPokemonData(run, data).verified
    data["pokemon"].pop()
    assert not RunPokemonData(run, data).verified


@pytest.mark.parametrize("artifact", ["report.json", "manifest.json", "PceRandomizer.java"])
def test_provider_reuses_snapshot_until_an_artifact_changes(randomizer, artifact):
    from app.services.run_transformation_provider import RunTransformationProvider
    env, _ = randomizer
    run = env.service.isolate(create(env, challenge=challenge()))
    provider = RunTransformationProvider(env.manager.root)
    first = provider.for_run(run)
    assert isinstance(first, TransformationSnapshot)
    assert provider.for_run(deepcopy(run)) is first
    target = env.manager.root / run.run_id / "play" / "transformation" / artifact
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError):
        provider.for_run(run)


def test_replacement_snapshot_does_not_reuse_previous_types_or_graph(tmp_path, monkeypatch):
    _, run, _, data = setup(tmp_path, monkeypatch)
    previous = RunPokemonData(run, TransformationSnapshot(data))
    data["pokemon"][497]["types"] = ["fire"]
    edge(data, 498, 501)
    current = RunPokemonData(run, TransformationSnapshot(data))
    assert previous.types(498, 0) == ("normal",)
    assert current.types(498, 0) == ("fire",)
    assert previous.evolution(498, 501, 0, 0) is False
    assert current.evolution(498, 501, 0, 0) is True
