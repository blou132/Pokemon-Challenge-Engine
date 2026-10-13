"""A confirmed removal owns one UUID directory, never a referenced game source."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

from app.core.run_manager import RunManager
from app.models.run import history_event, utc_now
from app.services.run_deletion_service import RunDeletionService


def owned_files(manager, run):
    folder = manager.root / run.run_id
    for name, content in (("game/white.nds", b"synthetic run ROM"),
                          ("saves/white.dsv", b"synthetic run save"),
                          ("states/white.ds0", b"synthetic state"),
                          ("backups/white.dsv", b"synthetic backup")):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return folder


def snapshot(folder):
    return {str(path.relative_to(folder)): path.read_bytes() for path in folder.rglob("*") if path.is_file()}


def test_delete_one_independent_run_preserves_other_source_save_and_profiles(tmp_path):
    source, save, backup = (tmp_path / name for name in ("original.nds", "original.dsv", "old-backup.dsv"))
    for path in (source, save, backup):
        path.write_bytes(b"user-owned original")
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "template.json").write_bytes(b"original template")
    manager = RunManager(tmp_path / "runs")
    first = manager.create("Blanc classique", "white", save_path=str(save),
                           launch_profile={"rom_path": str(source), "_source": {"source_path": str(source)}})
    first.history.append(history_event("backup_created", "system", {"path": str(backup)}))
    manager.save(first)
    second = manager.create("Blanc Nuzlocke", "white")
    a, b = owned_files(manager, first), owned_files(manager, second)
    other_before, profiles_before = snapshot(b), snapshot(profiles)
    service = RunDeletionService(manager)
    plan = service.preview(first.run_id)
    assert set(plan.files) == {"run.json", "game/white.nds", "saves/white.dsv", "states/white.ds0", "backups/white.dsv"}
    assert plan.total_bytes == sum(len(content) for content in snapshot(a).values())
    assert set(plan.preserved_references) == {str(source), str(save), str(backup)}
    service.delete(plan)
    assert not a.exists()
    assert snapshot(b) == other_before and snapshot(profiles) == profiles_before
    assert manager.load(second.run_id).name == "Blanc Nuzlocke"
    assert all(path.read_bytes() == b"user-owned original" for path in (source, save, backup))


def test_empty_run_and_archived_run_can_be_deleted(tmp_path):
    manager = RunManager(tmp_path)
    run = manager.create("Archived", "white")
    manager.update(run.run_id, lambda value: setattr(value, "status", "archived"))
    service = RunDeletionService(manager)
    plan = service.preview(run.run_id)
    assert plan.files == ("run.json",)
    assert plan.name == "Archived"
    service.delete(plan)
    assert manager.list_runs() == []


def test_process_surviving_pce_closure_blocks_removal_before_touching_files(tmp_path):
    manager = RunManager(tmp_path / "runs")
    run = manager.create("Still running", "white", launch_profile={"emulator_path": "owned.exe"})
    folder = owned_files(manager, run)
    before = snapshot(folder)
    running = [False]
    service = RunDeletionService(manager, running_probe=lambda executable: running[0])
    plan = service.preview(run.run_id)
    running[0] = True
    with pytest.raises(ValueError, match="Fermez DeSmuME"):
        service.preview(run.run_id)
    with pytest.raises(ValueError, match="Fermez DeSmuME"):
        service.delete(plan)
    assert snapshot(folder) == before


@pytest.mark.parametrize("run_id", ["../outside", "", "C:/outside", "123456781234123412341234567890ab"])
def test_noncanonical_run_id_refused(tmp_path, run_id):
    with pytest.raises(ValueError, match="UUID"):
        RunDeletionService(RunManager(tmp_path)).preview(run_id)


def test_selected_run_requires_tracker_deactivation_even_without_observation(tmp_path):
    manager = RunManager(tmp_path)
    run = manager.create("Selected", "white")
    service = RunDeletionService(manager)
    plan = service.preview(run.run_id)
    manager.set_active_id(run.run_id)
    with pytest.raises(ValueError, match="Arrêtez la session"):
        service.preview(run.run_id)
    with pytest.raises(ValueError, match="Arrêtez la session"):
        service.delete(plan)
    assert manager.load(run.run_id).name == "Selected"


def test_open_session_refused_even_without_active_selection(tmp_path):
    manager = RunManager(tmp_path)
    run = manager.create("Session", "white")
    stamp = utc_now()
    run.sessions.append({"session_id": str(uuid4()), "started_at": stamp, "last_heartbeat": stamp,
                         "ended_at": None, "duration": 0.0})
    manager.save(run)
    with pytest.raises(ValueError, match="Arrêtez la session"):
        RunDeletionService(manager).preview(run.run_id)


def test_other_active_selection_is_preserved(tmp_path):
    manager = RunManager(tmp_path)
    first, second = manager.create("First", "white"), manager.create("Second", "white")
    manager.set_active_id(second.run_id)
    before = (tmp_path / "active.json").read_bytes()
    service = RunDeletionService(manager)
    service.delete(service.preview(first.run_id))
    assert manager.active_id == second.run_id
    assert (tmp_path / "active.json").read_bytes() == before


@pytest.mark.parametrize("change", ["new_file", "changed_file", "removed_file", "renamed_run", "same_size_preserved_mtime"])
def test_changed_inventory_requires_new_confirmation(tmp_path, change):
    manager = RunManager(tmp_path)
    run = manager.create("First", "white")
    folder = owned_files(manager, run)
    service = RunDeletionService(manager)
    plan = service.preview(run.run_id)
    path = folder / "saves/white.dsv"
    if change == "new_file":
        (folder / "additional.txt").write_text("review this too", encoding="utf-8")
    elif change == "changed_file":
        path.write_bytes(b"a new save")
    elif change == "removed_file":
        path.unlink()
    elif change == "renamed_run":
        manager.update(run.run_id, lambda value: setattr(value, "name", "Changed"))
    else:
        before = path.stat()
        path.write_bytes(b"x" * before.st_size)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    remaining = snapshot(folder)
    with pytest.raises(ValueError, match="changé depuis la confirmation"):
        service.delete(plan)
    assert snapshot(folder) == remaining


def test_plan_cannot_be_forged_or_used_in_another_root(tmp_path):
    manager = RunManager(tmp_path / "first")
    run = manager.create("First", "white")
    service = RunDeletionService(manager)
    plan = service.preview(run.run_id)
    with pytest.raises(ValueError, match="confirmation"):
        service.delete(replace(plan, entries=(), token="approved"))
    other_root = tmp_path / "second"
    (other_root / run.run_id).mkdir(parents=True)
    (other_root / run.run_id / "run.json").write_bytes((manager.root / run.run_id / "run.json").read_bytes())
    with pytest.raises(ValueError, match="confirmation"):
        RunDeletionService(RunManager(other_root)).delete(plan)
    assert manager.load(run.run_id).name == "First"


def test_invalid_manifest_ownership_is_refused(tmp_path):
    manager = RunManager(tmp_path)
    run = manager.create("First", "white")
    path = tmp_path / run.run_id / "run.json"
    data = run.to_dict()
    data["run_id"] = str(uuid4())
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="dossier"):
        RunDeletionService(manager).preview(run.run_id)
    assert path.is_file()


def test_other_run_referencing_target_file_blocks_deletion(tmp_path):
    manager = RunManager(tmp_path)
    first = manager.create("First", "white")
    folder = owned_files(manager, first)
    manager.create("Legacy shared save", "white", save_path=str(folder / "saves/white.dsv"))
    before = snapshot(folder)
    with pytest.raises(ValueError, match="autre partie utilise"):
        RunDeletionService(manager).preview(first.run_id)
    assert snapshot(folder) == before


def test_corrupt_other_run_blocks_unknown_shared_reference(tmp_path):
    manager = RunManager(tmp_path)
    first, second = manager.create("First", "white"), manager.create("Second", "white")
    (tmp_path / second.run_id / "run.json").write_bytes(b"invalid data")
    with pytest.raises(ValueError, match="illisibles"):
        RunDeletionService(manager).preview(first.run_id)
    assert manager.load(first.run_id).name == "First"


def test_hard_link_to_external_save_is_refused(tmp_path):
    source = tmp_path / "external.dsv"
    source.write_bytes(b"external save")
    manager = RunManager(tmp_path / "runs")
    run = manager.create("First", "white")
    os.link(source, manager.root / run.run_id / "linked.dsv")
    with pytest.raises(ValueError, match="lien physique"):
        RunDeletionService(manager).preview(run.run_id)
    assert source.read_bytes() == b"external save"


def test_directory_link_never_traversed_or_deleted(tmp_path):
    source = tmp_path / "external"
    source.mkdir()
    (source / "original.dsv").write_bytes(b"external save")
    manager = RunManager(tmp_path / "runs")
    run = manager.create("First", "white")
    link = manager.root / run.run_id / "linked"
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(source)], capture_output=True)
        assert result.returncode == 0
    else:
        link.symlink_to(source, target_is_directory=True)
    try:
        with pytest.raises(ValueError, match="lien ou jonction"):
            RunDeletionService(manager).preview(run.run_id)
        assert (source / "original.dsv").read_bytes() == b"external save"
    finally:
        if os.name == "nt":
            link.rmdir()
        else:
            link.unlink()


def test_inventory_limit_fails_without_any_deletion(tmp_path, monkeypatch):
    manager = RunManager(tmp_path)
    run = manager.create("First", "white")
    before = snapshot(tmp_path / run.run_id)
    monkeypatch.setattr("app.services.run_deletion_service.MAX_DELETE_ENTRIES", 1)
    with pytest.raises(ValueError, match="trop de fichiers"):
        RunDeletionService(manager).preview(run.run_id)
    assert snapshot(tmp_path / run.run_id) == before


def test_filesystem_failure_keeps_manifest_and_remaining_files(tmp_path, monkeypatch):
    manager = RunManager(tmp_path)
    run = manager.create("First", "white")
    folder = owned_files(manager, run)
    service = RunDeletionService(manager)
    plan = service.preview(run.run_id)
    unlink = Path.unlink
    def fail_save(path, *args, **kwargs):
        if path.name == "white.dsv" and path.parent.name == "saves":
            raise PermissionError("file in use")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_save)
    with pytest.raises(ValueError, match="interrompue"):
        service.delete(plan)
    assert manager.load(run.run_id).name == "First"
    assert (folder / "saves/white.dsv").read_bytes() == b"synthetic run save"
    assert (folder / "states/white.ds0").read_bytes() == b"synthetic state"


def test_old_writer_cannot_recreate_deleted_run(tmp_path):
    manager = RunManager(tmp_path)
    run = manager.create("First", "white")
    stale = manager.load(run.run_id)
    service = RunDeletionService(manager)
    service.delete(service.preview(run.run_id))
    stale.name = "Recreated"
    with pytest.raises(ValueError, match="absent"):
        manager.save(stale)
    assert not (tmp_path / run.run_id).exists()
