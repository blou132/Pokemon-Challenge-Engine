"""Crash recovery and synthetic profile-bound consumption, without game access."""

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.profile_manager import ProfileManager
from app.models.profile import default_progress, validate_progress
from app.services.tracking_service import TrackingService
from test_nuzlocke_tracker import battle, make_profile, observation, zone


def create(base, *, enabled=True, clause=False, game="white"):
    manager = ProfileManager(base / "profiles")
    return manager, manager.create("Partie", make_profile(enabled=enabled, clause=clause, game=game).challenge)


def state(value=None, sequence=1, session="session-one", **changes):
    defaults = dict(game_id="white", game_code="IRAF", game_region="FR", rom_revision=0,
                    connected=True, session_id=session, sequence=sequence, last_timestamp=1000,
                    observation=asdict(value) if value is not None else None, observations=(), last_event="heartbeat")
    return SimpleNamespace(**(defaults | changes))


def contents(manager, profile):
    return {path.name: path.read_bytes() for path in (manager.root / profile.id).iterdir()}


def test_no_profile_and_rule_disabled_never_write(tmp_path):
    service = TrackingService(tmp_path)
    assert service.consume(state(battle())).status == "disabled"
    assert not (tmp_path / "profiles").exists()
    manager, profile = create(tmp_path, enabled=False)
    original = contents(manager, profile)
    assert service.select_profile(profile.id).status == "disabled"
    assert service.consume(state(battle(outcome="captured"))).status == "disabled"
    assert contents(manager, profile) == original


@pytest.mark.parametrize("changes", [{"game_id": "black"}, {"game_code": "IRBF"}, {"game_region": "EN"},
                                     {"rom_revision": 1}])
def test_identity_mismatch_is_reported_without_writing(tmp_path, changes):
    manager, profile = create(tmp_path)
    original = contents(manager, profile)
    service = TrackingService(tmp_path)
    service.select_profile(profile.id)
    result = service.consume(state(battle(outcome="captured"), **changes))
    assert result.status == "mismatch"
    assert "incompatibles" in result.message
    assert contents(manager, profile) == original


@pytest.mark.parametrize("field", ["game_id", "game_code", "game_region", "rom_revision"])
def test_missing_identity_is_waiting_without_writing(tmp_path, field):
    manager, profile = create(tmp_path)
    original = contents(manager, profile)
    service = TrackingService(tmp_path)
    service.select_profile(profile.id)
    assert service.consume(state(battle(), **{field: None})).status == "waiting"
    assert contents(manager, profile) == original


def test_restart_keeps_zone_and_reconnect_does_not_duplicate(tmp_path):
    manager, profile = create(tmp_path)
    service = TrackingService(tmp_path)
    service.select_profile(profile.id)
    service.consume(state(battle(), 1))
    service.consume(state(battle(outcome="captured"), 2))
    reloaded = TrackingService(tmp_path)
    result = reloaded.select_profile(profile.id)
    assert result.zone_used is True
    assert result.encounter["result"] == "captured"
    reloaded.consume(state(battle(outcome="captured"), 1, session="session-two"))
    saved = manager.load(profile.id)
    assert len(saved.history) == 3
    assert saved.challenge.version == "0.1.0"
    assert saved.progress["schema_version"] == 2


def test_profile_switch_updates_only_selected_profile(tmp_path):
    manager, first = create(tmp_path)
    _, second = create(tmp_path)
    service = TrackingService(tmp_path)
    service.select_profile(first.id)
    service.consume(state(battle(outcome="captured")))
    service.select_profile(second.id)
    assert service.state.zone_used is None
    service.consume(state(battle(outcome="player_fled")))
    assert zone(manager.load(first.id))["first_encounter"]["result"] == "captured"
    assert zone(manager.load(second.id))["first_encounter"]["result"] == "player_fled"


def test_disconnect_and_null_do_not_consume_pending_encounter(tmp_path):
    manager, profile = create(tmp_path)
    service = TrackingService(tmp_path)
    service.select_profile(profile.id)
    service.consume(state(battle()))
    service.consume(state(sequence=2, connected=False))
    service.consume(state(observation(battle_active=None), sequence=3))
    assert zone(manager.load(profile.id))["status"] == "encounter_started"


