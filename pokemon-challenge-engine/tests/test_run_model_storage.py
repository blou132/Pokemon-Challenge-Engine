"""Persistent runs never borrow mutable profile progression or game save files."""

from copy import deepcopy
import json
from pathlib import Path
from uuid import UUID

import pytest

from app.core.profile_manager import ProfileManager
from app.core.run_manager import RunManager
from app.models.challenge import Challenge
from app.models.run import Run, RUN_STATUSES


def challenge(rules=None):
    return Challenge("white", "custom", rules or ["nuzlocke", "permanent_death"], {},
                     {"enforcement": "soft", "rule_parameters": {}}, None, 42)


def test_classic_run_uuid_unknown_counters_and_no_profile(tmp_path):
    manager = RunManager(tmp_path / "runs")
    run = manager.create("Blanc classique", "white")
    assert str(UUID(run.run_id)) == run.run_id
    assert run.schema_version == 1 and run.rules_snapshot["active_rules"] == []
    assert run.profile_id is None and run.badges is None and run.captures is None and run.deaths is None
    assert run.death_count is None and run.status == "preparing"
    assert manager.load(run.run_id) == run
    assert (tmp_path / "runs" / run.run_id / "run.json").is_file()


def test_profile_rules_snapshot_and_original_progress_are_independent(tmp_path):
    profiles = ProfileManager(tmp_path / "profiles")
    profile = profiles.create("Nuzlocke", challenge())
    original_progress = (tmp_path / "profiles" / profile.id / "progress.json").read_bytes()
    original_history = (tmp_path / "profiles" / profile.id / "history.json").read_bytes()
    manager = RunManager(tmp_path / "runs")
    run = manager.create("Blanc 1", "white", challenge=profile.challenge, profile_id=profile.id, preset="classic_nuzlocke")
    original_snapshot = deepcopy(run.rules_snapshot)
    profile.challenge.active_rules.clear()
    profiles.save(profile)
    assert manager.load(run.run_id).rules_snapshot == original_snapshot
    assert (tmp_path / "profiles" / profile.id / "progress.json").read_bytes() == original_progress
    assert (tmp_path / "profiles" / profile.id / "history.json").read_bytes() == original_history
    assert run.seed == 42 and run.profile_id == profile.id


def test_caller_dictionary_cannot_modify_snapshot(tmp_path):
    data = challenge().to_dict()
    manager = RunManager(tmp_path)
    run = manager.create("A", "white", challenge=data)
    data["active_rules"].clear()
    assert run.active_rules == ("nuzlocke", "permanent_death")


@pytest.mark.parametrize("field,value", [("rules_snapshot", None), ("seed", 99), ("profile_id", "different"),
                                         ("generation", 6), ("preset", "different")])
def test_existing_run_snapshot_metadata_is_immutable(tmp_path, field, value):
    manager = RunManager(tmp_path)
    run = manager.create("A", "white")
    before = (tmp_path / run.run_id / "run.json").read_bytes()
    if field == "rules_snapshot":
        run.rules_snapshot["active_rules"] = ["nuzlocke"]
    else:
        setattr(run, field, value)
    with pytest.raises(ValueError):
        manager.save(run)
    assert (tmp_path / run.run_id / "run.json").read_bytes() == before


def test_reopen_launch_reference_and_unknown_future_generation(tmp_path):
    manager = RunManager(tmp_path)
    run = manager.create("Future", "future_game", generation=10, save_path="C:/isolated/game.dsv",
                         launch_profile={"emulator_path": "C:/isolated/emu.exe", "_source": {"archive": "source.zip"}})
    manager.set_active_id(run.run_id)
    reopened = RunManager(tmp_path)
    assert reopened.active_id == run.run_id
    assert reopened.load(run.run_id) == run


@pytest.mark.parametrize("status", sorted(RUN_STATUSES))
def test_status_storage(tmp_path, status):
    manager = RunManager(tmp_path)
    run = manager.create("A", "white")
    run.status = status
    manager.save(run)
    assert manager.load(run.run_id).status == status


@pytest.mark.parametrize("run_id", ["../outside", "C:/outside", "", "0", "123456781234123412341234567890ab"])
def test_identifier_cannot_escape_run_root(tmp_path, run_id):
    with pytest.raises(ValueError):
        RunManager(tmp_path).load(run_id)


@pytest.mark.parametrize("field,value", [("schema_version", True), ("schema_version", 2), ("generation", True),
                                         ("status", "lost"), ("total_play_seconds", float("inf")),
                                         ("badges", False), ("created_at", "2026-10-03"), ("name", " ")])
