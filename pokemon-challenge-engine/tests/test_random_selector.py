"""Le tirage respecte le total exact, les dépendances et les interdictions."""

from itertools import combinations

import pytest

from app.core.random_selector import RandomSelector
from app.core.rule_engine import RuleEngine
from app.models.rule import Rule, RuleState


def test_required_forbidden_exact_count_and_seed(rule_engine):
    selector = RandomSelector(rule_engine)
    states = {"nuzlocke": RuleState.REQUIRED, "permanent_death": "required", "shiny_only": "forbidden", "solo_run": "forbidden"}
    first = selector.select("black", states, 5, 482193)
    assert first == selector.select("black", dict(reversed(list(states.items()))), 5, 482193)
    for seed in range(150):
        result = selector.select("black", states, 5, seed)
        assert len(result) == len(set(result)) == 5
        assert {"nuzlocke", "permanent_death"} <= set(result)
        assert not {"shiny_only", "solo_run"} & set(result)
        assert rule_engine.validate(result, "black") == []


@pytest.mark.parametrize("count", [-1, True, 1.5, 999])
def test_impossible_count_is_a_clear_error(rule_engine, count):
    with pytest.raises(ValueError, match="nombre|Impossible"):
        RandomSelector(rule_engine).select("black", {}, count, 1)


def test_required_dependency_cannot_be_forbidden(rule_engine):
    with pytest.raises(ValueError, match="interdite"):
        RandomSelector(rule_engine).select("black", {"nuzlocke": "required", "permanent_death": "forbidden"}, 3, 5)


def test_conflicting_required_rules(rule_engine):
    with pytest.raises(ValueError, match="incompatible"):
        RandomSelector(rule_engine).max_count("black", {"solo_run": "required", "nuzlocke": "required"})


def test_required_count_includes_transitive_dependencies(rule_engine):
    selector = RandomSelector(rule_engine)
    states = {"species_clause": "required"}
    assert selector.feasible_counts("black", states)[0] == 3
    assert selector.select("black", states, 3, 8) == ["nuzlocke", "permanent_death", "species_clause"]
    with pytest.raises(ValueError, match="exactement 2"):
        selector.select("black", states, 2, 8)


def test_all_forbidden_allows_empty_challenge(rule_engine):
    selector = RandomSelector(rule_engine)
    states = {key: "forbidden" for key in rule_engine.rules}
    assert selector.feasible_counts("black", states) == [0]
    assert selector.max_count("black", states) == 0
    assert selector.select("black", states, 0, 0) == []


def test_unavailable_dependency_disables_candidate():
    rules = [Rule("a", "A", "A", 1, "Test", requires=("b",), supported_games=("black",)),
             Rule("b", "B", "B", 1, "Test", supported_games=("black2",)),
             Rule("c", "C", "C", 1, "Test", supported_games=("black",))]
    selector = RandomSelector(RuleEngine(rules))
    assert selector.max_count("black", {}) == 1
    assert selector.select("black", {}, 1, 0) == ["c"]
    with pytest.raises(ValueError, match="pas disponible"):
        selector.select("black", {"a": "required"}, 2, 0)


def test_feasible_counts_match_exhaustive_reference(rule_engine):
    """Comparaison indépendante avec toutes les sélections d'un petit sous-catalogue."""
    candidates = ["nuzlocke", "permanent_death", "species_clause", "solo_run", "starter_only", "no_items"]
    states = {key: "forbidden" for key in rule_engine.rules if key not in candidates}
    expected = set()
    for count in range(len(candidates) + 1):
        for subset in combinations(candidates, count):
            if not rule_engine.validate(subset, "black"):
                expected.add(count)
    selector = RandomSelector(rule_engine)
    assert selector.feasible_counts("black", states) == sorted(expected)
    for count in expected:
        for seed in range(10):
            result = selector.select("black", states, count, seed)
            assert len(result) == count
            assert rule_engine.validate(result, "black") == []


def test_cache_is_reused_for_count_and_draw(rule_engine):
    selector = RandomSelector(rule_engine)
    selector.max_count("black", {})
    selector.select("black", {}, 5, 2)
    assert selector._cached_solutions.cache_info().hits == 1


def test_search_has_explicit_complexity_bound(rule_engine):
    selector = RandomSelector(rule_engine)
    selector.SEARCH_NODE_LIMIT = 1
    with pytest.raises(ValueError, match="trop de combinaisons"):
        selector.max_count("black", {})


@pytest.mark.parametrize("states", [{"unknown": "required"}, {"monotype": "invalid"}, None])
def test_invalid_states_are_rejected(rule_engine, states):
    with pytest.raises(ValueError):
        RandomSelector(rule_engine).select("black", states, 3, 5)
