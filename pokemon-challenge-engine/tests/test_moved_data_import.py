"""Controlled imports of physically moved stores; no emulator is executed."""

import json
from pathlib import Path

import pytest

from app.core.run_manager import RunManager
from app.services.emulator_settings_service import IniDocument
from app.services.melonds_run_service import MelonDSRunService
from app.services.run_isolation_service import RunIsolationService
from app.services.save_manager_service import SaveManagerService
from app.services.user_data_import import execute_import, plan_import
from test_melonds_run import component
from test_run_isolation import create, environment, tree
from test_save_conversion import dsv


def moved_store(env, component, kind):
    source = env.tmp / "old"
    env.manager = RunManager(source / "runs")
    env.service = RunIsolationService(env.manager, running_probe=lambda _: False)
    env.save.write_bytes(dsv())
    run = env.service.isolate(create(env), import_save=env.save, import_states=True)
    if kind == "melonds":
        run = MelonDSRunService(env.manager, running_probe=lambda _: False).prepare(run, component, migrate=True)
    env.manager.update(run.run_id, lambda item: setattr(item, "badges", 3))
    run = env.manager.load(run.run_id)
    backup = SaveManagerService(Path(run.launch_profile["backup_directory"])).backup(run.save_path, "white")
    moved = env.tmp / "moved"
    # This is only the synthetic test store, never a real user directory.
    source.rename(moved)
    return source, moved, run, backup


@pytest.mark.parametrize("kind", ["desmume", "melonds"])
def test_moved_store_import_rebases_only_owned_data(environment, component, kind, monkeypatch):
    env = environment
    original, moved, run, backup = moved_store(env, component, kind)
    before, external_before = tree(moved), tree(env.source)
    target = env.tmp / "new"
    original_open, original_stat = Path.open, Path.stat
    def guard_open(path, *args, **kwargs):
        assert not path.is_relative_to(original), "An obsolete path must never be opened"
        return original_open(path, *args, **kwargs)
    def guard_stat(path, *args, **kwargs):
        assert not path.is_relative_to(original), "An obsolete path must never be probed"
        return original_stat(path, *args, **kwargs)
    with monkeypatch.context() as guard:
        guard.setattr(Path, "open", guard_open)
        guard.setattr(Path, "stat", guard_stat)
        execute_import(plan_import(moved, target))
    manager = RunManager(target / "runs")
    copied = manager.load(run.run_id)
    RunIsolationService(manager, running_probe=lambda _: False).validate(copied)
    assert copied.badges == 3
    assert copied.history == run.history
    assert copied.rules_snapshot == run.rules_snapshot
    assert copied.launch_profile["_source"] == run.launch_profile["_source"]
    assert Path(copied.save_path).read_bytes() == (dsv()[:512 * 1024] if kind == "melonds" else dsv())
    assert SaveManagerService(Path(copied.launch_profile["backup_directory"])).list_backups_for_save(
        copied.save_path, "white")[0].sha256 == backup.sha256
    original_config = "emulator/portable/melonDS.toml" if kind == "melonds" else "emulator/desmume.ini"
    play_name = "play-melonds" if kind == "melonds" else "play"
    changed = {f"runs/{run.run_id}/run.json", f"runs/{run.run_id}/{play_name}/{original_config}",
               f"runs/{run.run_id}/{play_name}/backups/pce-backups.json"}
    after = tree(target)
    for relative, data in before.items():
        if Path(relative).as_posix() not in changed:
            assert after[relative] == data
    assert tree(moved) == before
    assert tree(env.source) == external_before
    assert not original.exists()


@pytest.mark.parametrize("kind", ["desmume", "melonds"])
@pytest.mark.parametrize("damage", ["mixed_save", "external_emulator", "other_uuid", "rom_hash", "config_save", "manifest_owner", "missing_save"])
def test_moved_store_rejects_ambiguous_or_corrupted_ownership(environment, component, kind, damage):
    env = environment
    original, moved, run, _ = moved_store(env, component, kind)
    manager = RunManager(moved / "runs")
    play_name = "play-melonds" if kind == "melonds" else "play"
    play = moved / "runs" / run.run_id / play_name
    if damage in {"mixed_save", "external_emulator", "other_uuid"}:
        def damage_run(item):
            if damage == "mixed_save":
                item.save_path = str(play / "saves" / Path(item.save_path).name)
            elif damage == "external_emulator":
                item.launch_profile["emulator_path"] = str(component)
            else:
                item.launch_profile["rom_path"] = item.launch_profile["rom_path"].replace(
                    run.run_id, "00000000-0000-0000-0000-000000000000")
        manager.update(run.run_id, damage_run)
    elif damage == "rom_hash":
        rom = play / "game" / Path(run.launch_profile["rom_path"]).name
        rom.write_bytes(rom.read_bytes() + b"changed")
    elif damage == "missing_save":
        (play / "saves" / Path(run.save_path).name).unlink()
    elif damage == "manifest_owner":
        marker = play / "isolation.json"
        data = json.loads(marker.read_text(encoding="utf-8"))
        data["owner"] = "unrecognised"
        marker.write_text(json.dumps(data), encoding="utf-8")
    elif kind == "melonds":
        config = play / "emulator/portable/melonDS.toml"
        text = config.read_text(encoding="utf-8")
        text = text.replace(json.dumps(str(original / "runs" / run.run_id / play_name / "saves")),
                            json.dumps(str(env.tmp / "external-saves")))
        config.write_text(text, encoding="utf-8")
    else:
        config = play / "emulator/desmume.ini"
        document = IniDocument(config.read_bytes())
        document.set_text("PathSettings", "Battery", str(env.tmp / "external-saves"))
        config.write_bytes(document.to_bytes())
    before, target = tree(moved), env.tmp / "new"
    with pytest.raises(ValueError):
        execute_import(plan_import(moved, target))
    assert not (target / "runs" / run.run_id).exists()
    assert tree(moved) == before


@pytest.mark.parametrize("kind", ["desmume", "melonds"])
def test_moved_store_collision_never_replaces_existing_adventure(environment, component, kind):
    env = environment
    _, moved, run, _ = moved_store(env, component, kind)
    target = env.tmp / "new"
    plan = plan_import(moved, target)
    collision = target / "runs" / run.run_id
    collision.mkdir(parents=True)
    (collision / "keep.txt").write_text("existing adventure")
    before = tree(moved)
    with pytest.raises(ValueError, match="existe d"):
        execute_import(plan)
    assert tree(target) == {str(Path("runs") / run.run_id / "keep.txt"): b"existing adventure"}
    assert tree(moved) == before


def test_import_staging_does_not_reduce_desmume_destination_path_limit(environment, component):
    env = environment
    _, moved, run, _ = moved_store(env, component, "desmume")
    tail = Path("runs") / run.run_id / "play" / "state-slots" / ("white2-" + "0" * 36 + ".ds9")
    length = 249 - len(str(env.tmp / tail).encode("utf-8")) - 1
    assert length > 0
    target = env.tmp / ("x" * length)
    assert len(str(target / tail).encode("utf-8")) == 249
    execute_import(plan_import(moved, target))
    manager = RunManager(target / "runs")
    copied = manager.load(run.run_id)
    RunIsolationService(manager).validate(copied)
    assert Path(copied.save_path).read_bytes() == dsv()
