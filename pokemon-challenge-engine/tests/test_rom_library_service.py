"""Personal library tests use synthetic bytes and an explicitly isolated root."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import stat
import zipfile

import pytest

from app.services import rom_library_service as library
from app.services.rom_library_service import RomLibraryService, inspect_library_source


def rom_bytes(code="IRAF", revision=0, marker=0):
    data = bytearray(8192)
    data[12:16] = code.encode("ascii")
    data[30] = revision
    data[-1] = marker
    return bytes(data)


def rom(tmp_path, code="IRAF", revision=0, marker=0, name="source.nds"):
    path = tmp_path / name
    path.write_bytes(rom_bytes(code, revision, marker))
    return path


@pytest.fixture
def service(tmp_path):
    return RomLibraryService(tmp_path / "isolated-library")


def test_default_location_survives_workdir_and_build_changes(tmp_path, monkeypatch):
    local = tmp_path / "personal-appdata"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    first = library.default_library_root()
    build = tmp_path / "new-build"
    build.mkdir()
    monkeypatch.chdir(build)
    second = RomLibraryService()
    assert first == second.root == local / "Pokemon-Challenge-Engine" / "library"
    assert not local.exists()
    assert second.list_entries() == ()
    assert not local.exists()


def test_relative_environment_store_is_refused(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "build/user-data")
    with pytest.raises(ValueError, match="absolu"):
        library.default_library_root()


@pytest.mark.parametrize("code,game,generation,revision", [
    ("ADAF", "diamond", 4, 5), ("APAF", "pearl", 4, 5), ("CPUF", "platinum", 4, 0),
    ("IPKF", "heartgold", 4, 0), ("IPGF", "soulsilver", 4, 0),
    ("IRBF", "black", 5, 0), ("IRAF", "white", 5, 0),
    ("IREF", "black2", 5, 0), ("IRDF", "white2", 5, 0),
])
def test_all_nine_games_identified_from_header_not_filename(tmp_path, service, code, game, generation, revision):
    source = rom(tmp_path, code, revision, name="misleading-pokemon-name.nds")
    actual = inspect_library_source(source)
    assert (actual.game_id, actual.generation, actual.revision, actual.region) == (game, generation, revision, "FR")
    result = service.import_source(actual)
    assert result.imported
    assert result.entry.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert service.resolve(game).read_bytes() == source.read_bytes()
    assert service.verify()[0].valid


def test_import_is_independent_idempotent_and_survives_source_removal(tmp_path, service):
    source = rom(tmp_path)
    source_before = source.read_bytes()
    first = service.import_source(source)
    master = service.master_path(first.entry)
    manifest = service.manifest_path.read_bytes()
    master_stat = master.stat()
    assert master.stat().st_ino != source.stat().st_ino
    second = service.import_source(source)
    assert second.entry == first.entry and not second.imported
    assert service.manifest_path.read_bytes() == manifest
    assert master.stat().st_mtime_ns == master_stat.st_mtime_ns
    assert source.read_bytes() == source_before
    source.unlink()
    reopened = RomLibraryService(service.root)
    assert reopened.resolve("white").read_bytes() == source_before
    assert reopened.resolve("black") is None


def test_run_copies_and_run_deletion_leave_library_intact(tmp_path, service):
    source = rom(tmp_path)
    entry = service.import_source(source).entry
    master = service.resolve("white")
    for number in (1, 2):
        run = tmp_path / f"run-{number}"
        run.mkdir()
        shutil.copyfile(master, run / "game.nds")
        (run / "save.sav").write_bytes(bytes([number]))
    (tmp_path / "run-1" / "game.nds").write_bytes(b"derived-only")
    shutil.rmtree(tmp_path / "run-1")
    assert (tmp_path / "run-2" / "game.nds").read_bytes() == source.read_bytes()
    assert (tmp_path / "run-2" / "save.sav").read_bytes() == b"\x02"
    assert service.resolve("white") == master
    assert service.list_entries() == (entry,)


def test_zip_import_streams_only_unique_member_and_preserves_archive(tmp_path, service):
    archive = tmp_path / "personal.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("subfolder/renamed.nds", rom_bytes("IPKF"))
        zipped.writestr("description.txt", "metadata")
    before = archive.read_bytes()
    source = inspect_library_source(archive)
    assert source.archive_member == "subfolder/renamed.nds"
    assert source.source_sha256 == hashlib.sha256(before).hexdigest()
    result = service.import_source(source)
    assert service.resolve("heartgold").read_bytes() == rom_bytes("IPKF")
    assert not (service.root / "subfolder").exists()
    assert archive.read_bytes() == before
    assert not service.import_source(archive).imported


@pytest.mark.parametrize("member", ["../escape.nds", "/absolute.nds", "dir\\ambiguous.nds"])
def test_zip_path_attacks_rejected_without_writing(tmp_path, service, member):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        info = zipfile.ZipInfo("placeholder.nds")
        # ZipInfo normally normalizes backslashes on Windows; set the raw ZIP
        # member explicitly to exercise a genuinely ambiguous input archive.
        info.filename = member
        info.orig_filename = member
        zipped.writestr(info, rom_bytes())
    with pytest.raises(ValueError):
        service.import_source(archive)
    assert not service.root.exists()


def test_zip_links_and_multiple_roms_rejected(tmp_path, service):
    archive = tmp_path / "ambiguous.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("one.nds", rom_bytes())
        zipped.writestr("two.nds", rom_bytes("IRBF"))
    with pytest.raises(ValueError, match="seule ROM"):
        service.import_source(archive)
    with zipfile.ZipFile(archive, "w") as zipped:
        info = zipfile.ZipInfo("link.nds")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(info, rom_bytes())
    with pytest.raises(ValueError, match="Liens"):
        service.import_source(archive)


def test_zip_member_with_directory_mode_cannot_masquerade_as_regular_rom(tmp_path, service):
    archive = tmp_path / "wrong-mode.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        info = zipfile.ZipInfo("not-a-file.nds")
        info.create_system = 3
        info.external_attr = (stat.S_IFDIR | 0o755) << 16
        zipped.writestr(info, rom_bytes())
    with pytest.raises(ValueError, match="régulier"):
        service.import_source(archive)
    assert not service.root.exists()


def test_corrupt_zip_crc_is_rejected_before_import(tmp_path, service):
    archive = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zipped:
        zipped.writestr("game.nds", rom_bytes())
    content = bytearray(archive.read_bytes())
    content[30 + len("game.nds") + 100] ^= 1
    archive.write_bytes(content)
    with pytest.raises(ValueError, match="corrompue"):
        service.import_source(archive)
    assert not service.root.exists()


def test_empty_directory_does_not_create_a_library(tmp_path, service):
    sources = tmp_path / "empty-sources"
    sources.mkdir()
    assert service.import_directory(sources) == ()
    assert not service.root.exists()


def test_conflicting_revision_never_replaces_master(tmp_path, service):
    original = rom(tmp_path)
    entry = service.import_source(original).entry
    conflicting = rom(tmp_path, revision=1, name="other.nds")
    before = service.manifest_path.read_bytes()
    with pytest.raises(ValueError, match="Conflit"):
        service.import_source(conflicting)
    assert service.manifest_path.read_bytes() == before
    assert service.master_path(entry).read_bytes() == original.read_bytes()


def test_directory_preflight_refuses_conflicting_sources_before_any_import(tmp_path, service):
    sources = tmp_path / "sources"
    sources.mkdir()
    rom(sources, name="one.nds")
    rom(sources, marker=2, name="two.nds")
    with pytest.raises(ValueError, match="Conflit"):
        service.import_directory(sources)
    assert not service.root.exists()


def test_duplicate_identical_sources_count_as_one_master(tmp_path, service):
    sources = tmp_path / "sources"
    sources.mkdir()
    rom(sources, name="one.nds")
    rom(sources, name="two.nds")
    (sources / "ignored.txt").write_text("not a ROM")
    result = service.import_directory(sources)
    assert [item.imported for item in result] == [True, False]
    assert len(service.list_entries()) == 1
    assert len(tuple(service.root.rglob("*.nds"))) == 1


def test_source_changed_after_scan_is_rejected(tmp_path, service):
    source = rom(tmp_path)
    scanned = inspect_library_source(source)
    source.write_bytes(rom_bytes(marker=42))
    with pytest.raises(ValueError, match="depuis son inventaire"):
        service.import_source(scanned)
    assert not service.root.exists()


def test_source_changed_during_copy_leaves_no_master(tmp_path, service, monkeypatch):
    source = rom(tmp_path)
    original = library._read_rom

    def mutate_after_read(reader, size, writer=None):
        result = original(reader, size, writer)
        if writer is not None:
            source.write_bytes(rom_bytes(marker=42))
        return result

    monkeypatch.setattr(library, "_read_rom", mutate_after_read)
    with pytest.raises(ValueError, match="pendant la copie"):
        service.import_source(source)
    assert not service.manifest_path.exists()
    assert not tuple(service.root.rglob("*.nds"))
    assert not tuple(service.root.rglob(".import-*.tmp"))


def test_corrupt_master_is_refused_and_never_repaired_by_reimport(tmp_path, service):
    source = rom(tmp_path)
    entry = service.import_source(source).entry
    master = service.master_path(entry)
    master.write_bytes(rom_bytes(marker=9))
    damaged = master.read_bytes()
    with pytest.raises(ValueError, match="Intégrité"):
        service.resolve("white")
    assert service.verify()[0].valid is False
    with pytest.raises(ValueError, match="Intégrité"):
        service.import_source(source)
    assert master.read_bytes() == damaged


def test_missing_master_is_reported_without_forgetting_manifest(tmp_path, service):
    entry = service.import_source(rom(tmp_path)).entry
    before = service.manifest_path.read_bytes()
    service.master_path(entry).unlink()
    assert service.verify()[0].valid is False
    with pytest.raises(ValueError, match="inaccessible"):
        service.resolve("white")
    assert service.manifest_path.read_bytes() == before


@pytest.mark.parametrize("change", [
    {"schema_version": 2}, {"schema_version": True}, {"owner": "another-owner"},
    {"entries": "broken"},
])
def test_unknown_manifest_never_reset(tmp_path, service, change):
    service.import_source(rom(tmp_path))
    value = json.loads(service.manifest_path.read_text())
    value.update(change)
    service.manifest_path.write_text(json.dumps(value))
    before = service.manifest_path.read_bytes()
    with pytest.raises(ValueError):
        service.list_entries()
    with pytest.raises(ValueError):
        service.import_source(tmp_path / "source.nds")
    assert service.manifest_path.read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("relative_path", "../../outside.nds"), ("sha256", "not-a-hash"), ("size", True),
    ("revision", -1), ("generation", 4), ("game_code", "IRBF"),
    ("source_name", "../private.nds"), ("imported_at", "yesterday"),
])
def test_invalid_entries_refused(tmp_path, service, field, value):
    entry = service.import_source(rom(tmp_path)).entry
    with pytest.raises(ValueError):
        service.master_path(replace(entry, **{field: value}))


def test_duplicate_json_keys_refused(tmp_path, service):
    service.root.mkdir()
    service.manifest_path.write_text('{"owner":"one","owner":"two"}')
    with pytest.raises(ValueError, match="dupliquée"):
        service.list_entries()


def test_import_lock_is_exclusive_and_released(tmp_path, service):
    source = rom(tmp_path)
    with service._lock():
        with pytest.raises(ValueError, match="déjà en cours"):
            RomLibraryService(service.root).import_source(source)
    assert service.import_source(source).imported


def test_failed_manifest_commit_preserves_complete_master_for_recovery(tmp_path, service, monkeypatch):
    source = rom(tmp_path)
    original = service._write_manifest

    def fail(_entries):
        raise OSError("disk unavailable")

    monkeypatch.setattr(service, "_write_manifest", fail)
    with pytest.raises(OSError, match="disk unavailable"):
        service.import_source(source)
    masters = tuple(service.root.rglob("*.nds"))
    assert len(masters) == 1
    stat_before = masters[0].stat()
    assert masters[0].read_bytes() == source.read_bytes()
    assert not service.manifest_path.exists()
    monkeypatch.setattr(service, "_write_manifest", original)
    assert service.import_source(source).imported
    assert masters[0].stat().st_mtime_ns == stat_before.st_mtime_ns


def test_corrupt_unpublished_master_is_never_overwritten(tmp_path, service):
    source = rom(tmp_path)
    actual = inspect_library_source(source)
    master = service.root / "masters" / "white" / f"{actual.sha256}.nds"
    master.parent.mkdir(parents=True)
    master.write_bytes(rom_bytes(marker=99))
    with pytest.raises(ValueError, match="Intégrité"):
        service.import_source(source)
    assert master.read_bytes() == rom_bytes(marker=99)
    assert not service.manifest_path.exists()


def test_publication_does_not_overwrite_a_racing_destination(tmp_path, service, monkeypatch):
    source = rom(tmp_path)
    original = library.os.link

    def race(temporary, destination):
        destination.write_bytes(b"existing file must survive")
        original(temporary, destination)

    monkeypatch.setattr(library.os, "link", race)
    with pytest.raises(FileExistsError):
        service.import_source(source)
    assert tuple(service.root.rglob("*.nds"))[0].read_bytes() == b"existing file must survive"
    assert not tuple(service.root.rglob(".import-*.tmp"))
    assert not service.manifest_path.exists()
