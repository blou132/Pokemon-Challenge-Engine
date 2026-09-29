"""Le résultat de la roue dépend seulement des paramètres métier."""

import pytest

from app.core.monotype import GEN5_TYPE_IDS, matches_type, select_type


def test_exactly_17_gen5_types(catalog):
    assert len(catalog.types) == len(GEN5_TYPE_IDS) == 17
    assert {item["id"] for item in catalog.types} == set(GEN5_TYPE_IDS)
    assert "fairy" not in GEN5_TYPE_IDS


def test_never_selects_excluded_types():
    allowed = ["fire", "water", "grass"]
    observed = {select_type(allowed, seed) for seed in range(1000)}
    assert observed == set(allowed)


def test_reproducible_with_canonical_order_and_reroll_index():
    for index in range(8):
        assert select_type(["fire", "water"], 123, index) == select_type(["water", "fire"], 123, index)
    assert len({select_type(list(GEN5_TYPE_IDS), 123, index) for index in range(30)}) > 1


@pytest.mark.parametrize("allowed", [[], ["fairy"], ["fire", "fire"], [123], None, "fire"])
def test_invalid_type_lists(allowed):
    with pytest.raises(ValueError):
        select_type(allowed, 3)


@pytest.mark.parametrize("seed,index", [(True, 0), (-1, 0), (3, -1), (3, True), (3.5, 0)])
def test_invalid_seed_and_roll_index(seed, index):
    with pytest.raises(ValueError):
        select_type(["fire"], seed, index)


def test_monotype_modes_have_distinct_semantics():
    assert matches_type(["fire", "flying"], "flying", "soft")
    assert not matches_type(["fire", "flying"], "flying", "strict")
    assert matches_type(["fire", "flying"], "fire", "strict")
    assert not matches_type(["fire", "flying"], "fire", "pure")
    assert matches_type(["fire"], "fire", "pure")
