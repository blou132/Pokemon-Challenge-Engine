"""Explicit transformation settings validation, keeping historical profiles intact."""
from copy import deepcopy

import pytest

from app.core.challenge_engine import ChallengeEngine


@pytest.mark.parametrize("value", [None, {}, {"kind": "unknown", "categories": ["wild"], "balanced": False},
    {"kind": "zx", "categories": [], "balanced": False},
    {"kind": "zx", "categories": ["fake"], "balanced": False},
    {"kind": "zx", "categories": ["types"], "balanced": True},
    {"kind": "zx", "categories": ["wild"], "balanced": False, "java_path": "local.exe"}])
def test_invalid_explicit_transform_is_rejected(catalog, value):
    engine = ChallengeEngine(catalog)
    challenge = engine.generate("white", "custom", {"randomizer": "required"}, 0, 42)
    challenge.settings["rom_transformation"] = value
    assert engine.validate(challenge)


def test_transform_requires_active_randomizer(catalog):
    engine = ChallengeEngine(catalog)
    challenge = engine.generate("white", "normal", {}, 0, 42)
    challenge.settings["rom_transformation"] = {"kind": "zx", "categories": ["wild"], "balanced": False}
    assert engine.validate(challenge)


def test_historical_randomizer_stays_valid_without_transformation(catalog):
    engine = ChallengeEngine(catalog)
    challenge = engine.generate("white", "custom", {"randomizer": "required"}, 0, 42)
    before = deepcopy(challenge.to_dict())
    assert engine.validate(challenge) == []
    assert challenge.to_dict() == before


def test_valid_options_share_the_challenge_seed_without_tool_paths(catalog):
    engine = ChallengeEngine(catalog)
    challenge = engine.generate("white", "custom", {"randomizer": "required"}, 0, 2**63 - 1,
        settings={"rom_transformation": {"kind": "zx", "categories": ["wild", "starters"], "balanced": True}})
    assert engine.validate(challenge) == []
    assert challenge.seed == 2**63 - 1
    challenge.seed = 2**63
    assert engine.validate(challenge)
