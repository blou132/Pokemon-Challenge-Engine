"""New-adventure defaults only; fixture executables are never launched."""

from copy import deepcopy
import shutil

import pytest

from app.core.profile_manager import ProfileManager
from app.core.run_manager import RunManager
from app.services import melonds_runtime
from app.services.config_service import AppConfig
from app.services.game_mode_config import launch_defaults
from app.services.run_launch_service import RunLaunchService
from app.ui.run_dialogs import NewRunDialog
from test_melonds_run import component
from test_run_creation import choose, close, profile, qt_app


@pytest.fixture
def installed_component(tmp_path, component, monkeypatch):
    installation = tmp_path / "portable"
    monkeypatch.setattr(melonds_runtime, "__file__", str(installation / "app/services/melonds_runtime.py"))
    folder = installation / "third-party/melonDS"
    shutil.copytree(component.parent, folder)
    return folder / component.name


def legacy_options(base):
    config = AppConfig(desmume_path="existing-desmume.exe", rom_paths={"white": "original-white.nds"})
    return {"white": launch_defaults("white", config, base)}


def test_verified_bundle_is_default_only_in_new_dialog(qt_app, catalog, tmp_path, installed_component):
    options = legacy_options(tmp_path)
    before = deepcopy(options)
    dialog = NewRunDialog(catalog, [], options, base_dir=tmp_path)
    try:
        choose(dialog.game_combo, "white")
        assert dialog.emulator_combo.currentData() == "melonds"
        assert dialog.emulator_combo.model().item(dialog.emulator_combo.findData("desmume")).isEnabled()
        selected = dialog.selection()["launch_profile"]
        assert selected["emulator_kind"] == "melonds"
        assert selected["emulator_path"] == str(installed_component)
        assert options == before and dialog.launch_profiles == before
    finally:
        close(dialog, qt_app)


@pytest.mark.parametrize("state", ["missing", "changed", "untrusted"])
def test_missing_or_unverified_bundle_keeps_desmume_default(qt_app, catalog, tmp_path, installed_component, state):
    marker = installed_component.parent / "pce-bridge.json"
    if state == "missing":
        marker.unlink()
    elif state == "changed":
        installed_component.write_bytes(b"modified fixture executable")
    else:
        marker.write_bytes(marker.read_bytes() + b" ")
    dialog = NewRunDialog(catalog, [], legacy_options(tmp_path), base_dir=tmp_path)
    try:
        choose(dialog.game_combo, "white")
        assert dialog.melonds_executable is None
        assert dialog.emulator_combo.currentData() == "desmume"
        assert not dialog.emulator_combo.model().item(dialog.emulator_combo.findData("melonds")).isEnabled()
        assert dialog.selection()["launch_profile"]["emulator_kind"] == "desmume"
    finally:
        close(dialog, qt_app)


def test_explicit_desmume_choice_survives_game_and_profile_changes(qt_app, catalog, tmp_path, installed_component):
    source = profile(catalog)
    options = legacy_options(tmp_path)
    before = deepcopy(options)
    dialog = NewRunDialog(catalog, [source], options, base_dir=tmp_path)
    try:
        assert dialog.emulator_combo.currentData() == "melonds"
        choose(dialog.emulator_combo, "desmume")
        choose(dialog.game_combo, "white")
        choose(dialog.profile_combo, source.id)
        selected = dialog.selection()["launch_profile"]
        assert dialog.emulator_combo.currentData() == "desmume"
        assert selected["emulator_kind"] == "desmume"
        assert selected["emulator_path"] == before["white"]["emulator_path"]
        assert options == before and dialog.launch_profiles == before
    finally:
        close(dialog, qt_app)


@pytest.mark.parametrize("engine", ["melonds", "desmume"])
def test_selected_engine_persists_without_changing_old_adventure_or_profile(qt_app, catalog, tmp_path, installed_component, engine):
    base = tmp_path / "data"
    manager = RunManager(base / "runs")
    profiles = ProfileManager(base / "profiles")
    source = profiles.create("Existing challenge", profile(catalog).challenge)
    options = legacy_options(base)
    before_options = deepcopy(options)
    previous = manager.create("Existing adventure", "white", launch_profile=options["white"])
    old_path = manager.root / previous.run_id / "run.json"
    before_run = old_path.read_bytes()
    before_profiles = {path: path.read_bytes() for path in (base / "profiles").rglob("*.json")}
    dialog = NewRunDialog(catalog, [source], options, profile=source, base_dir=base)
    try:
        assert dialog.emulator_combo.currentData() == "melonds"
        choose(dialog.emulator_combo, engine)
        values = dialog.selection()
        snapshot = RunLaunchService(base, AppConfig()).snapshot("white", values["launch_profile"], values["save_path"])
        snapshot["_isolation_pending"] = True
        created = manager.create("New adventure", "white", challenge=source.challenge,
                                 profile_id=source.id, launch_profile=snapshot)
        reread = RunManager(base / "runs").load(created.run_id)
        assert reread.launch_profile["emulator_kind"] == engine
        expected = str(installed_component) if engine == "melonds" else options["white"]["emulator_path"]
        assert reread.launch_profile["emulator_path"] == expected
        assert old_path.read_bytes() == before_run
        assert {path: path.read_bytes() for path in before_profiles} == before_profiles
        assert options == before_options
    finally:
        close(dialog, qt_app)


@pytest.mark.parametrize("available", [False, True])
def test_desmume_selection_never_reuses_a_melonds_launch_profile(qt_app, catalog, tmp_path, installed_component, available):
    if not available:
        (installed_component.parent / "pce-bridge.json").unlink()
    options = legacy_options(tmp_path)
    options["white"].update(emulator_kind="melonds", emulator_path=str(installed_component),
                            ini_path="existing-melonds.toml", lua_connection="manual")
    before = deepcopy(options)
    dialog = NewRunDialog(catalog, [], options, base_dir=tmp_path)
    try:
        choose(dialog.game_combo, "white")
        choose(dialog.emulator_combo, "desmume")
        selected = dialog.selection()["launch_profile"]
        assert selected["emulator_kind"] == "desmume"
        assert selected["emulator_path"] == selected["ini_path"] == ""
        assert selected["lua_connection"] == "ask"
        assert options == before and dialog.launch_profiles == before
    finally:
        close(dialog, qt_app)
