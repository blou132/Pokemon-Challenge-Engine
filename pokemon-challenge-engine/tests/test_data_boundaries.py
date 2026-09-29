"""Les entrées illisibles restent des erreurs utilisateur, sans perte de fichier."""

from pathlib import Path

import pytest

from app.core.challenge_engine import ChallengeEngine
from app.core.profile_manager import ProfileManager
from app.models.challenge import Challenge
from app.services.config_service import ConfigService


def test_cyclic_challenge_settings_are_rejected(catalog):
    challenge = ChallengeEngine(catalog).generate("black", "normal", {}, 0, 42)
    challenge.settings["cycle"] = challenge.settings
    with pytest.raises(ValueError, match="imbriquée"):
        challenge.to_dict()


def test_deep_challenge_data_are_rejected_before_copy(catalog):
    data = ChallengeEngine(catalog).generate("black", "normal", {}, 0, 42).to_dict()
    nested = data["settings"]
    for _ in range(200):
        nested["next"] = {}
        nested = nested["next"]
    with pytest.raises(ValueError, match="imbriquée"):
        Challenge.from_dict(data)


@pytest.mark.parametrize("key", ["game_id", "created_at"])
def test_challenge_invalid_unicode_is_rejected(catalog, key):
    data = ChallengeEngine(catalog).generate("black", "normal", {}, 0, 42).to_dict()
    data[key] = "\ud800"
    with pytest.raises(ValueError, match="Unicode"):
        Challenge.from_dict(data)


def test_unreadable_config_is_not_replaced(tmp_path: Path):
    path = tmp_path / "config.json"
    contents = '[' * 3000 + '0' + ']' * 3000
    path.write_text(contents, encoding="utf-8")
    service = ConfigService(path)
    assert service.load().desmume_path == ""
    assert service.warnings
    assert path.read_text(encoding="utf-8") == contents


@pytest.mark.parametrize("contents", ['[' * 3000 + '0' + ']' * 3000, '{"badges":["\\ud800"]}'])
def test_corrupt_progress_fallback_is_preserved(tmp_path, catalog, contents):
    manager = ProfileManager(tmp_path)
    challenge = ChallengeEngine(catalog).generate("black", "normal", {}, 0, 42)
    profile = manager.create("Parcours", challenge)
    path = tmp_path / profile.id / "progress.json"
    path.write_text(contents, encoding="utf-8")
    loaded = manager.load(profile.id)
    assert loaded.progress["badges"] == []
    assert manager.warnings
    with pytest.raises(ValueError):
        manager.save(loaded)
    assert path.read_text(encoding="utf-8") == contents
