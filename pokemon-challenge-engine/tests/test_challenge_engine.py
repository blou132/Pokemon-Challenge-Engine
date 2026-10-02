"""La préparation d'un challenge reste indépendante du jeu lancé."""

from copy import deepcopy

import pytest

from app.core.challenge_engine import ChallengeEngine
from app.core.profile_manager import ProfileManager
from app.models.challenge import Challenge


def test_normal_has_no_rules_even_when_states_are_required(catalog):
    result = ChallengeEngine(catalog).generate("black", "normal", {"nuzlocke": "required"}, 5, 123)
    assert result.active_rules == []
    assert result.monotype is None


def test_custom_includes_dependency_closure(catalog):
    result = ChallengeEngine(catalog).generate("black2", "custom", {"species_clause": "required"}, 1, 123)
    assert result.active_rules == ["nuzlocke", "permanent_death", "species_clause"]


@pytest.mark.parametrize("game_id", ["black", "white", "black2", "white2"])
def test_gen5_challenge_roundtrip_keeps_game_and_v01_profile_schema(catalog, tmp_path, game_id):
    engine = ChallengeEngine(catalog)
    challenge = engine.generate(game_id, "custom", {"species_clause": "required", "monotype": "required"}, 4, 123)
    assert not engine.validate(challenge)
    assert challenge.active_rules == ["monotype", "nuzlocke", "permanent_death", "species_clause"]
    manager = ProfileManager(tmp_path / "profiles")
    stored = manager.create(catalog.games[game_id].name, challenge)
    loaded = manager.load(stored.id).challenge
    assert loaded.game_id == game_id
    assert loaded.version == "0.1.0"
    assert loaded.to_dict() == challenge.to_dict()


def test_monotype_auto_config_and_parameters_saved(catalog):
    engine = ChallengeEngine(catalog)
    states = {"monotype": "required", "level_cap": "required"}
    first = engine.generate("black", "custom", states, 2, 123)
    second = engine.generate("black", "custom", states, 2, 123)
    assert first.monotype == second.monotype
    assert first.settings["rule_parameters"]["level_cap"]["max_level"] == 20
    assert Challenge.from_dict(first.to_dict()).to_dict() == first.to_dict()


def test_strict_intention_can_be_saved_without_enforcement(catalog):
    result = ChallengeEngine(catalog).generate("black", "custom", {"nuzlocke": "required"}, 2, 123,
                                             settings={"enforcement": "strict"})
    assert result.settings["enforcement"] == "strict"


def test_parameters_for_inactive_rules_are_excluded_from_final_challenge(catalog):
    result = ChallengeEngine(catalog).generate("black", "normal", {}, 0, 1, settings={
        "rule_parameters": {"level_cap": {"max_level": 40}},
    })
    assert result.settings["rule_parameters"] == {}


@pytest.mark.parametrize("parameters", [{"max_level": 0}, {"max_level": 101}, {"max_level": True}, {"unknown": 3}])
def test_invalid_parameters_rejected(catalog, parameters):
    with pytest.raises(ValueError, match="Niveau maximum|inconnu"):
        ChallengeEngine(catalog).generate("black", "custom", {"level_cap": "required"}, 1, 3,
                                          settings={"rule_parameters": {"level_cap": parameters}})


def test_future_games_are_not_yet_generatable(catalog):
    with pytest.raises(ValueError, match="version ultérieure"):
        ChallengeEngine(catalog).generate("emerald", "normal", {}, 0, 3)


@pytest.mark.parametrize("field,value", [
    ("seed", True), ("seed", -1), ("active_rules", ["no_items", "no_items"]),
    ("active_rules", [42]), ("rule_states", {"no_items": "unknown"}),
    ("settings", {"enforcement": "unknown", "rule_parameters": {}}),
    ("settings", {"enforcement": "soft", "rule_parameters": {"x": float("nan")}}),
    ("created_at", "hier"), ("created_at", "2026-09-29"), ("version", "9.0.0"),
    ("mode", "missing"), ("monotype", {"type_id": "fire"}),
])
def test_challenge_schema_rejects_invalid_values(catalog, field, value):
    data = ChallengeEngine(catalog).generate("black", "normal", {}, 0, 3).to_dict()
    data[field] = value
    with pytest.raises(ValueError):
        Challenge.from_dict(data)


def test_monotype_rejects_excluded_result(catalog):
    data = ChallengeEngine(catalog).generate("black", "custom", {"monotype": "required"}, 1, 3).to_dict()
    data["monotype"]["allowed_types"] = ["fire"]
    data["monotype"]["type_id"] = "water"
    with pytest.raises(ValueError, match="autorisés"):
        Challenge.from_dict(data)


def test_saved_profile_is_detached_from_source(catalog):
    data = ChallengeEngine(catalog).generate("black", "custom", {"monotype": "required"}, 1, 3).to_dict()
    saved = deepcopy(data)
    challenge = Challenge.from_dict(data)
    data["monotype"]["allowed_types"].clear()
    assert challenge.to_dict() == saved


def test_profile_with_semantically_inconsistent_states_is_rejected(catalog):
    engine = ChallengeEngine(catalog)
    challenge = engine.generate("black", "custom", {"no_items": "required"}, 1, 2)
    challenge.rule_states["no_items"] = "forbidden"
    assert any("interdite" in error for error in engine.validate(challenge))
