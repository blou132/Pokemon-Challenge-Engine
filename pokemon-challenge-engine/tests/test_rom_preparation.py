"""Archives synthétiques : cache, intégrité et conservation des sources."""

from hashlib import sha256
import json
from pathlib import Path
import stat
import struct
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

import pytest

from app.services.rom_preparation_service import RomPreparationService
from test_auto_discovery import rom_bytes, write_zip


@pytest.fixture
def archive(tmp_path):
    source = write_zip(tmp_path / "source.zip", {"nested/Pokemon Blanc.nds": rom_bytes(size=20000), "README.txt": b"hello"})
    return source, RomPreparationService(tmp_path / "cache")


def test_direct_nds_is_not_copied_or_modified(tmp_path):
    source = tmp_path / "white.nds"
    source.write_bytes(rom_bytes())
    before = source.read_bytes(), source.stat().st_mtime_ns
    service = RomPreparationService(tmp_path / "cache")
    result = service.prepare(source, expected_game="white")
    assert result.path == source and result.manifest_path is None
    assert result.rom_sha256 == sha256(before[0]).hexdigest()
    assert before == (source.read_bytes(), source.stat().st_mtime_ns)
    assert not service.cache_root.exists()


def test_zip_preserves_basename_source_and_publishes_complete_manifest(archive):
    source, service = archive
    before = source.read_bytes(), source.stat().st_mtime_ns
    result = service.prepare(source, expected_game="white")
    assert result.path.name == "Pokemon Blanc.nds" and result.path.read_bytes() == rom_bytes(size=20000)
    assert not result.reused and result.game_code == "IRAF" and result.revision == 0
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["owner"] == "pokemon-challenge-engine-rom-cache" and manifest["complete"] is True
    assert manifest["archive_sha256"] == sha256(before[0]).hexdigest()
    assert manifest["rom_sha256"] == sha256(result.path.read_bytes()).hexdigest()
    assert len(result.path.parent.name) == 16
    assert manifest["member_sha256"] == sha256(b"nested/Pokemon Blanc.nds").hexdigest()
    assert before == (source.read_bytes(), source.stat().st_mtime_ns)
    assert set(path.name for path in result.path.parent.iterdir()) == {"Pokemon Blanc.nds", "manifest.json"}


def test_valid_cache_reused_without_reextraction(archive):
    source, service = archive
    first = service.prepare(source)
    before = first.path.stat().st_mtime_ns, first.manifest_path.read_bytes()
    with patch("app.services.rom_preparation_service.tempfile.mkdtemp", side_effect=AssertionError("no extraction")):
        second = service.prepare(source)
    assert second.reused and second.path == first.path
    assert before == (first.path.stat().st_mtime_ns, first.manifest_path.read_bytes())


def test_changed_archive_creates_new_cache_without_modifying_previous(archive):
    source, service = archive
    first = service.prepare(source)
    previous = first.path.read_bytes()
    write_zip(source, {"nested/Pokemon Blanc.nds": rom_bytes(size=25000)})
    second = service.prepare(source)
    assert first.path != second.path and not second.reused
    assert first.path.read_bytes() == previous


@pytest.mark.parametrize("change", ["rom", "manifest", "missing_manifest"])
def test_invalid_existing_cache_never_silently_overwritten(archive, change):
    source, service = archive
    result = service.prepare(source)
    if change == "rom":
        result.path.write_bytes(b"changed externally")
    elif change == "manifest":
        result.manifest_path.write_bytes(b"{bad")
    else:
        result.manifest_path.unlink()
    before = result.path.read_bytes()
    with pytest.raises(ValueError, match="sans écrasement"):
        service.prepare(source)
    assert result.path.read_bytes() == before


def test_multiple_nds_need_explicit_selection(tmp_path):
    source = write_zip(tmp_path / "multi.zip", {"white.nds": rom_bytes(), "black.nds": rom_bytes("IRBF")})
    service = RomPreparationService(tmp_path / "cache")
    with pytest.raises(ValueError, match="choisissez"):
        service.prepare(source, expected_game="white")
    assert not service.cache_root.exists()
    result = service.prepare(source, member="black.nds", expected_game="black")
    assert result.game_id == "black"


