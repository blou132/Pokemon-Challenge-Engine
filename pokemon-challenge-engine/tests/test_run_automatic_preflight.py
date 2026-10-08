"""Selected-run preflight with synthetic discovery and real local cache reads."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.game_detector import GameDetector
from app.services.config_service import AppConfig
from app.services.discovery_safety import file_hash
from app.services.game_mode_config import launch_defaults, validate_config
from app.services.run_launch_service import RunLaunchService
from test_auto_discovery import rom_bytes, write_zip


class Setup:
    def __init__(self, root, report):
        self.cache_root = root / "cache"
        self.report = report
        self.scans = []
        self.checks = []

    def automatic_setup(self, *, game_id):
        self.scans.append(game_id)
        return deepcopy(self.report)

    def health_check(self, game_id, *, options_override):
        values = deepcopy(options_override)
        self.checks.append(values)
        issues = []
        try:
            if GameDetector.detect(values["rom_path"]) != game_id:
                issues.append("Wrong game")
        except (ValueError, OSError):
            issues.append("Missing ROM")
        if not values["emulator_path"] or not Path(values["emulator_path"]).is_file():
            issues.append("Missing emulator")
        if values["save_path"] and not Path(values["save_path"]).is_file():
            issues.append("La sauvegarde sélectionnée a été déplacée ou supprimée.")
        return {"ready": not issues, "launch_ready": not issues, "issues": issues}


@pytest.fixture
def environment(tmp_path):
    emulator = tmp_path / "DeSmuME.exe"
    emulator.write_bytes(b"Synthetic executable; never launched")
    ini = tmp_path / "desmume.ini"
    ini.write_text("[General]\n", encoding="utf-8")
    source = tmp_path / "White.nds"
    source.write_bytes(rom_bytes())
    report = {"ready": True, "game_states": {"white": {
        "status": "ready", "message": "Prêt", "candidate_id": "white-fixture", "emulator_path": str(emulator)}},
        "games": [{"id": "white-fixture", "game_id": "white", "source_path": str(source),
                   "archive_member": None, "supported": True}],
        "emulators": [{"path": str(emulator), "architecture": "x64"}]}
    setup = Setup(tmp_path, report)
    options = launch_defaults("white", AppConfig(), tmp_path)
    options.update(rom_path=str(source), emulator_path=str(emulator), ini_path=str(ini))
    run = SimpleNamespace(run_id="synthetic-run", game_id="white", launch_profile=options,
                          save_path=None, rom_fingerprint=None)
    return run, setup, source, emulator


def prepare(tmp_path, run, setup):
    return RunLaunchService(tmp_path, AppConfig(), setup=setup).prepare(run)


def test_valid_explicit_references_are_checked_without_discovery_or_global_rebinding(tmp_path, environment):
    run, setup, source, _ = environment
    run.launch_profile.update(speed="x4", lua_connection="manual")
    saved = tmp_path / "owned.dsv"
    saved.write_bytes(b"synthetic save")
    run.save_path = str(saved)
    run.rom_fingerprint = file_hash(source)
    before = deepcopy(run.launch_profile)
    setup.report["games"][0]["source_path"] = str(tmp_path / "another.nds")
    result = prepare(tmp_path, run, setup)
    assert result["health"]["ready"]
    assert setup.scans == []
    assert result["profile"] == before | {"save_path": str(saved)}
    assert run.launch_profile == before


def test_missing_run_rom_prepares_zip_and_preserves_archive_without_other_games(tmp_path, environment):
    run, setup, _, _ = environment
    archive = write_zip(tmp_path / "White.zip", {"White.nds": rom_bytes()})
    before = archive.read_bytes(), archive.stat().st_mtime_ns
    setup.report["games"][0].update(source_path=str(archive), archive_member="White.nds")
    setup.report["game_states"].update({game: {"status": "not_found"} for game in ("black", "black2", "white2")})
    run.launch_profile["rom_path"] = str(tmp_path / "missing.nds")
    result = prepare(tmp_path, run, setup)
    assert setup.scans == ["white"]
    assert result["health"]["ready"]
    assert Path(result["profile"]["rom_path"]).read_bytes() == rom_bytes()
    assert result["source"] == {"source_path": str(archive), "archive_member": "White.nds"}
    assert "_source" not in result["profile"]
    validate_config({"launch_profiles": {"white": result["profile"]}}, AppConfig(), tmp_path)
    assert (archive.read_bytes(), archive.stat().st_mtime_ns) == before
    assert run.launch_profile["rom_path"] == str(tmp_path / "missing.nds")


def test_another_ready_game_does_not_make_missing_target_ready(tmp_path, environment):
    run, setup, _, _ = environment
    run.launch_profile["rom_path"] = ""
    setup.report["games"] = []
    setup.report["game_states"] = {
        "white": {"status": "not_found", "message": "Pokémon Blanc n'a pas été trouvé. Ajoutez le jeu à votre bibliothèque RetroBat."},
        "black": {"status": "ready"}}
    result = prepare(tmp_path, run, setup)
    assert not result["health"]["ready"]
    assert not result["health"]["launch_ready"]
    assert "Pokémon Blanc n'a pas été trouvé" in result["health"]["issues"][0]
    assert setup.scans == ["white"]


def test_missing_executable_is_recovered_without_replacing_valid_rom_or_ini(tmp_path, environment):
    run, setup, source, emulator = environment
    manual_ini = tmp_path / "manual.ini"
    manual_ini.write_text("[Keys]\nA=88\n", encoding="utf-8")
    run.launch_profile.update(emulator_path="", ini_path=str(manual_ini), speed="x2")
    setup.report["game_states"] = {"white": {"status": "not_found"}}
    setup.report["games"] = []
    result = prepare(tmp_path, run, setup)
    assert result["health"]["ready"]
    assert result["profile"]["emulator_path"] == str(emulator)
    assert result["profile"]["rom_path"] == str(source)
    assert result["profile"]["ini_path"] == str(manual_ini)
    assert result["profile"]["speed"] == "x2"


def test_adjacent_ini_is_detected_without_replacing_valid_run_references_or_scanning(tmp_path, environment):
    run, setup, source, emulator = environment
    run.launch_profile["ini_path"] = ""
    result = prepare(tmp_path, run, setup)
    assert result["health"]["ready"]
    assert result["profile"]["ini_path"] == str(emulator.parent / "desmume.ini")
    assert result["profile"]["rom_path"] == str(source)
    assert setup.scans == []


def test_missing_explicit_save_remains_blocking_and_is_never_reassociated(tmp_path, environment):
    run, setup, _, _ = environment
    run.launch_profile["rom_path"] = ""
    run.save_path = str(tmp_path / "missing-owned.dsv")
    setup.report["game_states"]["white"]["save_path"] = str(tmp_path / "global.dsv")
    result = prepare(tmp_path, run, setup)
    assert not result["health"]["ready"]
    assert result["profile"]["save_path"] == run.save_path
    assert "sauvegarde" in " ".join(result["health"]["issues"])


def test_no_run_save_stays_unset_even_when_discovery_finds_one(tmp_path, environment):
    run, setup, _, _ = environment
    run.launch_profile.update(rom_path="", save_path="outdated-global.dsv")
    setup.report["game_states"]["white"]["save_path"] = "another-global.dsv"
    result = prepare(tmp_path, run, setup)
    assert result["health"]["ready"]
    assert result["profile"]["save_path"] == ""


def test_run_explicit_save_resolves_unrelated_global_save_ambiguity(tmp_path, environment):
    run, setup, _, _ = environment
    run.launch_profile["rom_path"] = ""
    owned = tmp_path / "owned.dsv"
    owned.write_bytes(b"synthetic save")
    run.save_path = str(owned)
    setup.report["ready"] = False
    setup.report["game_states"]["white"].update(status="needs_choice", message="Plusieurs sauvegardes ont été trouvées.")
    result = prepare(tmp_path, run, setup)
    assert result["health"]["ready"]
    assert result["profile"]["save_path"] == str(owned)
    assert all(check["save_path"] == str(owned) for check in setup.checks)


@pytest.mark.parametrize("different", [False, True])
def test_moved_source_requires_same_frozen_rom_hash(tmp_path, environment, different):
    run, setup, source, _ = environment
    cached = tmp_path / "already-prepared.nds"
    cached.write_bytes(rom_bytes())
    if different:
        source.write_bytes(rom_bytes() + b"different")
    run.launch_profile.update(rom_path=str(cached), _source={"source_path": str(tmp_path / "moved.zip"), "archive_member": "White.nds"})
    run.rom_fingerprint = file_hash(cached)
    result = prepare(tmp_path, run, setup)
    assert result["health"]["ready"] is not different
    assert result["profile"]["rom_path"] == str(cached)
    if different:
        assert "ROM a changé" in result["health"]["issues"][0]
        assert result["source"] == run.launch_profile["_source"]
    else:
        assert result["source"] == {"source_path": str(source), "archive_member": None}
        assert result["rom_fingerprint"] == run.rom_fingerprint


def test_valid_source_provenance_is_returned_without_extra_profile_fields(tmp_path, environment):
    run, setup, source, _ = environment
    run.launch_profile["_source"] = {"source_path": str(source), "archive_member": None}
    result = prepare(tmp_path, run, setup)
    assert result["source"] == run.launch_profile["_source"]
    assert "_source" not in result["profile"]
    assert setup.scans == []


@pytest.mark.parametrize("ambiguity", ["rom", "emulator"])
def test_ambiguous_rom_or_emulator_is_not_silently_chosen(tmp_path, environment, ambiguity):
    run, setup, _, _ = environment
    run.launch_profile.update(rom_path="", emulator_path="")
    entry = setup.report["game_states"]["white"]
    entry.update(status="needs_choice", message="Plusieurs choix locaux : choisissez celui à utiliser.")
    if ambiguity == "rom":
        entry["candidate_id"] = ""
    else:
        entry["emulator_path"] = ""
        setup.report["emulators"].append({"path": str(tmp_path / "second.exe"), "architecture": "x64"})
    result = prepare(tmp_path, run, setup)
    assert not result["health"]["ready"]
    assert "choisissez" in result["health"]["issues"][0]
    assert result["profile"]["rom_path"] == ""