def test_invalid_schema_is_rejected(tmp_path, field, value):
    raw = RunManager(tmp_path).create("A", "white").to_dict()
    raw[field] = value
    with pytest.raises(ValueError):
        Run.from_dict(raw)


def test_concurrent_stale_writer_refused(tmp_path):
    first = RunManager(tmp_path)
    run = first.create("A", "white")
    second = RunManager(tmp_path)
    stale = second.load(run.run_id)
    run.name = "New name"
    first.save(run)
    stale.name = "Stale name"
    with pytest.raises(ValueError, match="autre instance"):
        second.save(stale)
    assert first.load(run.run_id).name == "New name"


def test_library_refresh_cannot_reauthorize_stale_active_object(tmp_path):
    manager = RunManager(tmp_path)
    stale = manager.create("Old", "white")
    other = RunManager(tmp_path)
    changed = other.load(stale.run_id)
    changed.name = "External edit"
    other.save(changed)
    assert manager.list_runs()[0].name == "External edit"
    stale.name = "Lost update"
    with pytest.raises(ValueError, match="autre instance"):
        manager.save(stale)
    assert manager.load(stale.run_id).name == "External edit"


def test_storage_revision_is_not_part_of_the_run_schema(tmp_path):
    manager = RunManager(tmp_path)
    run = manager.create("A", "white")
    assert run._storage_revision
    assert "_storage_revision" not in run.to_dict()
    detached = Run.from_dict(run.to_dict())
    with pytest.raises(ValueError, match="autre instance"):
        manager.save(detached)


def test_active_pointer_conflict_refuses_silent_switch(tmp_path):
    first, second = RunManager(tmp_path), RunManager(tmp_path)
    a, b = first.create("A", "white"), first.create("B", "white")
    assert second.active_id is None
    first.set_active_id(a.run_id)
    with pytest.raises(ValueError, match="autre instance"):
        second.set_active_id(b.run_id)
    assert first.active_id == a.run_id


def test_atomic_replace_failure_preserves_previous_file_and_cleans_temp(tmp_path, monkeypatch):
    manager = RunManager(tmp_path)
    run = manager.create("A", "white")
    path = tmp_path / run.run_id / "run.json"
    original = path.read_bytes()
    run.name = "B"
    def fail(*args, **kwargs):
        raise OSError("locked")
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        manager.save(run)
    assert path.read_bytes() == original
    assert list(path.parent.glob(".run-*.tmp")) == []


def test_corrupt_data_preserved_and_library_reports_warning(tmp_path):
    manager = RunManager(tmp_path)
    run = manager.create("A", "white")
    path = tmp_path / run.run_id / "run.json"
    path.write_bytes(b'{"schema_version":1,"schema_version":1}')
    assert manager.list_runs() == [] and manager.warnings
    with pytest.raises(ValueError):
        manager.save(run)
    assert path.read_bytes() == b'{"schema_version":1,"schema_version":1}'


def test_run_file_cannot_claim_other_directory(tmp_path):
    manager = RunManager(tmp_path)
    a, b = manager.create("A", "white"), manager.create("B", "white")
    path = tmp_path / a.run_id / "run.json"
    payload = a.to_dict()
    payload["run_id"] = b.run_id
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="dossier"):
        manager.load(a.run_id)


def test_update_uses_current_run_and_never_touches_save(tmp_path):
    original = tmp_path / "pokemon.dsv"
    original.write_bytes(b"not a real save: preserve exactly")
    manager = RunManager(tmp_path / "runs")
    run = manager.create("A", "white", save_path=str(original))
    manager.update(run.run_id, lambda item: setattr(item, "name", "Renamed"))
    assert manager.load(run.run_id).name == "Renamed"
    assert original.read_bytes() == b"not a real save: preserve exactly"


def test_twenty_runs_are_distinct_and_survive_independent_reopen(tmp_path):
    manager = RunManager(tmp_path)
    ids = {manager.create(f"Run {number}", "white").run_id for number in range(20)}
    assert {run.run_id for run in RunManager(tmp_path).list_runs()} == ids


def test_history_source_and_order_validated(tmp_path):
    data = RunManager(tmp_path).create("A", "white").to_dict()
    data["history"][0]["source"] = "synthetic_claimed_real"
    with pytest.raises(ValueError):
        Run.from_dict(data)


def test_session_total_cannot_invent_offline_time(tmp_path):
    data = RunManager(tmp_path).create("A", "white").to_dict()
    data["total_play_seconds"] = 28800
    with pytest.raises(ValueError, match="incohérent"):
        Run.from_dict(data)
