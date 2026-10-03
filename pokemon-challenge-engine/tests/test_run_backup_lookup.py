"""The existing backup manager isolates runs that share a game or filename."""

import pytest

from app.services.save_manager_service import SaveManagerService


def test_same_game_and_same_filename_do_not_mix_sources(tmp_path):
    service = SaveManagerService(tmp_path / "backups")
    first = tmp_path / "first" / "white.dsv"
    second = tmp_path / "second" / "white.dsv"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"first synthetic save")
    second.write_bytes(b"second synthetic save")
    expected = service.backup(first, "white")
    unrelated = service.backup(second, "white")
    assert service.list_backups_for_save(first, "white") == (expected,)
    assert service.list_backups_for_save(second, "white") == (unrelated,)
    assert service.list_backups_for_save(first, "black") == ()


def test_lookup_preserves_original_and_manifest_and_works_after_missing_original(tmp_path):
    service = SaveManagerService(tmp_path / "backups")
    source = tmp_path / "white.dsv"
    source.write_bytes(b"synthetic save")
    record = service.backup(source, "white")
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}
    assert service.list_backups_for_save(source) == (record,)
    after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}
    assert before == after
    source.unlink()  # Owned temporary fixture, never an original user save.
    assert service.list_backups_for_save(source, "white") == (record,)


def test_no_backup_directory_is_created_by_lookup(tmp_path):
    root = tmp_path / "absent"
    service = SaveManagerService(root)
    assert service.list_backups_for_save(tmp_path / "not-yet-existing.dsv", "white") == ()
    assert not root.exists()


@pytest.mark.parametrize("filename", ["save.nds", "save.ds0", "archive.zip"])
def test_lookup_rejects_non_save_reference(tmp_path, filename):
    with pytest.raises(ValueError):
        SaveManagerService(tmp_path / "backups").list_backups_for_save(tmp_path / filename, "white")
