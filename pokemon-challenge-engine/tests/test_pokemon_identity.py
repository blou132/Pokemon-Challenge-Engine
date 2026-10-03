"""Synthetic identity tests and independent checks of the documented Gen V table."""
import json
from pathlib import Path

import pytest

from app.core.pokemon_identity import documented_evolution, evolution_family, pokemon_identity, same_evolution_family
from tools.build_gen5_evolution_families import SOURCE_SHA256, build_families, decode_edges


def test_identity_does_not_depend_on_species_level_slot_or_hp():
    pokemon = {"personality_id": 0xFFEE1234, "original_trainer_id": 0x82345678,
               "species_id": 498, "level": 5, "slot": 1, "hp": 20}
    expected = "gen5:ffee1234:82345678"
    assert pokemon_identity(pokemon) == expected
    assert pokemon_identity(pokemon | {"species_id": 499, "level": 17, "slot": 4, "hp": 0}) == expected


def test_same_species_individuals_and_original_trainers_remain_distinct():
    first = {"species_id": 501, "personality_id": 50, "original_trainer_id": 60}
    assert pokemon_identity(first) != pokemon_identity(first | {"personality_id": 51})
    assert pokemon_identity(first) != pokemon_identity(first | {"original_trainer_id": 61})


def test_identity_zero_and_full_unsigned_range_are_valid():
    assert pokemon_identity({"personality_id": 0, "original_trainer_id": 0}) == "gen5:00000000:00000000"
    assert pokemon_identity({"personality_id": 0xFFFFFFFF, "original_trainer_id": 0xFFFFFFFF}) == "gen5:ffffffff:ffffffff"


@pytest.mark.parametrize("value", [None, -1, 0x100000000, True, 1.0, "123", [], {}])
@pytest.mark.parametrize("field", ["personality_id", "original_trainer_id"])
def test_invalid_identity_stays_unknown(field, value):
    assert pokemon_identity({"personality_id": 1, "original_trainer_id": 2} | {field: value}) is None


@pytest.mark.parametrize("pokemon", [{}, {"species_id": 501, "level": 5}, {"personality_id": 123}, None])
def test_legacy_or_incomplete_identity_is_not_guessed(pokemon):
    assert pokemon_identity(pokemon) is None


@pytest.mark.parametrize("generation", [4, 6, None, "5", True])
def test_undocumented_generations_are_not_assumed_compatible(generation):
    assert pokemon_identity({"personality_id": 1, "original_trainer_id": 2}, generation) is None
    assert evolution_family(498, generation) is None
    assert not same_evolution_family(498, 499, generation)


@pytest.mark.parametrize("members,expected", [
    ([498, 499, 500], 498), ([495, 496, 497], 495), ([501, 502, 503], 501),
    ([25, 26, 172], 25), ([133, 134, 135, 136, 196, 197, 470, 471], 133),
    ([236, 106, 107, 237], 106), ([280, 281, 282, 475], 280),
    ([290, 291, 292], 290), ([479], 479), ([649], 649),
])
def test_documented_families_include_pre_gen_v_and_split_evolutions(members, expected):
    assert {evolution_family(species) for species in members} == {expected}
    assert all(same_evolution_family(members[0], species) for species in members)


@pytest.mark.parametrize("first,second", [(498, 501), (29, 32), (588, 616), (127, 214), (133, 700), (0, 0)])
def test_unrelated_or_later_species_are_not_one_gen_v_family(first, second):
    assert not same_evolution_family(first, second)


@pytest.mark.parametrize("species", [0, -1, 650, 700, None, True, 498.0, "498"])
def test_family_unknown_species_is_not_zero(species):
    assert evolution_family(species) is None


def test_complete_table_matches_its_documented_graph_and_source():
    path = Path(__file__).resolve().parents[1] / "data/gen5_evolution_families.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["source"]["resource_sha256"] == SOURCE_SHA256
    assert data["source"]["resource_bytes"] == 3874
    assert len(data["evolution_edges"]) == 320
    assert len(data["families"]) == 329
    species = [entry for family in data["families"] for entry in family]
    assert sorted(species) == list(range(1, 650))
    assert build_families(data["evolution_edges"]) == data["families"]
    assert all(evolution_family(species) == min(family) for family in data["families"] for species in family)


def test_regenerator_refuses_an_unverified_resource():
    with pytest.raises(ValueError, match="SHA-256"):
        decode_edges(b"g5" + bytes(3872))


@pytest.mark.parametrize("first,second", [(498, 499), (498, 500), (172, 26), (133, 197), (290, 291), (236, 237)])
def test_documented_forward_evolution_paths(first, second):
    assert documented_evolution(first, second)


@pytest.mark.parametrize("first,second", [(291, 292), (290, 292), (292, 291), (134, 135), (500, 498), (498, 498), (133, 700), (None, 498)])
def test_family_does_not_imply_same_individual_evolution(first, second):
    assert not documented_evolution(first, second)


def test_shedinja_stays_in_family_but_is_not_an_identity_evolution():
    assert same_evolution_family(290, 292)
    assert not documented_evolution(290, 292)
    assert not documented_evolution(498, 499, generation=6)
