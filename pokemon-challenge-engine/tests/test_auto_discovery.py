"""Détection entièrement synthétique, sans scan des disques utilisateur."""

from pathlib import Path
from unittest.mock import patch
import zipfile

import pytest

from app.services.game_discovery_service import GameDiscoveryService
from app.services.retrobat_discovery_service import RetroBatDiscoveryService
from app.services.rom_preparation_service import RomPreparationService
from app.services.save_discovery_service import SaveDiscoveryService


def rom_bytes(code="IRAF", revision=0, size=4096):
    data = bytearray(b"\x35" * size)
    data[12:16] = code.encode("ascii")
    data[0x1E] = revision
    return bytes(data)


def write_zip(path, members):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return path


def create_retrobat(root):
    (root / "roms" / "nds").mkdir(parents=True)
    (root / "emulators" / "desmume").mkdir(parents=True)
    return root


def test_retrobat_requires_structure_not_name(tmp_path):
    fake = tmp_path / "RetroBat"
    fake.mkdir()
    service = RetroBatDiscoveryService()
    assert service.discover([fake, tmp_path / "missing"], drive_roots=[]) == ()
    real = create_retrobat(tmp_path / "Actual")
    result = service.discover([real], drive_roots=[])
    assert len(result) == 1 and result[0].root == real
    assert result[0].roms_directory == real / "roms"


def test_discovery_checks_drive_roots_and_keeps_multiple_installations(tmp_path):
    drive_c, drive_d = tmp_path / "C", tmp_path / "D"
    first = create_retrobat(drive_c / "RetroBat")
    second = create_retrobat(drive_d / "RetroBat")
    service = RetroBatDiscoveryService()
    assert {item.root for item in service.discover(drive_roots=[drive_c, drive_d])} == {first, second}


def test_configured_emulator_or_rom_recovers_parent_without_duplicates(tmp_path):
    root = create_retrobat(tmp_path / "Portable")
    exe = root / "emulators" / "desmume" / "DeSmuME.exe"
    exe.touch()
    rom = root / "roms" / "nds" / "white.nds"
    rom.write_bytes(rom_bytes())
    found = RetroBatDiscoveryService().discover([exe, rom, root], drive_roots=[])
    assert len(found) == 1 and found[0].root == root


def test_retrobat_does_not_search_deep_unconfigured_locations(tmp_path):
    create_retrobat(tmp_path / "deep" / "nested" / "RetroBat")
    assert RetroBatDiscoveryService().discover([tmp_path], drive_roots=[]) == ()


@pytest.mark.parametrize("code,game,region", [("IRBF", "black", "FR"), ("IRAF", "white", "FR"),
                                             ("IREF", "black2", "FR"), ("IRDF", "white2", "FR"),
                                             ("IRAO", "white", "EN"), ("IRAJ", "white", "JP")])
def test_header_identity_not_filename(tmp_path, code, game, region):
    path = tmp_path / "misleading-black2.nds"
    path.write_bytes(rom_bytes(code, 3))
    candidate = GameDiscoveryService().inspect(path)[0]
    assert (candidate.game_id, candidate.game_code, candidate.region, candidate.revision) == (game, code, region, 3)
    assert candidate.candidate_id == GameDiscoveryService().inspect(path)[0].candidate_id


def test_zip_members_are_detected_without_extraction(tmp_path):
    source = write_zip(tmp_path / "misleading.zip", {"readme.txt": b"text", "folder/white.nds": rom_bytes()})
    found = GameDiscoveryService().discover([tmp_path])
    assert len(found) == 1 and found[0].source_kind == "zip"
    assert found[0].archive_member == "folder/white.nds" and not found[0].requires_choice
    assert list(tmp_path.iterdir()) == [source]


def test_multiple_rom_members_require_choice_even_if_only_one_supported(tmp_path):
    source = write_zip(tmp_path / "collection.zip", {"white.nds": rom_bytes(), "other.nds": rom_bytes("ABCD")})
    found = GameDiscoveryService().inspect(source)
    assert len(found) == 1 and found[0].requires_choice


def test_two_distinct_sources_of_same_game_are_not_merged(tmp_path):
    (tmp_path / "first.nds").write_bytes(rom_bytes(size=4096))
    (tmp_path / "second.nds").write_bytes(rom_bytes(size=8192))
    assert len(GameDiscoveryService().discover([tmp_path])) == 2


