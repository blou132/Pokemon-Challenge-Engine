"""Bounded discovery with synthetic ROMs, including empty-directory cache changes."""

from pathlib import Path

import pytest

from app.services import game_discovery_service as discovery
from app.services.game_discovery_service import GameDiscoveryService
from test_auto_discovery import rom_bytes, write_zip
from test_auto_setup_service import environment
from test_automatic_setup_flow import automatic


def test_automatic_setup_discovers_rom_in_immediate_child(automatic):
    env = automatic
    folder = env.source.parent / "Pokemon Blanc"
    folder.mkdir()
    source = env.source.rename(folder / env.source.name)
    original = source.read_bytes()

    report = env.service.automatic_setup()

    assert report["game_states"]["white"]["status"] == "ready"
    assert report["games"][0]["source_path"] == str(source)
    assert source.read_bytes() == original


def test_empty_child_rom_addition_invalidates_automatic_cache(automatic):
    env = automatic
    folder = env.source.parent / "Pokemon Noir"
    folder.mkdir()
    env.service.automatic_setup()
    assert env.service.automatic_setup()["cached"]
    (folder / "black.nds").write_bytes(rom_bytes("IRBF"))

    report = env.service.automatic_setup()

    assert not report["cached"]
    assert report["game_states"]["black"]["status"] == "ready"
    assert str(folder) in report["searched_directories"]


def test_child_discovery_keeps_direct_roms_and_stops_at_one_level(tmp_path):
    direct = tmp_path / "white.nds"
    direct.write_bytes(rom_bytes())
    child = tmp_path / "child"
    child.mkdir()
    nested = write_zip(child / "black.zip", {"black.nds": rom_bytes("IRBF")})
    deeper = child / "deeper"
    deeper.mkdir()
    (deeper / "white2.nds").write_bytes(rom_bytes("IRDF"))
    empty = tmp_path / "empty"
    empty.mkdir()
    service = GameDiscoveryService()

    found = service.discover([tmp_path], include_subdirectories=True, explicit_paths=[nested])

    assert {candidate.source_path for candidate in found} == {direct, nested}
    assert len(found) == 2
    assert set(service.searched_directories) == {tmp_path, child, empty}
    assert not service.warnings
    assert [candidate.source_path for candidate in service.discover([tmp_path])] == [direct]
    assert service.searched_directories == [tmp_path]


def test_scan_entry_limit_is_shared_across_roots_and_children(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "MAX_SCAN_ENTRIES", 3)
    roots = [tmp_path / "first", tmp_path / "second"]
    for root in roots:
        child = root / "child"
        child.mkdir(parents=True)
        (child / "white.nds").write_bytes(rom_bytes())
    service = GameDiscoveryService()

    found = service.discover(roots, include_subdirectories=True)

    assert len(found) == 1  # Two directory entries plus one ROM consume the whole budget.
    assert any("3 entrées au total" in warning for warning in service.warnings)


def test_scan_directory_limit_is_global_and_includes_empty_children(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "MAX_SCAN_DIRECTORIES", 2)
    for name in ("first", "second", "third"):
        (tmp_path / name).mkdir()
    service = GameDiscoveryService()

    assert service.discover([tmp_path], include_subdirectories=True) == ()
    assert len(service.searched_directories) == 2
    assert any("2 dossiers" in warning for warning in service.warnings)


def test_automatic_scan_does_not_enter_managed_cache(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "white.nds").write_bytes(rom_bytes())
    service = GameDiscoveryService(cache)

    assert service.discover([tmp_path, cache], include_subdirectories=True) == ()
    assert service.searched_directories == [tmp_path]


def test_scan_rejects_junction_child_before_reading_it(tmp_path, monkeypatch):
    child = tmp_path / "junction"
    child.mkdir()
    (child / "white.nds").write_bytes(rom_bytes())
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda path: path == child or original(path))
    service = GameDiscoveryService()

    assert service.discover([tmp_path], include_subdirectories=True) == ()
    assert service.searched_directories == [tmp_path]
    assert any("jonction" in warning for warning in service.warnings)


def test_scan_does_not_follow_directory_or_rom_symlinks(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    source = external / "white.nds"
    source.write_bytes(rom_bytes())
    root = tmp_path / "root"
    root.mkdir()
    try:
        (root / "linked-folder").symlink_to(external, target_is_directory=True)
        (root / "linked.nds").symlink_to(source)
    except OSError as exc:
        pytest.skip(f"Symlink creation is unavailable: {exc}")
    service = GameDiscoveryService()

    assert service.discover([root], include_subdirectories=True) == ()
    assert service.searched_directories == [root]