def test_map_only_is_explicitly_unavailable_and_does_not_consume(tmp_path):
    manager, profile = create(tmp_path)
    service = TrackingService(tmp_path)
    service.select_profile(profile.id)
    result = service.consume(state(observation(battle_active=None)))
    assert result.status == "waiting"
    assert "non documentées" in result.message
    assert zone(manager.load(profile.id))["used"] is False


def test_chronological_journal_preserves_battle_lost_between_polls(tmp_path):
    manager, profile = create(tmp_path)
    service = TrackingService(tmp_path)
    service.select_profile(profile.id)
    observations = [battle(), battle(hp=0), observation()]
    journal = tuple({"id": f"session-one:{i}", "session_id": "session-one", "sequence": i,
                     "timestamp": 1000 + i, "observation": asdict(value)}
                    for i, value in enumerate(observations, 1))
    service.consume(state(observation(), 5, observations=journal))
    saved = manager.load(profile.id)
    assert zone(saved)["first_encounter"]["result"] == "fainted"
    original = contents(manager, profile)
    service.consume(state(observation(), 6, observations=journal))
    assert contents(manager, profile) == original


def test_closing_flushes_valid_journal_without_assuming_an_end(tmp_path):
    manager, profile = create(tmp_path)
    service = TrackingService(tmp_path)
    service.select_profile(profile.id)
    journal = ({"id": "session-one:1", "session_id": "session-one", "sequence": 1,
                "timestamp": 1000, "observation": asdict(battle())},)
    result = service.consume(state(connected=False, last_event="emulator_closing", observations=journal))
    assert result.status == "waiting"
    assert zone(manager.load(profile.id))["status"] == "encounter_started"


def test_unchanged_heartbeat_does_not_write(tmp_path):
    manager, profile = create(tmp_path)
    service = TrackingService(tmp_path)
    service.select_profile(profile.id)
    service.consume(state(battle()))
    before = contents(manager, profile)
    service.consume(state(battle(), sequence=2))
    assert contents(manager, profile) == before


def test_legacy_migration_preserves_manual_data_and_is_read_only_until_update(tmp_path):
    manager, profile = create(tmp_path)
    legacy = {"badges": ["Triple"], "captures": [{"manual": True}], "deaths": [],
              "zones": ["Zone manuelle"], "current_level_cap": 14}
    path = manager.root / profile.id / "progress.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    before = path.read_bytes()
    loaded = manager.load(profile.id)
    assert loaded.progress["schema_version"] == 2
    assert loaded.progress["zones"] == ["Zone manuelle"]
    assert path.read_bytes() == before
    service = TrackingService(tmp_path)
    service.select_profile(profile.id)
    service.consume(state(battle()))
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2
    assert manager.load(profile.id).progress["badges"] == ["Triple"]


@pytest.mark.parametrize("filename,content", [("progress.json", "{"), ("history.json", "{}"),
                                             ("progress.json", '{"schema_version":99}')])
def test_corrupt_files_disable_tracking_and_are_preserved(tmp_path, filename, content):
    manager, profile = create(tmp_path)
    path = manager.root / profile.id / filename
    path.write_text(content, encoding="utf-8")
    before = contents(manager, profile)
    service = TrackingService(tmp_path)
    assert service.select_profile(profile.id).status == "error"
    assert service.consume(state(battle(outcome="captured"))).status == "error"
    assert contents(manager, profile) == before


def test_corruption_after_selection_also_refuses_writes(tmp_path):
    manager, profile = create(tmp_path)
    service = TrackingService(tmp_path)
    service.select_profile(profile.id)
    target = manager.root / profile.id / "history.json"
    target.write_text("[broken", encoding="utf-8")
    before = contents(manager, profile)
    assert service.consume(state(battle())).status == "error"
    assert contents(manager, profile) == before


@pytest.mark.parametrize("field,value", [("schema_version", True), ("schema_version", 3),
                                       ("nuzlocke", {}), ("nuzlocke", None)])
def test_invalid_progress_schema_is_rejected(field, value):
    data = default_progress()
    data[field] = value
    with pytest.raises(ValueError):
        validate_progress(data)


def test_explicit_schema_two_requires_tracking_payload():
    with pytest.raises(ValueError, match="exige"):
        validate_progress({"schema_version": 2})


