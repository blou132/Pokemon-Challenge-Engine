"""Automatic discovery/preparation with synthetic files, never a real emulator run."""

from copy import deepcopy
from pathlib import Path

import pytest

from app.services.auto_setup_service import AutoSetupService
from app.services.config_service import AppConfig
from app.services.retrobat_discovery_service import RetroBatDiscoveryService
from app.services.save_discovery_service import SaveDiscoveryService
from app.services.lua_runtime_installer import LuaRuntimeInstaller
from test_auto_discovery import rom_bytes, write_zip
from test_auto_setup_service import environment
from test_lua_runtime_setup import pe_bytes


@pytest.fixture
def automatic(environment, monkeypatch):
    env = environment
    # The same production lookup finds C:/RetroBat, represented by this temp drive.
    monkeypatch.setattr(RetroBatDiscoveryService, "_drives", staticmethod(lambda: (env.root.parent,)))
    env.service.legacy.retrobat_path = str(env.root)
    monkeypatch.setattr(LuaRuntimeInstaller, "install", lambda *args, **kwargs: pytest.fail("Unconsented Lua installation"))
    return env


def test_startup_detects_zip_save_emulator_and_prepares_only_owned_cache(automatic):
    env = automatic
    originals = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in (env.source, env.exe, env.ini, env.save)}
    report = env.service.automatic_setup()
    assert report["ready"] and report["prepared_games"] == ["white"]
    assert report["game_states"]["white"]["status"] == "ready"
    assert report["game_states"]["white"]["save_path"] == str(env.save)
    assert report["game_states"]["white"]["emulator_path"] == str(env.exe)
    assert {key: value["status"] for key, value in report["game_states"].items() if key != "white"} == {
        "black": "not_found", "black2": "not_found", "white2": "not_found"}
    profile = env.service._preferences()[1]["launch_profiles"]["white"]
    assert Path(profile["rom_path"]).is_relative_to(env.service.cache_root)
    assert Path(profile["rom_path"]).read_bytes() == rom_bytes()
    assert env.service.prepare_play("white")["health"]["ready"]
    assert originals == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in originals}


def test_no_games_reports_missing_states_without_global_exception(automatic):
    env = automatic
    env.source.unlink()
    report = env.service.automatic_setup()
    assert not report["ready"] and report["prepared_games"] == []
    assert all(row["status"] == "not_found" and "RetroBat" in row["message"] for row in report["game_states"].values())
    assert not env.service.store.path.exists()


def test_multiple_emulators_require_choice_until_one_is_explicit(automatic):
    env = automatic
    other = env.exe.with_name("alternative.exe")
    other.write_bytes(pe_bytes(markers=b"DeSmuME lua51.dll"))
    report = env.service.automatic_setup()
    assert report["game_states"]["white"]["status"] == "needs_choice"
    assert "DeSmuME" in report["game_states"]["white"]["message"]
    assert not env.service.store.path.exists()
    store, preferences = env.service._preferences()
    preferences["launch_profiles"]["white"]["emulator_path"] = str(env.exe)
    store.save(preferences)
    assert env.service.automatic_setup()["game_states"]["white"]["status"] == "ready"


def test_multiple_saves_require_choice_and_valid_manual_save_is_retained(automatic):
    env = automatic
    extra = env.source.with_suffix(".dsv")
    extra.write_bytes(b"another synthetic save")
    report = env.service.automatic_setup()
    assert report["game_states"]["white"]["status"] == "needs_choice"
    assert "sauvegardes" in report["game_states"]["white"]["message"]
    assert not env.service.store.path.exists()
    store, preferences = env.service._preferences()
    preferences["launch_profiles"]["white"]["save_path"] = str(env.save)
    store.save(preferences)
    ready = env.service.automatic_setup()["game_states"]["white"]
    assert ready["status"] == "ready" and ready["save_path"] == str(env.save)


def test_no_existing_save_allows_new_game(automatic):
    automatic.save.unlink()
    entry = automatic.service.automatic_setup()["game_states"]["white"]
    assert entry["status"] == "ready" and entry["save_path"] == ""
    assert "Aucune sauvegarde" in entry["save_message"]


def test_explicit_no_save_association_survives_automatic_detection_and_restart(automatic):
    env = automatic
    original = env.save.read_bytes()
    env.service.prepare(env.selection | {"save_path": ""})
    report = env.service.automatic_setup(force=True)
    assert report["game_states"]["white"]["status"] == "ready"
    assert report["game_states"]["white"]["save_path"] == ""
    assert "Aucune sauvegarde associée" in report["game_states"]["white"]["save_message"]
    assert report["games"][0]["saves"]  # A manual association remains available.
    assert env.service._preferences()[1]["launch_profiles"]["white"]["save_path"] == ""
    restarted = AutoSetupService(env.service.base_dir, env.service.legacy)
    assert restarted.automatic_setup()["game_states"]["white"]["save_path"] == ""
    assert env.save.read_bytes() == original


