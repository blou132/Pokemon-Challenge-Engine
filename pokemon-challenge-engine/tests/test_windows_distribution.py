"""Storage boundaries and real old-format migration, using synthetic game fixtures."""

import json
import os
from pathlib import Path
import sys

import pytest

from app.core.profile_manager import ProfileManager
from app.core.run_manager import RunManager
from app.models.challenge import Challenge
from app.paths import PORTABLE_MARKER, resolve_app_paths
from app.services import user_data_import
from app.services.config_service import AppConfig, ConfigService
from app.services.run_isolation_service import RunIsolationService
from app.services.save_manager_service import SaveManagerService
from app.services.user_data_import import execute_import, plan_import
from test_run_isolation import create, environment, tree


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    installation = tmp_path / "Distribution avec espaces"
    resources = installation / "_internal"
    resources.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(installation / "Pokemon-Challenge-Engine.exe"))
    monkeypatch.setattr("app.paths.resource_dir", lambda: resources)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    return installation, resources


def test_frozen_storage_is_stable_outside_resources_and_cwd(frozen, tmp_path, monkeypatch):
    installation, resources = frozen
    monkeypatch.chdir(tmp_path)
    first = resolve_app_paths()
    assert first.data == tmp_path / "local/Pokemon-Challenge-Engine"
    ConfigService(first.data / "config.json").save(AppConfig(save_path="preserved"))
    monkeypatch.chdir(resources)
    assert resolve_app_paths() == first
    assert ConfigService(first.data / "config.json").load().save_path == "preserved"
    assert not list(resources.iterdir())


def test_portable_marker_selects_adjacent_store_without_moving_previous_data(frozen):
    installation, resources = frozen
    previous = resolve_app_paths().data
    (previous / "preserve.txt").write_text("existing")
    (installation / PORTABLE_MARKER).write_text('{"schema_version":1}')
    paths = resolve_app_paths()
    assert paths.portable and paths.data == installation / "user-data"
    assert (previous / "preserve.txt").read_text() == "existing"


@pytest.mark.parametrize("marker", ['{}', '{"schema_version":2}', '{"schema_version":1,"path":"../outside"}', 'invalid'])
def test_invalid_portable_marker_fails_without_hidden_fallback(frozen, marker):
    installation, resources = frozen
    (installation / PORTABLE_MARKER).write_text(marker)
    with pytest.raises(ValueError):
        resolve_app_paths()
    assert not (installation / "user-data").exists()


def test_explicit_data_rejects_relative_and_resource_paths(frozen):
    installation, resources = frozen
    for path in (Path("relative"), resources, resources / "user-data"):
        with pytest.raises(ValueError):
            resolve_app_paths(path)


def test_import_preserves_source_and_existing_preferences(tmp_path):
    source, target = tmp_path / "ancienne installation", tmp_path / "nouvelle installation"
    manager = RunManager(source / "runs")
    run = manager.create("Partie conservée", "black")
    manager.update(run.run_id, lambda item: setattr(item, "badges", 4))
    challenge = Challenge("black", "normal", [], {}, {"enforcement": "soft", "rule_parameters": {}}, None, 4)
    profile = ProfileManager(source / "profiles").create("Modèle", challenge)
    ConfigService(source / "config.json").save(AppConfig(save_path="old"))
    ConfigService(target / "config.json").save(AppConfig(save_path="current"))
    before = tree(source)
    plan = plan_import(source, target)
    result = execute_import(plan)
    assert result == {"runs": 1, "profiles": 1, "preferences": 0, "skipped_preferences": ["config.json"]}
    assert RunManager(target / "runs").load(run.run_id).badges == 4
    assert ProfileManager(target / "profiles").load(profile.id).challenge == challenge
    assert ConfigService(target / "config.json").load().save_path == "current"
    assert tree(source) == before
    after = tree(target)
    with pytest.raises(ValueError, match="existe déjà"):
        plan_import(source, target)
    assert tree(target) == after


def test_old_isolated_adventure_relocates_save_states_ini_and_backup_lookup(environment):
    env = environment
    env.manager = RunManager(env.tmp / "ancienne" / "runs")
    env.service = RunIsolationService(env.manager, running_probe=lambda _: False)
    run = env.service.isolate(create(env), import_save=env.save, import_states=True)
    backups = SaveManagerService(Path(run.launch_profile["backup_directory"]))
    record = backups.backup(run.save_path, "white")
    before = tree(env.manager.root.parent)
    target = env.tmp / "nouvelle avec espaces"
    execute_import(plan_import(env.manager.root.parent, target))
    manager = RunManager(target / "runs")
    copied = manager.load(run.run_id)
    RunIsolationService(manager, running_probe=lambda _: False).validate(copied)
    assert Path(copied.save_path).read_bytes() == Path(run.save_path).read_bytes()
    assert copied.save_path != run.save_path
    states = Path(copied.launch_profile["save_state_directory"])
    assert len(list(states.glob("*.ds*"))) == 2
    copied_backups = SaveManagerService(Path(copied.launch_profile["backup_directory"]))
    assert copied_backups.list_backups_for_save(copied.save_path, "white")[0].sha256 == record.sha256
    assert tree(env.manager.root.parent) == before


def test_source_changed_during_copy_is_not_published(tmp_path, monkeypatch):
    source, target = tmp_path / "old", tmp_path / "new"
    run = RunManager(source / "runs").create("Before", "black")
    plan = plan_import(source, target)
    original = user_data_import._copy
    def changed(path, destination, signatures):
        original(path, destination, signatures)
        if path.name == "run.json":
            path.write_bytes(path.read_bytes() + b" ")
    monkeypatch.setattr(user_data_import, "_copy", changed)
    with pytest.raises(ValueError, match="changé"):
        execute_import(plan)
    assert not (target / "runs" / run.run_id).exists()


def test_source_transaction_is_never_recovered_by_preview(tmp_path):
    source, target = tmp_path / "old", tmp_path / "new"
    profile = ProfileManager(source / "profiles").create("Model", Challenge("black", "normal", [], {},
                                                           {"enforcement": "soft", "rule_parameters": {}}, None, 0))
    journal = source / "profiles" / profile.id / ".transaction.json"
    journal.write_text('{"pending": true}')
    before = tree(source)
    with pytest.raises(ValueError, match="interrompue"):
        plan_import(source, target)
    assert tree(source) == before


def test_hardlinked_file_is_rejected_without_publishing(tmp_path):
    source, target = tmp_path / "old", tmp_path / "new"
    run = RunManager(source / "runs").create("Before", "black")
    shared = tmp_path / "shared.txt"
    shared.write_text("must not copy a shared file")
    os.link(shared, source / "runs" / run.run_id / "shared.txt")
    with pytest.raises(ValueError, match="partagés"):
        execute_import(plan_import(source, target))
    assert shared.read_text() == "must not copy a shared file"
    assert not (target / "runs" / run.run_id).exists()


def test_new_destination_collision_after_preview_is_preserved(tmp_path):
    source, target = tmp_path / "old", tmp_path / "new"
    run = RunManager(source / "runs").create("Before", "black")
    plan = plan_import(source, target)
    collision = target / "runs" / run.run_id
    collision.mkdir(parents=True)
    (collision / "keep.txt").write_text("preserve")
    with pytest.raises(ValueError, match="existe déjà"):
        execute_import(plan)
    assert (collision / "keep.txt").read_text() == "preserve"