def test_wrong_game_or_unknown_member_refuses_without_cache(archive):
    source, service = archive
    with pytest.raises(ValueError, match="jeu réel"):
        service.prepare(source, expected_game="black")
    with pytest.raises(ValueError, match="Membre ROM inconnu"):
        service.prepare(source, member="missing.nds")
    assert not service.cache_root.exists()


@pytest.mark.parametrize("name", ["../escape.nds", "/absolute.nds", "C:/escape.nds", "folder\\escape.nds", "CON.nds", "name:stream.nds", "folder/../escape.nds"])
def test_zip_traversal_and_windows_unsafe_names_are_rejected(tmp_path, name):
    source = write_zip(tmp_path / "bad.zip", {name: rom_bytes()})
    if "\\" in name:
        # Sous Windows, le créateur zipfile normalise les séparateurs. Modifier
        # les deux noms dans le ZIP permet de tester une archive externe réelle.
        source.write_bytes(source.read_bytes().replace(name.replace("\\", "/").encode(), name.encode()))
    service = RomPreparationService(tmp_path / "cache")
    with pytest.raises(ValueError):
        service.prepare(source)
    assert not service.cache_root.exists()
    assert set(path.name for path in tmp_path.iterdir()) == {"bad.zip"}


def test_symlink_archive_member_is_rejected(tmp_path):
    source = tmp_path / "link.zip"
    info = zipfile.ZipInfo("white.nds")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(source, "w") as handle:
        handle.writestr(info, rom_bytes())
    with pytest.raises(ValueError, match="Liens"):
        RomPreparationService(tmp_path / "cache").prepare(source)


def test_duplicate_member_names_are_rejected(tmp_path):
    source = write_zip(tmp_path / "duplicate.zip", {"white.nds": rom_bytes(), "WHITE.nds": rom_bytes()})
    with pytest.raises(ValueError, match="dupliqués"):
        RomPreparationService(tmp_path / "cache").prepare(source)


def test_decompression_bomb_size_is_rejected_before_reading(tmp_path):
    source = write_zip(tmp_path / "bomb.zip", {"white.nds": rom_bytes()})
    data = bytearray(source.read_bytes())
    central = data.index(b"PK\x01\x02")
    struct.pack_into("<I", data, central + 24, 0x7FFFFFFF)
    source.write_bytes(data)
    with pytest.raises(ValueError, match="volumineuse"):
        RomPreparationService(tmp_path / "cache").prepare(source)


def test_corrupt_crc_refuses_publication_and_cleans_partial_cache(tmp_path):
    source = tmp_path / "crc.zip"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as handle:
        handle.writestr("white.nds", rom_bytes(size=20000))
    data = bytearray(source.read_bytes())
    data[6000] ^= 0xFF
    source.write_bytes(data)
    service = RomPreparationService(tmp_path / "cache")
    with pytest.raises(ValueError, match="corrompue"):
        service.prepare(source)
    assert not list(service.cache_root.rglob("*.nds"))
    assert not list(service.cache_root.rglob("manifest.json"))
    assert not list(service.cache_root.rglob("*.lock"))


def test_disk_full_error_keeps_source_and_does_not_publish(archive):
    source, service = archive
    before = source.read_bytes()
    with patch("app.services.rom_preparation_service.shutil.disk_usage", return_value=SimpleNamespace(free=0)):
        with pytest.raises(ValueError, match="Espace disque"):
            service.prepare(source)
    assert source.read_bytes() == before
    assert not list(service.cache_root.rglob("*.nds"))


def test_permissions_error_is_readable_and_cleans_partial_files(archive):
    source, service = archive
    real_open = Path.open

    def deny_writes(path, mode="r", *args, **kwargs):
        if mode == "xb":
            raise PermissionError("access denied")
        return real_open(path, mode, *args, **kwargs)

    with patch.object(Path, "open", deny_writes):
        with pytest.raises(ValueError, match="permissions"):
            service.prepare(source)
    assert source.exists() and not list(service.cache_root.rglob("*.nds"))


