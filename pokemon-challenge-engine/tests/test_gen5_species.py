"""Source-derived facts and synthetic rule checks; no emulator validation."""
import json
from pathlib import Path

import pytest

from app.core.gen5_species import evolution_stage, is_unevolved, monotype_compliance, species_types, starter_species
from app.core.monotype import GEN5_TYPE_IDS
from tools.build_gen5_species_types import SOURCES, SOURCE_COMMIT, TYPE_IDS, decode_table


@pytest.mark.parametrize("game", ["black", "white", "black2", "white2"])
def test_all_gen5_species_have_documented_base_types(game):
    for species in range(1, 650):
        types = species_types(species, game, form=0)
        assert types and 1 <= len(types) <= 2
        assert set(types) <= set(GEN5_TYPE_IDS)
        assert len(set(types)) == len(types)
        assert evolution_stage(species, game) in (0, 1, 2)


@pytest.mark.parametrize("species,expected", [
    (1, ("grass", "poison")), (6, ("fire", "flying")),
    (35, ("normal",)), (39, ("normal",)), (81, ("electric", "steel")),
    (183, ("water",)), (282, ("psychic",)), (303, ("steel",)),
    (511, ("grass",)), (535, ("water",)), (499, ("fire", "fighting")),
])
def test_types_are_generation_five_not_modern_fairy_types(species, expected):
    assert species_types(species, "white") == expected
    assert species_types(species, "white2") == expected


@pytest.mark.parametrize("form,expected", [
    (0, ("electric", "ghost")), (1, ("electric", "fire")),
    (2, ("electric", "water")), (3, ("electric", "ice")),
    (4, ("electric", "flying")), (5, ("electric", "grass")),
])
def test_rotom_forms_use_gen5_secondary_types(form, expected):
    assert species_types(479, "white", form) == expected
    assert species_types(479, "black2", form) == expected


@pytest.mark.parametrize("species,form,expected", [
    (351, 1, ("fire",)), (351, 2, ("water",)), (351, 3, ("ice",)),
    (413, 1, ("bug", "ground")), (413, 2, ("bug", "steel")),
    (492, 1, ("grass", "flying")), (555, 1, ("fire", "psychic")),
    (648, 1, ("normal", "fighting")),
])
def test_form_changes_are_not_silently_mapped_to_base_species(species, form, expected):
    assert species_types(species, "white", form) == expected


def test_arceus_forms_do_not_all_inherit_normal_from_shared_personal_row():
    for form, expected in enumerate(TYPE_IDS):
        assert species_types(493, "white", form) == (expected,)
    assert species_types(493, "white", 17) is None
    assert species_types(493, "white") is None


@pytest.mark.parametrize("species,form", [(641, 1), (642, 1), (645, 1), (646, 1), (646, 2), (647, 1)])
def test_sequel_only_forms_are_refused_in_black_and_white(species, form):
    assert species_types(species, "black", form) is None
    assert species_types(species, "white", form) is None
    assert species_types(species, "black2", form) is not None
    assert species_types(species, "white2", form) is not None


@pytest.mark.parametrize("species", [351, 413, 479, 492, 493, 555, 648])
def test_missing_form_with_variable_types_remains_unknown(species):
    assert species_types(species, "white") is None
    assert monotype_compliance(species, "white", "fire") is None


@pytest.mark.parametrize("species,form,expected", [
    (201, 27, ("psychic",)), (412, 2, ("bug",)),
    (414, 2, ("bug", "flying")), (421, 1, ("grass",)),
    (422, 1, ("water",)), (423, 1, ("water", "ground")),
    (585, 3, ("normal", "grass")), (586, 3, ("normal", "grass")),
    (649, 4, ("bug", "steel")),
])
def test_cosmetic_forms_and_genesect_drives_keep_species_types(species, form, expected):
    assert species_types(species, "white", form) == expected
    assert species_types(species, "white") == expected


