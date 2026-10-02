"""Préférences, journal et nettoyage PCE sur données locales synthétiques."""

from copy import deepcopy
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.installation_journal import InstallationJournal
from app.services.local_storage_service import LocalStorageService
from app.services.rom_preparation_service import RomPreparationService
from app.services.setup_state import SetupStateStore
from test_auto_discovery import rom_bytes, write_zip


def test_setup_first_read_does_not_create_files(tmp_path):
    store = SetupStateStore(tmp_path)
    assert store.load() == {"schema_version": 1, "first_run_done": False, "retrobat_root": "", "games": {}}
    assert not store.path.exists()


def valid_state(store):
    state = store.load()
    state["first_run_done"] = True
    state["games"]["white"] = {
        "source_path": "source.zip", "archive_member": "Blanc.nds", "prepared_path": "Blanc.nds",
        "emulator_path": "DeSmuME.exe", "save_path": "Blanc.dsv",
        "fingerprints": {"source.zip": {"size": 123, "mtime_ns": 42, "sha256": "a" * 64}, "missing.dll": None},
    }
    return state


def test_setup_provenance_roundtrip(tmp_path):
    store = SetupStateStore(tmp_path)
    state = valid_state(store)
    assert store.save(state) == state
    assert SetupStateStore(tmp_path).load() == state


@pytest.mark.parametrize("content", [b"{bad", b"[]", b'{"schema_version":1,"schema_version":1}', b"\xff"])
def test_corrupt_setup_is_preserved_and_cannot_be_silently_overwritten(tmp_path, content):
    store = SetupStateStore(tmp_path)
    fresh = store.load()
    store.path.write_bytes(content)
    with pytest.raises(ValueError):
        store.load()
    with pytest.raises(ValueError, match="conservé"):
        store.save(fresh)
    assert store.path.read_bytes() == content


@pytest.mark.parametrize("fingerprint", [{}, {"size": True, "mtime_ns": 1, "sha256": "a" * 64},
                                         {"size": -1, "mtime_ns": 1, "sha256": "a" * 64},
                                         {"size": 10, "mtime_ns": 1, "sha256": "bad"}, []])
def test_invalid_fingerprints_cannot_be_persisted(tmp_path, fingerprint):
    store = SetupStateStore(tmp_path)
    state = valid_state(store)
    state["games"]["white"]["fingerprints"]["source.zip"] = fingerprint
    with pytest.raises(ValueError):
        store.save(state)
    assert not store.path.exists()


def test_changed_setup_in_another_instance_is_not_overwritten(tmp_path):
    first, second = SetupStateStore(tmp_path), SetupStateStore(tmp_path)
    one, two = first.load(), second.load()
    first.save(one)
    with pytest.raises(ValueError):
        second.save(two)
    assert first.load() == one


def test_setup_replace_failure_preserves_previous_content(tmp_path):
    store = SetupStateStore(tmp_path)
    state = valid_state(store)
    store.save(state)
    before = store.path.read_bytes()
    state["first_run_done"] = False
    with patch.object(Path, "replace", side_effect=PermissionError("locked")):
        with pytest.raises(PermissionError):
            store.save(state)
    assert store.path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_setup_rejects_nul_path(tmp_path):
    store = SetupStateStore(tmp_path)
    state = valid_state(store)
    state["games"]["white"]["source_path"] = "bad\0.zip"
    with pytest.raises(ValueError, match="Chemin"):
        store.save(state)


def test_journal_records_structured_local_events(tmp_path):
    journal = InstallationJournal(tmp_path)
    assert journal.recent() == [] and not journal.path.exists()
    journal("rom_detected", source="Blanc.nds", game="white")
    record = journal.recent()[0]
    assert record["event"] == "rom_detected" and record["details"]["game"] == "white"
    assert set(record) == {"time", "event", "details"}


def test_journal_partial_line_is_preserved_without_breaking_future_events(tmp_path):
    journal = InstallationJournal(tmp_path)
    journal("rom_detected", game="white")
    with journal.path.open("ab") as handle:
        handle.write(b'{"partial":')
    journal("configuration_ready", game="white")
    events = journal.recent()
    assert [event["event"] for event in events] == ["rom_detected", "configuration_ready", "journal_warning"]
    assert b'{"partial":' in journal.path.read_bytes()
    assert journal.warnings


