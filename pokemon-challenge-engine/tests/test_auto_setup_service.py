"""Integrated setup fixtures: synthetic ROM/PE, no user scan or network."""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.auto_setup_service import AutoSetupService
from app.services.config_service import AppConfig
from app.services.game_mode_config import GameModeConfigStore
from app.services.retrobat_discovery_service import RetroBatDiscoveryService
from app.services import lua_runtime_installer as runtime
from test_auto_discovery import create_retrobat, rom_bytes, write_zip
from test_lua_runtime_setup import pe_bytes


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(RetroBatDiscoveryService, "_drives", staticmethod(lambda: ()))
    root = create_retrobat(tmp_path / "rb")
    exe = root / "emulators/desmume/game.exe"
    exe.write_bytes(pe_bytes(markers=b"DeSmuME lua51.dll"))
    battery = exe.parent / "Battery"
    battery.mkdir()
    save = battery / "white.dsv"
    save.write_bytes(b"synthetic saved game")
    ini = exe.parent / "desmume.ini"
    ini.write_bytes(b"[PathSettings]\nBattery=Battery\nStateSlots=StateSlots\n")
    source = write_zip(root / "roms/nds/white.zip", {"white.nds": rom_bytes()})
    blobs = {name: pe_bytes(dll=True, suffix=name.encode()) for name in ("lua51.dll", "lua5.1.dll")}
    manifest = {"x64": {name: ("x64/" + name, len(data), hashlib.sha256(data).hexdigest())
                        for name, data in blobs.items()}, "x86": runtime.DLL_MANIFEST["x86"]}
    monkeypatch.setattr(runtime, "DLL_MANIFEST", manifest)
    for name, data in blobs.items():
        (exe.parent / name).write_bytes(data)
    service = AutoSetupService(tmp_path / "pce", AppConfig())
    result = service.scan(retrobat_path=str(root))
    selection = {"candidate_id": result["games"][0]["id"], "emulator_path": str(exe), "retrobat_root": str(root)}
    return SimpleNamespace(root=root, exe=exe, ini=ini, save=save, source=source, service=service,
                           report=result, selection=selection, blobs=blobs)


def test_zip_ready_profile_survives_restart_without_touching_sources(environment):
    env = environment
    originals = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (env.source, env.exe, env.ini, env.save)}
    assert len(env.report["games"]) == 1
    assert env.report["games"][0]["proposed_save"] == str(env.save)
    assert env.report["emulators"][0]["lua_status"] == "verified"
    prepared = env.service.prepare(env.selection)
    assert prepared["health"]["ready"]
    assert prepared["health"]["lua_status"]["console_status"] == "not_tested"
    assert Path(prepared["profile"]["rom_path"]).read_bytes() == rom_bytes()
    assert prepared["profile"]["save_path"] == str(env.save)
    env.service.complete_first_run()
    fresh = AutoSetupService(env.service.base_dir, AppConfig())
    assert fresh.first_run_done and fresh.is_configured("white")
    assert fresh.prepare_play("white")["health"]["ready"]
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in originals} == originals
    assert any(item["event"] == "save_detected" for item in fresh.journal.recent())


def test_setup_preserves_other_game_and_user_backup_preferences(environment):
    env = environment
    store, values = env.service._preferences()
    values["launch_profiles"]["white"].update(backup_on_launch=True, backup_retention=7, speed="MAX")
    values["launch_profiles"]["black2"]["rom_path"] = "unrelated.nds"
    store.save(values)
    profile = env.service.prepare(env.selection)["profile"]
    assert profile["backup_on_launch"] and profile["backup_retention"] == 7 and profile["speed"] == "MAX"
    assert store.load()["launch_profiles"]["black2"]["rom_path"] == "unrelated.nds"


@pytest.mark.parametrize("change", ["missing_dll", "wrong_dll", "missing_exe", "bad_exe", "missing_ini", "bad_ini", "missing_save"])
def test_health_refuses_broken_installation(environment, change):
    env = environment
    env.service.prepare(env.selection)
    if change == "missing_dll": (env.exe.parent / "lua51.dll").unlink()
    elif change == "wrong_dll": (env.exe.parent / "lua51.dll").write_bytes(pe_bytes("x86", dll=True))
    elif change == "missing_exe": env.exe.unlink()
    elif change == "bad_exe": env.exe.write_bytes(b"not an emulator")
    elif change == "missing_ini": env.ini.unlink()
    elif change == "bad_ini": env.ini.write_bytes(b"\xef\xbb\xbf[PathSettings]\nBattery=Battery\n")
    elif change == "missing_save": env.save.unlink()
    health = env.service.health_check("white")
    assert not health["ready"] and health["issues"]
    assert health["launch_ready"] == (change in {"missing_dll", "wrong_dll"})
    assert health["changed"] or change == "missing_save"