def test_save_appearing_later_does_not_replace_prepared_absence_of_association(automatic):
    env = automatic
    env.save.unlink()
    assert env.service.automatic_setup()["game_states"]["white"]["save_path"] == ""
    env.save.write_bytes(b"new synthetic save created after preparation")
    report = env.service.automatic_setup()
    assert not report["cached"]
    assert report["game_states"]["white"]["status"] == "ready"
    assert report["game_states"]["white"]["save_path"] == ""
    assert report["games"][0]["proposed_save"] == str(env.save)


def test_clearing_save_in_existing_launch_profile_is_an_explicit_choice(automatic):
    env = automatic
    env.service.prepare(env.selection)
    store, preferences = env.service._preferences()
    preferences["launch_profiles"]["white"]["save_path"] = ""
    store.save(preferences)
    report = env.service.automatic_setup(force=True)
    assert report["game_states"]["white"]["status"] == "ready"
    assert report["game_states"]["white"]["save_path"] == ""
    assert env.service.store.load()["games"]["white"]["save_path"] == ""


def test_missing_lua_is_a_per_game_action_without_network_or_external_writes(automatic):
    for name in automatic.blobs:
        (automatic.exe.parent / name).unlink()
    report = automatic.service.automatic_setup()
    assert not report["ready"] and report["game_states"]["white"]["status"] == "lua_required"
    assert automatic.service.is_configured("white")
    assert not (automatic.exe.parent / "lua51.dll").exists()


def test_valid_explicit_rom_ini_and_preferences_survive_new_candidates(automatic):
    env = automatic
    selected = env.source.with_name("chosen.nds")
    selected.write_bytes(rom_bytes())
    manual_ini = env.exe.parent / "custom.ini"
    manual_ini.write_bytes(env.ini.read_bytes())
    store, preferences = env.service._preferences()
    options = preferences["launch_profiles"]["white"]
    options.update(rom_path=str(selected), emulator_path=str(env.exe), ini_path=str(manual_ini),
                   backup_on_launch=True, speed="MAX")
    store.save(preferences)
    report = env.service.automatic_setup()
    assert report["game_states"]["white"]["status"] == "ready"
    after = env.service._preferences()[1]["launch_profiles"]["white"]
    assert after["rom_path"] == str(selected) and after["ini_path"] == str(manual_ini)
    assert after["backup_on_launch"] and after["speed"] == "MAX"
    restarted = AutoSetupService(env.service.base_dir, env.service.legacy)
    assert restarted.automatic_setup()["game_states"]["white"]["profile"]["rom_path"] == str(selected)


def test_manual_rom_for_different_game_is_not_silently_replaced(automatic):
    env = automatic
    selected = env.source.with_name("chosen.nds")
    selected.write_bytes(rom_bytes("IRBF"))
    store, preferences = env.service._preferences()
    preferences["launch_profiles"]["white"]["rom_path"] = str(selected)
    store.save(preferences)
    result = env.service.automatic_setup()
    assert result["game_states"]["white"]["status"] == "needs_choice"
    assert env.service._preferences()[1]["launch_profiles"]["white"]["rom_path"] == str(selected)


def test_moved_source_is_repaired_when_identical_candidate_is_unique(automatic):
    env = automatic
    env.service.automatic_setup()
    moved = env.source.with_name("moved.zip")
    env.source.rename(moved)
    result = env.service.automatic_setup()
    assert not result["cached"] and result["game_states"]["white"]["status"] == "ready"
    assert env.service.store.load()["games"]["white"]["source_path"] == str(moved)
    assert env.service.prepare_play("white")["health"]["ready"]


def test_different_copy_cannot_silently_replace_missing_original(automatic):
    env = automatic
    env.service.automatic_setup()
    env.source.unlink()
    new = env.source.with_name("different.zip")
    content = bytearray(rom_bytes())
    content[-1] ^= 1
    write_zip(new, {"white.nds": content})
    result = env.service.automatic_setup()
    assert result["game_states"]["white"]["status"] == "needs_choice"
    assert env.service.store.load()["games"]["white"]["source_path"] == str(env.source)