def test_journal_rotation_is_bounded(tmp_path):
    journal = InstallationJournal(tmp_path)
    journal.path.parent.mkdir(parents=True)
    journal.path.write_bytes(b"x" * 5_000_001)
    journal("configuration_ready")
    assert journal.path.stat().st_size < 1000
    assert journal.path.with_name("events.previous.jsonl").stat().st_size == 5_000_001


@pytest.mark.parametrize("event", ["", "bad event", "EVENT", "x" * 101, None])
def test_invalid_journal_event_names_are_refused(tmp_path, event):
    journal = InstallationJournal(tmp_path)
    with pytest.raises(ValueError):
        journal(event)
    assert not journal.path.exists()


def test_journal_event_size_is_bounded_by_utf8_bytes(tmp_path):
    journal = InstallationJournal(tmp_path)
    with pytest.raises(ValueError, match="volumineux"):
        journal("large_event", detail="é" * 40000)


def test_journal_permission_failure_is_not_reported_as_success(tmp_path):
    journal = InstallationJournal(tmp_path)
    with patch.object(Path, "mkdir", side_effect=PermissionError("denied")):
        with pytest.raises(PermissionError):
            journal("configuration_ready")


def create_cached_rom(tmp_path):
    source = write_zip(tmp_path / "Blanc.zip", {"Blanc.nds": rom_bytes()})
    result = RomPreparationService(tmp_path / "runtime" / "extracted-roms").prepare(source)
    return source, result


def test_cleanup_needs_confirmation_and_preserves_originals_profiles_saves_backups(tmp_path):
    source, cached = create_cached_rom(tmp_path)
    protected = []
    for folder in ("profiles", "saves", "backups"):
        path = tmp_path / folder / "keep.dsv"
        path.parent.mkdir()
        path.write_bytes(b"keep")
        protected.append(path)
    service = LocalStorageService(tmp_path)
    with pytest.raises(ValueError, match="confirmation"):
        service.cleanup("extracted_roms")
    assert cached.path.exists()
    summary = service.summary()
    assert summary["items"][0]["count"] == 1
    result = service.cleanup("extracted_roms", confirmed=True)
    assert result["count"] == 1 and not cached.path.exists()
    assert source.exists() and all(path.read_bytes() == b"keep" for path in protected)


@pytest.mark.parametrize("change", ["foreign_file", "tampered_rom", "corrupt_manifest", "wrong_hash"])
def test_cleanup_does_not_claim_unknown_or_modified_cache_files(tmp_path, change):
    source, cached = create_cached_rom(tmp_path)
    if change == "foreign_file":
        (cached.path.parent / "user.txt").write_text("keep", encoding="utf-8")
    elif change == "tampered_rom":
        cached.path.write_bytes(b"changed")
    elif change == "corrupt_manifest":
        cached.manifest_path.write_bytes(b"{bad")
    else:
        data = json.loads(cached.manifest_path.read_text(encoding="utf-8"))
        data["member_sha256"] = "0" * 64
        cached.manifest_path.write_text(json.dumps(data), encoding="utf-8")
    assert LocalStorageService(tmp_path).cleanup("extracted_roms", confirmed=True)["count"] == 0
    assert cached.path.exists() and source.exists()


def stopped_session(tmp_path, name="a" * 32):
    folder = tmp_path / "runtime" / "bridge" / name
    folder.mkdir(parents=True)
    (folder / "connect.lua").write_text("-- Charger ce fichier dans DeSmuME > Tools > Lua Scripting.\n", encoding="utf-8")
    (folder / "config.lua").write_text("-- Configuration locale générée ; ne pas versionner.\nreturn {}\n", encoding="utf-8")
    (folder / "stop").touch()
    (folder / "sequence.txt").write_text("2", encoding="utf-8")
    (folder / "pending-0000000002.txt").write_text("", encoding="utf-8")
    (folder / "snapshot-0000000002.json").write_text("{}", encoding="utf-8")
    return folder


def test_real_session_filename_layout_can_be_cleaned(tmp_path):
    folder = stopped_session(tmp_path)
    assert LocalStorageService(tmp_path).cleanup("sessions", confirmed=True)["count"] == 1
    assert not folder.exists()