@pytest.mark.parametrize("corruption", ["status", "seen_battles", "result", "consumption", "contradictory_result"])
def test_malformed_nested_types_preserve_corrupt_profile(tmp_path, corruption):
    manager, profile = create(tmp_path)
    service = TrackingService(tmp_path)
    service.select_profile(profile.id)
    service.consume(state(battle(outcome="captured")))
    path = manager.root / profile.id / "progress.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if corruption == "status":
        data["nuzlocke"]["zones"]["route_1"]["status"] = []
    elif corruption == "result":
        data["nuzlocke"]["zones"]["route_1"]["first_encounter"]["result"] = []
    elif corruption == "consumption":
        data["nuzlocke"]["zones"]["route_1"]["used"] = False
    elif corruption == "contradictory_result":
        data["nuzlocke"]["zones"]["route_1"]["first_encounter"]["result"] = "fainted"
    else:
        data["nuzlocke"]["seen_battles"] = {"one": {}}
    path.write_text(json.dumps(data), encoding="utf-8")
    before = contents(manager, profile)
    assert TrackingService(tmp_path).select_profile(profile.id).status == "error"
    assert contents(manager, profile) == before


@pytest.mark.parametrize("break_after", [".transaction.json", "challenge.json", "progress.json", "history.json"])
def test_interrupted_transaction_recovers_progress_and_history_together(tmp_path, monkeypatch, break_after):
    manager, profile = create(tmp_path)
    profile.progress["badges"] = ["Updated"]
    profile.history = [{"id": "event-one", "event": "manual_update"}]
    original_replace = manager._replace_json

    def interrupted(destination, content):
        original_replace(destination, content)
        if destination.name == break_after:
            raise OSError("Synthetic interruption")

    monkeypatch.setattr(manager, "_replace_json", interrupted)
    with pytest.raises(ValueError, match="sauvegarder"):
        manager.save(profile)
    assert (manager.root / profile.id / ".transaction.json").exists()
    recovered = ProfileManager(manager.root).load(profile.id)
    assert recovered.progress["badges"] == ["Updated"]
    assert recovered.history == profile.history
    assert not (manager.root / profile.id / ".transaction.json").exists()


def test_interruption_before_journal_commit_preserves_all_old_files(tmp_path, monkeypatch):
    manager, profile = create(tmp_path)
    before = contents(manager, profile)
    profile.history.append({"event": "new"})
    monkeypatch.setattr(manager, "_replace_json", lambda *_: (_ for _ in ()).throw(OSError("No disk space")))
    with pytest.raises(ValueError):
        manager.save(profile)
    assert contents(manager, profile) == before


def test_recovery_refuses_to_overwrite_external_change(tmp_path, monkeypatch):
    manager, profile = create(tmp_path)
    original_replace = manager._replace_json

    def interrupted(destination, content):
        original_replace(destination, content)
        if destination.name == ".transaction.json":
            raise OSError("Interrupted")

    profile.history.append({"event": "new"})
    monkeypatch.setattr(manager, "_replace_json", interrupted)
    with pytest.raises(ValueError):
        manager.save(profile)
    target = manager.root / profile.id / "history.json"
    target.write_text("[broken", encoding="utf-8")
    before = contents(manager, profile)
    with pytest.raises(ValueError, match="modifié"):
        ProfileManager(manager.root).load(profile.id)
    assert contents(manager, profile) == before


def test_update_reloads_latest_data_and_does_not_overwrite_tracking(tmp_path):
    manager, profile = create(tmp_path)
    service = TrackingService(tmp_path)
    service.select_profile(profile.id)
    service.consume(state(battle(outcome="captured")))
    manager.update(profile.id, lambda fresh: fresh.progress["badges"].append("Manual badge"))
    result = manager.load(profile.id)
    assert result.progress["badges"] == ["Manual badge"]
    assert zone(result)["used"] is True
    assert len(result.history) == 3


def test_incomplete_journal_is_refused_without_modification(tmp_path):
    manager, profile = create(tmp_path)
    path = manager.root / profile.id / ".transaction.json"
    path.write_text('{"payloads":{}}', encoding="utf-8")
    before = contents(manager, profile)
    with pytest.raises(ValueError, match="transaction"):
        manager.load(profile.id)
    assert contents(manager, profile) == before