def test_detected_junction_refuses_managed_cache_path(tmp_path):
    with patch.object(Path, "is_junction", return_value=True):
        with pytest.raises(ValueError, match="jonction"):
            RomPreparationService(tmp_path / "cache")


def test_extraction_journal_reports_only_paths_and_hashes(archive):
    source, service = archive
    events = []
    service.journal = lambda event, **details: events.append((event, details))
    result = service.prepare(source)
    assert events[0][0] == "rom_extracted"
    assert events[0][1]["rom_sha256"] == result.rom_sha256
    service.prepare(source)
    assert len(events) == 1


@pytest.mark.parametrize("payload", [b"short", b"\0" * 31, rom_bytes("ABCD")])
def test_incomplete_or_unknown_nds_never_prepared(tmp_path, payload):
    source = tmp_path / "white.nds"
    source.write_bytes(payload)
    with pytest.raises(ValueError):
        RomPreparationService(tmp_path / "cache").prepare(source)


def test_zip_entry_count_is_bounded_before_opening_zipfile(archive):
    source, service = archive
    data = bytearray(source.read_bytes())
    end = data.rfind(b"PK\x05\x06")
    struct.pack_into("<HH", data, end + 8, 65535, 65535)
    source.write_bytes(data)
    with patch("app.services.rom_preparation_service.zipfile.ZipFile", side_effect=AssertionError("must reject first")):
        with pytest.raises(ValueError, match="ZIP64"):
            service.prepare(source)


def test_source_change_during_hash_is_rejected_without_publishing(archive):
    source, service = archive
    from app.services.rom_preparation_service import file_hash

    def mutate(path):
        result = file_hash(path)
        if path == source:
            source.write_bytes(source.read_bytes() + b"changed")
        return result

    with patch("app.services.rom_preparation_service.file_hash", mutate):
        with pytest.raises(ValueError, match="changé"):
            service.prepare(source)
    assert not list(service.cache_root.rglob("*.nds"))


def test_write_failure_after_extraction_started_cleans_partial_files(archive):
    source, service = archive
    with patch("app.services.rom_preparation_service.os.fsync", side_effect=OSError("disk full")):
        with pytest.raises(ValueError, match="espace disque"):
            service.prepare(source)
    assert source.exists()
    assert not list(service.cache_root.rglob("*.nds"))
    assert not list(service.cache_root.rglob("*.lock"))


def test_7z_remains_explicitly_unavailable(tmp_path):
    path = tmp_path / "game.7z"
    path.write_bytes(b"not a supported archive")
    with pytest.raises(ValueError, match="7z n'est pas disponible"):
        RomPreparationService(tmp_path / "cache").prepare(path)


def test_missing_provenance_field_invalidates_existing_cache(archive):
    source, service = archive
    prepared = service.prepare(source)
    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    del manifest["archive_size"]
    prepared.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="incomplet"):
        service.prepare(source)


def test_long_windows_cache_path_is_refused_before_extraction(archive):
    source, service = archive
    service.cache_root = service.cache_root / ("long-" * 30)
    with pytest.raises(ValueError, match="259"):
        service.prepare(source)
    assert not service.cache_root.exists()


def test_short_hash_collision_cannot_reuse_another_member(archive):
    source, service = archive
    prepared = service.prepare(source)
    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    manifest["archive_member"] = "other/Pokemon Blanc.nds"
    manifest["member_sha256"] = sha256(manifest["archive_member"].encode()).hexdigest()
    prepared.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = prepared.path.read_bytes()
    with pytest.raises(ValueError, match="sans écrasement"):
        service.prepare(source)
    assert prepared.path.read_bytes() == before


def test_deeply_nested_cache_manifest_is_preserved_and_reported(archive):
    source, service = archive
    prepared = service.prepare(source)
    payload = "[" * 2000 + "0" + "]" * 2000
    prepared.manifest_path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="sans écrasement"):
        service.prepare(source)
    assert prepared.manifest_path.read_text(encoding="utf-8") == payload
