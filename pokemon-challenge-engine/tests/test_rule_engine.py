"""Les incompatibilités doivent rester compréhensibles et symétriques."""

from app.core.rule_engine import RuleEngine
from app.models.rule import Rule


def test_requires_are_explained(rule_engine):
    errors = rule_engine.validate(["nuzlocke"], "black")
    assert any("exige" in error and "Mort permanente" in error for error in errors)


def test_transitive_requirements(rule_engine):
    assert rule_engine.dependency_closure(["species_clause"]) == {"species_clause", "nuzlocke", "permanent_death"}


def test_conflicts_only_declared_one_way_are_detected(rule_engine):
    errors = rule_engine.validate(["solo_run", "nuzlocke", "permanent_death"], "black")
    assert len(errors) == 1
    assert "incompatible" in errors[0]


def test_valid_selection(rule_engine):
    assert not rule_engine.validate(["nuzlocke", "permanent_death", "species_clause"], "black2")


def test_game_not_supported(rule_engine):
    assert "pas disponible" in rule_engine.validate(["nuzlocke", "permanent_death"], "emerald")[0]
    assert rule_engine.available("emerald") == []


def test_duplicates_and_unknown_rules(rule_engine):
    errors = rule_engine.validate(["no_items", "no_items", "missing"], "black")
    assert len(errors) == 2
    assert "plusieurs fois" in errors[0]


def test_model_can_describe_rules_for_other_games():
    engine = RuleEngine([Rule("test", "Test", "Description", 1, "Test", supported_games=("custom_game",))])
    assert engine.validate(["test"], "custom_game") == []