@pytest.mark.parametrize("species", [0, -1, 650, 666, 1000, True, 1.0, "1", None, []])
def test_unknown_species_are_not_personal_table_form_indices(species):
    assert species_types(species, "white", 0) is None
    assert evolution_stage(species, "white") is None
    assert is_unevolved(species, "white") is None


@pytest.mark.parametrize("game", ["bw", "white_fr", "scarlet", "", None, [], True])
def test_unknown_game_never_defaults_to_bw(game):
    assert species_types(1, game) is None
    assert evolution_stage(1, game) is None
    assert starter_species(game) is None


@pytest.mark.parametrize("form", [-1, 32, True, 0.0, "0", [], {}])
def test_invalid_forms_remain_unknown(form):
    assert species_types(1, "white", form) is None


def test_monotype_three_modes_are_distinct_and_pure_accepts_single_type():
    assert monotype_compliance(6, "white", "flying", "soft") is True
    assert monotype_compliance(6, "white", "flying", "strict") is False
    assert monotype_compliance(6, "white", "fire", "strict") is True
    assert monotype_compliance(6, "white", "fire", "pure") is False
    assert monotype_compliance(4, "white", "fire", "pure") is True
    assert monotype_compliance(4, "white", "water", "soft") is False


def test_unknown_monotype_configuration_is_not_an_unknown_observation():
    with pytest.raises(ValueError, match="Monotype"):
        monotype_compliance(1, "white", "fairy")
    with pytest.raises(ValueError, match="Monotype"):
        monotype_compliance(1, "white", "grass", "hard")


def test_changed_rom_data_invalidates_each_affected_vanilla_lookup():
    assert species_types(1, "white", 0, types_modified=True) is None
    assert monotype_compliance(1, "white", "grass", form=0, types_modified=True) is None
    assert evolution_stage(1, "white", evolutions_modified=True) is None
    assert is_unevolved(1, "white", evolutions_modified=True) is None
    assert starter_species("white", starters_modified=True) is None
    # Unrelated transformations need not change these particular tables.
    assert species_types(1, "white", types_modified=False) == ("grass", "poison")


@pytest.mark.parametrize("species,expected", [
    (1, 0), (2, 1), (3, 2), (172, 0), (25, 1), (26, 2),
    (236, 0), (106, 1), (290, 0), (291, 1), (292, 1),
    (298, 0), (183, 1), (184, 2), (201, 0), (479, 0), (493, 0),
])
def test_evolution_stage_uses_directed_edges_including_babies_and_shedinja(species, expected):
    assert evolution_stage(species, "white") == expected
    assert is_unevolved(species, "white") is (expected == 0)


@pytest.mark.parametrize("game", ["black", "white", "black2", "white2"])
def test_starter_lookup_only_returns_vanilla_candidates(game):
    assert starter_species(game) == (495, 498, 501)


def test_data_has_separate_sources_and_no_missing_or_extra_species():
    path = Path(__file__).resolve().parents[1] / "data/gen5_species_types.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["source"]["commit"] == SOURCE_COMMIT
    assert document["validation"] == "source_documented"
    assert len(document["type_ids"]) == 17
    for family in ("bw", "b2w2"):
        table = document["families"][family]
        assert table["source"]["resource_sha256"] == SOURCES[family]["sha256"]
        assert table["source"]["resource_bytes"] == SOURCES[family]["bytes"]
        assert [row["species_id"] for row in table["species"]] == list(range(1, 650))
    assert SOURCES["bw"]["sha256"] != SOURCES["b2w2"]["sha256"]


@pytest.mark.parametrize("family", ["bw", "b2w2"])
def test_regenerator_refuses_unverified_or_wrong_game_resource(family):
    with pytest.raises(ValueError, match="SHA-256"):
        decode_table(bytes(SOURCES[family]["bytes"]), family)


def test_regenerator_refuses_unknown_game_family():
    with pytest.raises(ValueError, match="family"):
        decode_table(b"", "xy")