def test_archive_and_its_managed_cache_are_deduplicated(tmp_path):
    source = write_zip(tmp_path / "white.zip", {"white.nds": rom_bytes()})
    root = tmp_path / "cache"
    prepared = RomPreparationService(root).prepare(source)
    found = GameDiscoveryService(root).discover([tmp_path, prepared.path.parent], explicit_paths=[prepared.path, source])
    assert len(found) == 1 and found[0].source_path == source


def test_unknown_corrupt_and_empty_archives_are_warnings_not_false_games(tmp_path):
    write_zip(tmp_path / "empty.zip", {"README.txt": b"hi"})
    (tmp_path / "corrupt.zip").write_bytes(b"not zip")
    (tmp_path / "foreign.nds").write_bytes(rom_bytes("ABCD"))
    service = GameDiscoveryService()
    assert service.discover([tmp_path]) == ()
    assert len(service.warnings) == 3


def test_game_scan_is_non_recursive(tmp_path):
    child = tmp_path / "nested"
    child.mkdir()
    (child / "white.nds").write_bytes(rom_bytes())
    assert GameDiscoveryService().discover([tmp_path]) == ()


def candidate_for_save(tmp_path):
    rom = tmp_path / "Pokemon Blanc.nds"
    rom.write_bytes(rom_bytes())
    return GameDiscoveryService().inspect(rom)[0]


def test_one_exact_dsv_is_proposed_but_not_modified(tmp_path):
    candidate = candidate_for_save(tmp_path)
    save = tmp_path / "Pokemon Blanc.dsv"
    save.write_bytes(b"synthetic save")
    before = save.read_bytes(), save.stat().st_mtime_ns
    service = SaveDiscoveryService()
    found = service.discover(candidate)
    assert len(found) == 1 and service.proposed(found).path == save
    assert before == (save.read_bytes(), save.stat().st_mtime_ns)


def test_multiple_credible_saves_never_silently_select(tmp_path):
    candidate = candidate_for_save(tmp_path)
    (tmp_path / "Pokemon Blanc.dsv").write_bytes(b"first")
    (tmp_path / "Pokemon Blanc - ancien.dsv").write_bytes(b"second")
    service = SaveDiscoveryService()
    found = service.discover(candidate)
    assert len(found) == 2 and service.proposed(found) is None


def test_missing_and_wrong_game_save_are_not_proposed(tmp_path):
    candidate = candidate_for_save(tmp_path)
    (tmp_path / "Pokemon Noir.dsv").write_bytes(b"wrong game")
    service = SaveDiscoveryService()
    assert service.discover(candidate) == () and service.proposed(()) is None


def test_srm_is_only_manual_import_candidate(tmp_path):
    candidate = candidate_for_save(tmp_path)
    (tmp_path / "Pokemon Blanc.srm").write_bytes(b"raw SRAM")
    service = SaveDiscoveryService()
    found = service.discover(candidate)
    assert len(found) == 1 and not found[0].compatible
    assert service.proposed(found) is None and "import manuel" in found[0].reason


def test_ini_battery_and_state_slots_resolve_relative_to_executable(tmp_path):
    candidate = candidate_for_save(tmp_path)
    emulator = tmp_path / "emulator"
    emulator.mkdir()
    executable = emulator / "DeSmuME.exe"
    executable.touch()
    battery = emulator / "custom-battery"
    battery.mkdir()
    (battery / "Pokemon Blanc.dsv").write_bytes(b"save")
    (emulator / "desmume.ini").write_bytes(b"[PathSettings]\r\nBattery=.\\custom-battery\r\nStateSlots=.\\custom-slots\r\n")
    service = SaveDiscoveryService()
    found = service.discover(candidate, emulator_path=executable)
    assert service.proposed(found).path == battery / "Pokemon Blanc.dsv"
    assert service.state_slots_directory == emulator / "custom-slots"


def test_retrobat_existing_save_directories_are_candidates(tmp_path):
    root = create_retrobat(tmp_path / "RetroBat")
    candidate = candidate_for_save(tmp_path)
    saves = root / "saves" / "nds" / "DeSmuME"
    saves.mkdir(parents=True)
    (saves / "Pokemon Blanc.dsv").write_bytes(b"save")
    service = SaveDiscoveryService()
    assert service.proposed(service.discover(candidate, retrobat_root=root)).path.parent == saves


