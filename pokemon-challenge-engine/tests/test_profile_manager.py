"""Vérifie les profils locaux et la préservation des données défectueuses."""

import json
from pathlib import Path

import pytest

from app.core.profile_manager import ProfileManager
from app.models.challenge import Challenge
from app.models.rule import RuleState


@pytest.fixture
def challenge() -> Challenge:
    return Challenge(game_id="black2", mode="custom", active_rules=["nuzlocke"],
                     rule_states={"nuzlocke": RuleState.REQUIRED.value},
                     settings={"enforcement": "soft", "rule_parameters": {}}, monotype=None, seed=482193)


def test_create_reload_and_update(tmp_path: Path, challenge: Challenge) -> None:
    manager = ProfileManager(tmp_path / "profiles")
    profile = manager.create("L'aventure été 01", challenge)
    assert {path.name for path in (manager.root / profile.id).iterdir()} == {"challenge.json", "progress.json", "history.json"}
    reloaded = manager.load(profile.id)
    assert reloaded.name == "L'aventure été 01"
    assert reloaded.challenge.to_dict() == challenge.to_dict()
    assert reloaded.challenge.seed == 482193
    reloaded.progress["badges"] = ["Badge Triple"]
    reloaded.progress["current_level_cap"] = 14
    reloaded.history.append({"event": "manual_update", "description": "Premier badge"})
    manager.save(reloaded)
    updated = manager.load(profile.id)
    assert updated.progress["badges"] == ["Badge Triple"]
    assert updated.progress["current_level_cap"] == 14
    assert updated.history[0]["event"] == "manual_update"
    assert not manager.warnings


def test_duplicate_names_get_distinct_directories(tmp_path: Path, challenge: Challenge) -> None:
    manager = ProfileManager(tmp_path)
    first = manager.create("Ma partie", challenge)
    second = manager.create("Ma partie", challenge)
    assert first.id != second.id
    assert len(manager.list_profiles()) == 2


@pytest.mark.parametrize("filename", ["progress.json", "history.json"])
def test_missing_optional_file_uses_memory_fallback(tmp_path: Path, challenge: Challenge, filename: str) -> None:
    manager = ProfileManager(tmp_path)
    profile = manager.create("Partie", challenge)
    (tmp_path / profile.id / filename).unlink()
    loaded = manager.load(profile.id)
    assert loaded.history == [] and loaded.progress["badges"] == []
    assert filename in manager.warnings[0]
    assert not (tmp_path / profile.id / filename).exists()
    manager.save(loaded)
    assert (tmp_path / profile.id / filename).is_file()


@pytest.mark.parametrize("filename,content", [
    ("progress.json", "{"), ("history.json", '{"unexpected": true}'),
    ("progress.json", '{"badges": 3}'), ("progress.json", '{"current_level_cap": true}'),
    ("progress.json", '{"badges": [], "badges": ["duplication"]}'),
    ("progress.json", '{"current_level_cap": NaN}'), ("history.json", "[3]"),
])
def test_corrupt_optional_files_are_preserved(tmp_path: Path, challenge: Challenge, filename: str, content: str) -> None:
    manager = ProfileManager(tmp_path)
    profile = manager.create("Partie", challenge)
    target = tmp_path / profile.id / filename
    target.write_text(content, encoding="utf-8")
    original_challenge = (tmp_path / profile.id / "challenge.json").read_bytes()
    loaded = manager.load(profile.id)
    assert manager.warnings
    with pytest.raises(ValueError, match="corrompu"):
        manager.save(loaded)
    assert target.read_text(encoding="utf-8") == content
    assert (tmp_path / profile.id / "challenge.json").read_bytes() == original_challenge


@pytest.mark.parametrize("content", ["{", "[]", "{}", '{"game_id": null}'])
def test_corrupt_challenge_is_ignored_in_listing(tmp_path: Path, challenge: Challenge, content: str) -> None:
    manager = ProfileManager(tmp_path)
    profile = manager.create("Partie", challenge)
    target = tmp_path / profile.id / "challenge.json"
    target.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        manager.load(profile.id)
    with pytest.raises(ValueError):
        manager.save(profile)
    assert manager.list_profiles() == []
    assert manager.warnings and target.read_text(encoding="utf-8") == content


def test_missing_challenge_is_an_error(tmp_path: Path, challenge: Challenge) -> None:
    manager = ProfileManager(tmp_path)
    profile = manager.create("Partie", challenge)
    (tmp_path / profile.id / "challenge.json").unlink()
    with pytest.raises(ValueError, match="challenge.json"):
        manager.load(profile.id)
    assert manager.list_profiles() == []
    assert manager.warnings


@pytest.mark.parametrize("profile_id", ["../parent", "..", "a/b", "a\\b", "/absolute", "C:\\absolute", "", "NUL."])
def test_directory_traversal_is_rejected(tmp_path: Path, profile_id: str) -> None:
    with pytest.raises(ValueError):
        ProfileManager(tmp_path).load(profile_id)


def test_invalid_profile_does_not_modify_existing_files(tmp_path: Path, challenge: Challenge) -> None:
    manager = ProfileManager(tmp_path)
    profile = manager.create("Partie", challenge)
    before = {path.name: path.read_bytes() for path in (tmp_path / profile.id).iterdir()}
    profile.progress["current_level_cap"] = 101
    with pytest.raises(ValueError, match="level cap"):
        manager.save(profile)
    assert {path.name: path.read_bytes() for path in (tmp_path / profile.id).iterdir()} == before


def test_invalid_original_name_cannot_be_overwritten(tmp_path: Path, challenge: Challenge) -> None:
    manager = ProfileManager(tmp_path)
    profile = manager.create("Partie", challenge)
    target = tmp_path / profile.id / "challenge.json"
    original = json.loads(target.read_text(encoding="utf-8"))
    original["profile_name"] = []
    target.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(ValueError):
        manager.save(profile)
    assert json.loads(target.read_text(encoding="utf-8"))["profile_name"] == []


def test_mismatched_profile_id_is_rejected(tmp_path: Path, challenge: Challenge) -> None:
    manager = ProfileManager(tmp_path)
    profile = manager.create("Partie", challenge)
    target = tmp_path / profile.id / "challenge.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    data["profile_id"] = "different_profile"
    target.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="identifiant"):
        manager.load(profile.id)


def test_listing_does_not_create_storage(tmp_path: Path) -> None:
    root = tmp_path / "not_created"
    assert ProfileManager(root).list_profiles() == []
    assert not root.exists()