def test_active_session_is_never_cleaned_even_with_stop_marker(tmp_path):
    folder = stopped_session(tmp_path)
    assert LocalStorageService(tmp_path).cleanup("sessions", confirmed=True, active_session=str(folder))["count"] == 0
    assert folder.exists()


@pytest.mark.parametrize("extra", ["observation-0000000002.json", "my_save.dsv", "unexpected.txt"])
def test_pending_events_and_foreign_files_preserve_stopped_session(tmp_path, extra):
    folder = stopped_session(tmp_path)
    (folder / extra).write_text("keep", encoding="utf-8")
    assert LocalStorageService(tmp_path).cleanup("sessions", confirmed=True)["count"] == 0
    assert (folder / extra).exists()


def test_session_without_stop_marker_is_preserved(tmp_path):
    folder = stopped_session(tmp_path)
    (folder / "stop").unlink()
    assert LocalStorageService(tmp_path).cleanup("sessions", confirmed=True)["count"] == 0
    assert folder.exists()


def test_cleanup_rechecks_file_signature_after_confirmation_record(tmp_path):
    source, cached = create_cached_rom(tmp_path)

    def change(event, **details):
        if event == "storage_cleanup_requested":
            cached.path.write_bytes(b"changed externally")

    with pytest.raises(ValueError, match="changé"):
        LocalStorageService(tmp_path, change).cleanup("extracted_roms", confirmed=True)
    assert cached.path.read_bytes() == b"changed externally" and source.exists()


def test_cleanup_permission_error_preserves_remaining_files(tmp_path):
    source, cached = create_cached_rom(tmp_path)
    with patch.object(Path, "unlink", side_effect=PermissionError("locked")):
        with pytest.raises(PermissionError):
            LocalStorageService(tmp_path).cleanup("extracted_roms", confirmed=True)
    assert source.exists() and cached.path.exists()


def test_cleanup_detects_replaced_file_even_with_preserved_size_and_timestamp(tmp_path):
    source, cached = create_cached_rom(tmp_path)
    before = cached.path.stat()
    replacement = tmp_path / "replacement.nds"
    replacement.write_bytes(b"changed".ljust(before.st_size, b"!"))
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    events = []

    def replace_after_confirmation(event, **details):
        events.append((event, details))
        if event == "storage_cleanup_requested":
            replacement.replace(cached.path)

    with pytest.raises(ValueError, match="changé"):
        LocalStorageService(tmp_path, replace_after_confirmation).cleanup("extracted_roms", confirmed=True)
    assert cached.path.read_bytes().startswith(b"changed") and source.exists()
    assert events[-1][0] == "storage_cleanup_failed" and events[-1][1]["removed"] == []


@pytest.mark.parametrize("filename", ["connect.lua", "config.lua"])
def test_unreadable_script_is_preserved_without_breaking_storage_summary(tmp_path, filename):
    folder = stopped_session(tmp_path)
    (folder / filename).write_bytes(b"\xff\xfeinvalid UTF8")
    service = LocalStorageService(tmp_path)
    assert next(item for item in service.summary()["items"] if item["kind"] == "sessions")["count"] == 0
    assert service.cleanup("sessions", confirmed=True)["count"] == 0
    assert (folder / filename).read_bytes() == b"\xff\xfeinvalid UTF8"


def test_partial_cleanup_failure_is_journalled_without_deleting_remaining_files(tmp_path):
    source, cached = create_cached_rom(tmp_path)
    original_unlink = Path.unlink
    events = []

    def deny_manifest(path, *args, **kwargs):
        if path == cached.manifest_path:
            raise PermissionError("manifest locked")
        return original_unlink(path, *args, **kwargs)

    with patch.object(Path, "unlink", deny_manifest):
        with pytest.raises(PermissionError, match="locked"):
            LocalStorageService(tmp_path, lambda event, **details: events.append((event, details))).cleanup(
                "extracted_roms", confirmed=True)
    assert source.exists() and cached.manifest_path.exists()
    assert events[-1][0] == "storage_cleanup_failed"
    assert events[-1][1]["removed"] == [str(cached.path)]


def test_all_local_storage_services_refuse_junction_paths(tmp_path):
    with patch.object(Path, "is_junction", return_value=True):
        for factory in (SetupStateStore, InstallationJournal, LocalStorageService):
            with pytest.raises(ValueError, match="jonction"):
                factory(tmp_path)