def test_unchanged_detection_uses_signatures_and_returns_detached_report(automatic, monkeypatch):
    env = automatic
    env.service.automatic_setup()
    original_scan = env.service.scan
    monkeypatch.setattr(env.service, "scan", lambda *args, **kwargs: pytest.fail("Unnecessary full scan"))
    result = env.service.automatic_setup()
    assert result["cached"] and result["prepared_games"] == []
    result["game_states"]["white"]["status"] = "caller mutation"
    assert env.service.automatic_setup()["game_states"]["white"]["status"] == "ready"
    monkeypatch.setattr(env.service, "scan", original_scan)
    assert not env.service.automatic_setup(force=True)["cached"]


def test_file_changes_and_library_additions_invalidate_cached_report(automatic):
    env = automatic
    env.service.automatic_setup()
    added = env.source.with_name("black.nds")
    added.write_bytes(rom_bytes("IRBF"))
    result = env.service.automatic_setup()
    assert not result["cached"] and result["game_states"]["black"]["status"] == "ready"
    (env.exe.parent / "lua51.dll").unlink()
    result = env.service.automatic_setup()
    assert not result["cached"] and result["game_states"]["white"]["status"] == "lua_required"


def test_scope_prepares_only_requested_game(automatic):
    env = automatic
    env.source.with_name("black.nds").write_bytes(rom_bytes("IRBF"))
    result = env.service.automatic_setup(game_id="white")
    assert result["ready"] and result["prepared_games"] == ["white"]
    assert env.service.is_configured("white") and not env.service.is_configured("black")


def test_scoped_launch_does_not_inspect_unrelated_game_saves(automatic, monkeypatch):
    env = automatic
    env.source.with_name("black.nds").write_bytes(rom_bytes("IRBF"))
    original = SaveDiscoveryService.discover

    def guarded(finder, candidate, **kwargs):
        assert candidate.game_id == "white", "Another game's saves must not participate in this launch"
        return original(finder, candidate, **kwargs)

    monkeypatch.setattr(SaveDiscoveryService, "discover", guarded)
    assert env.service.automatic_setup(game_id="white")["ready"]


def test_manual_settings_override_only_explicitly_changed_launch_paths(automatic):
    env = automatic
    env.service.automatic_setup()
    store, preferences = env.service._preferences()
    preferences["launch_profiles"]["white"]["speed"] = "MAX"
    preferences["launch_profiles"]["black2"]["rom_path"] = "preserved-manual.nds"
    store.save(preferences)
    previous = deepcopy(env.service.legacy)
    current = deepcopy(previous)
    chosen = env.source.with_name("chosen.nds")
    chosen.write_bytes(rom_bytes())
    current.rom_paths["white"] = str(chosen)
    env.service.apply_manual_config(previous, current)
    after = env.service._preferences()[1]["launch_profiles"]
    assert after["white"]["rom_path"] == str(chosen) and after["white"]["speed"] == "MAX"
    assert after["black2"]["rom_path"] == "preserved-manual.nds"
    assert env.service.automatic_setup()["game_states"]["white"]["profile"]["rom_path"] == str(chosen)


def test_global_cache_can_satisfy_selected_game_without_repeating_scan(automatic, monkeypatch):
    automatic.service.automatic_setup()
    monkeypatch.setattr(automatic.service, "scan", lambda *args, **kwargs: pytest.fail("Unnecessary scan"))
    assert automatic.service.automatic_setup(game_id="white")["cached"]


def test_corrupt_provenance_and_preferences_are_not_overwritten(automatic):
    env = automatic
    env.service.automatic_setup()
    path = env.service.base_dir / "game-mode.local.json"
    before = path.read_bytes()
    env.service.store.path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="illisible"):
        env.service.automatic_setup()
    assert path.read_bytes() == before and env.service.store.path.read_bytes() == b"corrupt"


def test_auto_setup_instances_share_mutation_lock(automatic):
    other = AutoSetupService(automatic.service.base_dir, automatic.service.legacy)
    assert other._lock is automatic.service._lock


def test_archive_with_multiple_members_requires_initial_choice(automatic):
    env = automatic
    write_zip(env.source, {"white.nds": rom_bytes(), "other.nds": rom_bytes("ABCD")})
    result = env.service.automatic_setup()
    assert result["game_states"]["white"]["status"] == "needs_choice"
    assert not env.service.store.path.exists()


def test_unverified_region_does_not_use_french_profile(automatic):
    write_zip(automatic.source, {"white.nds": rom_bytes("IRAO")})
    result = automatic.service.automatic_setup()
    assert result["game_states"]["white"]["status"] == "needs_attention"
    assert not automatic.service.store.path.exists()