def test_locked_save_is_reported_and_not_selected(tmp_path):
    candidate = candidate_for_save(tmp_path)
    save = tmp_path / "Pokemon Blanc.dsv"
    save.write_bytes(b"save")
    real_open = Path.open

    def locked(path, *args, **kwargs):
        if path == save:
            raise PermissionError("locked")
        return real_open(path, *args, **kwargs)

    service = SaveDiscoveryService()
    with patch.object(Path, "open", locked):
        assert service.discover(candidate) == ()
    assert service.warnings and save.read_bytes() == b"save"


def test_archive_member_and_archive_stems_both_discover_saves(tmp_path):
    source = write_zip(tmp_path / "RetroBat White.zip", {"Pokemon Blanc.nds": rom_bytes()})
    (tmp_path / "Pokemon Blanc.dsv").write_bytes(b"inner")
    (tmp_path / "RetroBat White.dsv").write_bytes(b"outer")
    candidate = GameDiscoveryService().inspect(source)[0]
    service = SaveDiscoveryService()
    found = service.discover(candidate)
    assert len(found) == 2 and service.proposed(found) is None


def test_missing_configured_save_prevents_silent_reassignment(tmp_path):
    candidate = candidate_for_save(tmp_path)
    (tmp_path / "Pokemon Blanc.dsv").write_bytes(b"other copy")
    service = SaveDiscoveryService()
    found = service.discover(candidate, configured_save=tmp_path / "old" / "Pokemon Blanc.dsv")
    assert len(found) == 1 and service.warnings and service.proposed(found) is None


def test_empty_save_is_not_proposed_as_ready(tmp_path):
    candidate = candidate_for_save(tmp_path)
    (tmp_path / "Pokemon Blanc.dsv").touch()
    service = SaveDiscoveryService()
    found = service.discover(candidate)
    assert len(found) == 1 and service.proposed(found) is None


def test_incomplete_save_scan_cannot_propose_a_single_surviving_candidate(tmp_path):
    candidate = candidate_for_save(tmp_path)
    (tmp_path / "Pokemon Blanc.dsv").write_bytes(b"save")
    service = SaveDiscoveryService()
    with patch("app.services.save_discovery_service.bounded_files", side_effect=PermissionError("denied")):
        found = service.discover(candidate, configured_save=tmp_path / "Pokemon Blanc.dsv")
    assert len(found) == 1 and service.proposed(found) is None


def test_game_directory_scan_has_a_hard_entry_limit(tmp_path):
    from app.services.discovery_safety import bounded_files
    for number in range(3):
        (tmp_path / str(number)).touch()
    with pytest.raises(ValueError, match="limitée"):
        list(bounded_files(tmp_path, limit=2))


@pytest.mark.parametrize("payload", ["[" * 2000 + "0" + "]" * 2000, '{"owner":"foreign","owner":"pokemon-challenge-engine-rom-cache"}'])
def test_invalid_cache_provenance_does_not_crash_discovery_or_guess_source(tmp_path, payload):
    source = write_zip(tmp_path / "white.zip", {"white.nds": rom_bytes()})
    root = tmp_path / "cache"
    prepared = RomPreparationService(root).prepare(source)
    prepared.manifest_path.write_text(payload, encoding="utf-8")
    service = GameDiscoveryService(root)
    assert service.discover([], explicit_paths=[prepared.path]) == ()
    assert service.warnings
    assert prepared.manifest_path.read_text(encoding="utf-8") == payload and source.exists()


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16-be"])
def test_unsupported_ini_encoding_cannot_propose_a_save_from_misread_battery_path(tmp_path, encoding):
    candidate = candidate_for_save(tmp_path)
    emulator = tmp_path / "emulator"
    emulator.mkdir()
    executable = emulator / "DeSmuME.exe"
    executable.touch()
    battery = emulator / "custom-battery"
    battery.mkdir()
    (battery / "Pokemon Blanc.dsv").write_bytes(b"save")
    content = "[PathSettings]\r\nBattery=.\\custom-battery\r\n"
    raw = content.encode(encoding)
    if encoding == "utf-16-be":
        raw = b"\xfe\xff" + raw
    ini = emulator / "desmume.ini"
    ini.write_bytes(raw)
    service = SaveDiscoveryService()
    assert service.proposed(service.discover(candidate, emulator_path=executable)) is None
    assert service.warnings and ini.read_bytes() == raw
