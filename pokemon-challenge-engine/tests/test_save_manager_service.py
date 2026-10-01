"""Fichiers synthétiques exclusivement : aucune sauvegarde Pokémon utilisateur."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.save_manager_service import MANIFEST_NAME, SaveManagerError, SaveManagerService


@pytest.fixture
def saves(tmp_path):
    source = tmp_path / "selected.dsv"
    source.write_bytes(b"synthetic save 123\0" * 30)
    service = SaveManagerService(tmp_path / "backups")
    return source, service


def test_inspect_does_not_create_or_modify_files(saves):
    source, service = saves
    original = source.read_bytes(), source.stat().st_mtime_ns
    info = service.inspect_save(source, "white")
    assert info.exists and info.game_id == "white" and info.size == len(original[0])
    assert info.modified_at.endswith("+00:00")
    assert original == (source.read_bytes(), source.stat().st_mtime_ns)
    assert not service.root.exists()


def test_missing_save_has_explicit_missing_metadata(saves):
    source, service = saves
    info = service.inspect_save(source.with_name("absent.dsv"), "white")
    assert not info.exists and info.size is None and info.modified_at is None
    with pytest.raises(SaveManagerError, match="introuvable"):
        service.backup(info.path, "white")


@pytest.mark.parametrize("path", ["", "\0", "file.nds", "file.ds0", "file.srm"])
def test_invalid_save_paths_are_rejected(saves, path):
    _, service = saves
    with pytest.raises(ValueError):
        service.inspect_save(path, "white")


@pytest.mark.parametrize("game", ["unknown", "white_fr", "../white"])
def test_game_must_be_chosen_explicitly(saves, game):
    source, service = saves
    with pytest.raises(SaveManagerError):
        service.backup(source, game)
    assert not service.root.exists()


def test_backup_is_verified_preserves_original_and_survives_reload(saves):
    source, service = saves
    original = source.read_bytes(), source.stat().st_mtime_ns
    record = service.backup(source, "white")
    assert record.filename.startswith("white_") and record.filename.endswith(".dsv")
    assert (service.root / record.filename).read_bytes() == original[0]
    assert record.sha256 == hashlib.sha256(original[0]).hexdigest()
    assert original == (source.read_bytes(), source.stat().st_mtime_ns)
    assert SaveManagerService(service.root).list_backups("white") == (record,)
    manifest = json.loads((service.root / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert str(source) not in json.dumps(manifest)
    assert manifest["owner"] == "pokemon-challenge-engine"


def test_filename_collision_never_overwrites_existing_backup(saves):
    source, service = saves
    first = service.backup(source, "white")
    source.write_bytes(b"new synthetic save")
    second = service.backup(source, "white")
    assert first.filename != second.filename
    assert (service.root / first.filename).read_bytes() != source.read_bytes()
    assert (service.root / second.filename).read_bytes() == source.read_bytes()


@pytest.mark.parametrize("retention", [0, -1, 10001, True, 2.5, "5"])
def test_retention_validated_before_any_write(saves, retention):
    source, service = saves
    with pytest.raises(SaveManagerError, match="rétention"):
        service.backup(source, "white", retention)
    assert not service.root.exists()


@pytest.mark.parametrize("retention", [1, 5, 10, 20, 50, 7])
def test_retention_only_deletes_own_backups_of_selected_game(saves, retention):
    source, service = saves
    service.root.mkdir()
    foreign = service.root / "white_2000-01-01_00-00-00.dsv"
    foreign.write_bytes(b"not created by PCE")
    other_game = service.backup(source, "black", retention=retention)
    created = [service.backup(source, "white", retention=retention) for _ in range(retention + 2)]
    assert len(service.list_backups("white")) == retention
    assert not (service.root / created[0].filename).exists()
    assert (service.root / created[-1].filename).exists()
    assert foreign.read_bytes() == b"not created by PCE"
    assert (service.root / other_game.filename).exists()
    assert source.exists()


def test_cannot_use_backup_as_original(saves):
    source, service = saves
    record = service.backup(source, "white")
    with pytest.raises(SaveManagerError, match="extérieure"):
        service.backup(service.root / record.filename, "white")


@pytest.mark.parametrize("content", ["{", "{}", '[]', '{"owner":"x","owner":"y"}'])
def test_corrupt_manifest_blocks_writes_without_touching_original(saves, content):
    source, service = saves
    service.root.mkdir()
    manifest = service.root / MANIFEST_NAME
    manifest.write_text(content, encoding="utf-8")
    original = source.read_bytes()
    with pytest.raises(SaveManagerError, match="Manifeste"):
        service.backup(source, "white")
    assert source.read_bytes() == original
    assert manifest.read_text(encoding="utf-8") == content
    assert set(path.name for path in service.root.iterdir()) == {MANIFEST_NAME}


@pytest.mark.parametrize("filename", ["../selected.dsv", "selected.dsv", "C:/outside.dsv"])
def test_manifest_cannot_claim_arbitrary_paths(saves, filename):
    source, service = saves
    record = service.backup(source, "white")
    service._write([replace(record, filename=filename)])
    with pytest.raises(SaveManagerError, match="Manifeste"):
        service.backup(source, "white", retention=1)
    assert source.exists()


def test_tampered_backup_is_never_deleted_by_retention(saves):
    source, service = saves
    first = service.backup(source, "white")
    target = service.root / first.filename
    target.write_bytes(b"replaced externally")
    with pytest.raises(SaveManagerError, match="changé"):
        service.backup(source, "white", retention=1)
    assert target.read_bytes() == b"replaced externally"
    assert source.exists()


def test_source_changing_during_copy_is_rejected(saves):
    source, service = saves
    with patch("app.services.save_manager_service._digest", return_value="0" * 64):
        with pytest.raises(SaveManagerError, match="modifiée"):
            service.backup(source, "white")
    assert not list(service.root.glob("*.dsv"))
    assert not (service.root / MANIFEST_NAME).exists()
    assert source.exists()


def test_source_permissions_or_lock_errors_preserve_original(saves):
    source, service = saves
    original = source.read_bytes()
    with patch.object(service, "_copy_consistent", side_effect=PermissionError("locked")):
        with pytest.raises(SaveManagerError, match="verrouillé"):
            service.backup(source, "white")
    assert original == source.read_bytes()
    assert not list(service.root.iterdir())


def test_manifest_write_failure_never_publishes_partial_backup(saves):
    source, service = saves
    with patch.object(service, "_write", side_effect=PermissionError("denied")):
        with pytest.raises(SaveManagerError, match="permissions"):
            service.backup(source, "white")
    assert not list(service.root.iterdir())
    assert source.exists()


def test_atomic_manifest_replace_failure_preserves_previous_manifest(saves):
    source, service = saves
    first = service.backup(source, "white")
    manifest = service.root / MANIFEST_NAME
    original_manifest = manifest.read_bytes()
    real_replace = Path.replace

    def fail_manifest_replace(path, target):
        if path.name.startswith(".manifest_"):
            raise PermissionError("manifest locked")
        return real_replace(path, target)

    with patch.object(Path, "replace", fail_manifest_replace):
        with pytest.raises(SaveManagerError):
            service.backup(source, "white")
    assert manifest.read_bytes() == original_manifest
    assert service.list_backups() == (first,)
    assert [item.name for item in service.root.glob("*.dsv")] == [first.filename]
    assert not list(service.root.glob("*.tmp"))


def test_concurrent_backup_is_rejected_without_deleting_another_lock(saves):
    source, service = saves
    service.root.mkdir()
    lock = service.root / ".pce-backup.lock"
    lock.write_bytes(b"owned elsewhere")
    with pytest.raises(SaveManagerError, match="déjà en cours"):
        service.backup(source, "white")
    assert lock.read_bytes() == b"owned elsewhere"


def test_detected_symlink_or_junction_is_refused(saves):
    source, service = saves
    with patch.object(Path, "is_junction", return_value=True):
        with pytest.raises(SaveManagerError, match="jonctions"):
            service.backup(source, "white")
    assert not service.root.exists()


def test_slots_use_verified_ds0_to_ds9_and_only_read_metadata(tmp_path):
    (tmp_path / "Blanc FR.ds0").write_bytes(b"synthetic state")
    (tmp_path / "Blanc FR.ds9").write_bytes(b"other state")
    (tmp_path / "Blanc FR.dst").write_bytes(b"manual state ignored")
    slots = SaveManagerService.inspect_slots(tmp_path, "Blanc FR", "white")
    assert len(slots) == 10
    assert [item.slot for item in slots if item.exists] == [0, 9]
    assert slots[0].size == len(b"synthetic state")
    assert not slots[1].exists and slots[1].size is None
    assert len(list(tmp_path.iterdir())) == 3


@pytest.mark.parametrize("stem", ["", "..", "../save", "C:save", "save/other", "save\\other", "bad*stem", "trailing."])
def test_unsafe_slot_names_refused(tmp_path, stem):
    with pytest.raises(SaveManagerError):
        SaveManagerService.inspect_slots(tmp_path, stem, "white")


def test_missing_slot_directory_is_not_reported_as_empty_slots(tmp_path):
    with pytest.raises(SaveManagerError, match="introuvable"):
        SaveManagerService.inspect_slots(tmp_path / "missing", "save", "white")


@pytest.mark.parametrize("confirmed,running", [(False, False), (None, False), (1, False), (True, True), (True, None)])
def test_restore_requires_confirmation_and_closed_emulator(saves, confirmed, running):
    source, service = saves
    record = service.backup(source, "white")
    source.write_bytes(b"current")
    with pytest.raises(SaveManagerError):
        service.restore(record.filename, source, "white", confirmed=confirmed, emulator_running=running)
    assert source.read_bytes() == b"current"


def test_restore_copies_current_save_before_explicit_replacement(saves):
    source, service = saves
    saved = source.read_bytes()
    record = service.backup(source, "white")
    source.write_bytes(b"current save to preserve")
    safety = service.restore(record.filename, source, "white", confirmed=True)
    assert safety.reason == "pre_restore"
    assert (service.root / safety.filename).read_bytes() == b"current save to preserve"
    assert source.read_bytes() == saved


def test_restore_rejects_backup_of_another_game(saves):
    source, service = saves
    record = service.backup(source, "black")
    with pytest.raises(SaveManagerError, match="autre jeu"):
        service.restore(record.filename, source, "white", confirmed=True)


def test_restore_aborts_if_current_save_backup_fails(saves):
    source, service = saves
    record = service.backup(source, "white")
    source.write_bytes(b"current")
    with patch.object(service, "_backup_locked", side_effect=PermissionError("denied")):
        with pytest.raises(SaveManagerError):
            service.restore(record.filename, source, "white", confirmed=True)
    assert source.read_bytes() == b"current"
    assert not list(source.parent.glob(".pce-restore_*"))


def test_restore_rejects_tampered_backup(saves):
    source, service = saves
    original = source.read_bytes()
    record = service.backup(source, "white")
    (service.root / record.filename).write_bytes(b"corrupt")
    with pytest.raises(SaveManagerError, match="changé"):
        service.restore(record.filename, source, "white", confirmed=True)
    assert source.read_bytes() == original


def test_restore_aborts_if_target_changes_after_safety_backup(saves):
    source, service = saves
    record = service.backup(source, "white")
    source.write_bytes(b"current")
    real_backup = service._backup_locked

    def changed_after_backup(*args):
        safety = real_backup(*args)
        source.write_bytes(b"changed by another writer")
        return safety

    with patch.object(service, "_backup_locked", changed_after_backup):
        with pytest.raises(SaveManagerError, match="changé"):
            service.restore(record.filename, source, "white", confirmed=True)
    assert source.read_bytes() == b"changed by another writer"