def test_setup_never_claims_different_save_will_be_loaded(environment):
    env = environment
    other = env.source.parent / "white.dsv"
    other.write_bytes(b"alternative")
    env.service.scan(retrobat_path=str(env.root))
    with pytest.raises(ValueError, match="sauvegardes"):
        env.service.prepare(env.selection)
    selection = env.selection | {"save_path": str(other)}
    health = env.service.prepare(selection)["health"]
    assert not health["ready"] and any("chargera" in issue for issue in health["issues"])
    assert other.read_bytes() == b"alternative"


def test_ambiguous_saves_can_be_declined_explicitly(environment):
    env = environment
    (env.source.parent / "white.dsv").write_bytes(b"alternative")
    env.service.scan(retrobat_path=str(env.root))
    result = env.service.prepare(env.selection | {"save_path": ""})
    assert result["health"]["ready"] and result["profile"]["save_path"] == ""


@pytest.mark.parametrize("code,revision", [("IRAO", 0), ("IRAF", 1)])
def test_unsupported_region_or_revision_cannot_be_prepared(environment, code, revision):
    env = environment
    write_zip(env.source, {"white.nds": rom_bytes(code, revision)})
    env.service.scan(retrobat_path=str(env.root))
    with pytest.raises(ValueError, match="profil mémoire"):
        env.service.prepare(env.selection)
    assert not env.service.store.path.exists()


def test_archive_change_gets_new_cache_preserving_previous_extraction(environment):
    env = environment
    old = Path(env.service.prepare(env.selection)["profile"]["rom_path"])
    before = old.read_bytes()
    changed = bytearray(before)
    changed[-1] ^= 255
    write_zip(env.source, {"white.nds": changed})
    result = env.service.prepare_play("white")
    new = Path(result["profile"]["rom_path"])
    assert result["health"]["ready"] and result["health"]["changed"]
    assert old != new and old.read_bytes() == before and new.read_bytes() == changed
    assert not env.service.prepare_play("white")["health"]["changed"]


def test_corrupt_cache_is_never_launched_or_silently_replaced(environment):
    env = environment
    prepared = Path(env.service.prepare(env.selection)["profile"]["rom_path"])
    prepared.write_bytes(rom_bytes("IRBF"))
    with pytest.raises(ValueError):
        env.service.prepare_play("white")
    assert prepared.read_bytes() == rom_bytes("IRBF")


def test_missing_original_source_is_not_hidden_by_existing_cache(environment):
    env = environment
    env.service.prepare(env.selection)
    env.source.unlink()
    with pytest.raises(ValueError, match="introuvable"):
        env.service.prepare_play("white")


def test_changed_launch_path_requires_new_diagnostic(environment):
    env = environment
    env.service.prepare(env.selection)
    store, values = env.service._preferences()
    values["launch_profiles"]["white"]["emulator_path"] = str(env.root / "elsewhere.exe")
    store.save(values)
    with pytest.raises(ValueError, match="Profil modifié"):
        env.service.prepare_play("white")


def test_external_ini_change_is_reported_and_checked(environment):
    env = environment
    env.service.prepare(env.selection)
    env.ini.write_bytes(env.ini.read_bytes() + b"[Video]\nWindow Size=2\n")
    result = env.service.prepare_play("white")
    assert result["health"]["changed"] and result["health"]["ready"]
    assert any("modifiée" in warning for warning in result["health"]["warnings"])


def test_corrupt_local_provenance_does_not_overwrite_preferences(environment):
    env = environment
    env.service.prepare(env.selection)
    preference = env.service.base_dir / "game-mode.local.json"
    before = preference.read_bytes()
    env.service.store.path.write_bytes(b"invalid")
    with pytest.raises(ValueError, match="illisible"):
        env.service.prepare(env.selection)
    assert preference.read_bytes() == before


def test_cache_cleanup_refuses_while_configured_emulator_runs(environment, monkeypatch):
    from app.services.emulator_window_manager import EmulatorWindowManager
    env = environment
    rom = Path(env.service.prepare(env.selection)["profile"]["rom_path"])
    monkeypatch.setattr(EmulatorWindowManager, "running_executable", lambda *args: True)
    with pytest.raises(ValueError, match="Fermez"):
        env.service.cleanup("extracted_roms", confirmed=True)
    assert rom.is_file()


def test_no_setup_cannot_bypass_play_preflight(environment):
    with pytest.raises(ValueError, match="Préparez"):
        environment.service.prepare_play("white")


def test_missing_lua_can_prepare_but_never_report_ready(environment):
    env = environment
    for name in env.blobs:
        (env.exe.parent / name).unlink()
    result = env.service.prepare(env.selection)
    assert result["health"]["lua_status"]["status"] == "missing"
    assert not result["health"]["ready"]
    assert result["health"]["launch_ready"]  # game can open while Lua repair remains explicit
    assert env.service.is_configured("white")
