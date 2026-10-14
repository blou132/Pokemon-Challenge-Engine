"""Synthetic integration of the real copy/provenance pipeline, without Java."""

from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.models.challenge import Challenge
from app.models.run import utc_now
from app.services import rom_transformation_service as transformation_module
from app.services.run_transformation_provider import RunTransformationProvider
from test_rom_transformation import transformation  # shared fake-tool fixture
from test_run_isolation import environment, create, tree  # owned PE/Lua fixture


def challenge(*, configured=True, seed=512):
    settings = {"enforcement": "soft", "rule_parameters": {}}
    if configured:
        settings["rom_transformation"] = {"kind": "zx", "categories": ["wild", "types"], "balanced": False}
    return Challenge("white", "custom", ["randomizer"], {"randomizer": "required"}, settings, None, seed)


@pytest.fixture
def randomizer(environment, transformation, monkeypatch):
    monkeypatch.setattr(transformation_module.RomTransformationService, "from_local_config",
                        classmethod(lambda cls, base: transformation.service))
    return environment, transformation


def test_new_randomizer_owns_derived_rom_and_all_provenance(randomizer):
    env, tool = randomizer
    original = tree(env.source)
    run = create(env, challenge=challenge())
    isolated = env.service.isolate(run)
    root = env.service.directory(isolated)
    assert Path(isolated.launch_profile["rom_path"]).read_bytes() != env.rom.read_bytes()
    assert not Path(isolated.save_path).exists()
    assert not (root / "transformation/derived.nds").exists()
    assert (root / "transformation/manifest.json").exists()
    assert (root / "transformation/report.json").exists()
    assert tree(env.source) == original
    assert tool.calls[-1][9] == "512"
    env.service.validate(env.manager.load(run.run_id))


@pytest.mark.parametrize("state", ["import_save", "import_states", "save_reference", "started", "played",
                                    "elapsed", "zone", "badges", "active"])
def test_randomization_requires_new_adventure_without_import(randomizer, state):
    env, tool = randomizer
    run = create(env, challenge=challenge())
    kwargs = {}
    if state == "import_save": kwargs["import_save"] = env.save
    elif state == "import_states": kwargs["import_states"] = True
    elif state == "save_reference": run.save_path = str(env.save)
    elif state == "started": run.started_at = utc_now()
    elif state == "played": run.last_played_at = utc_now()
    elif state == "elapsed":
        run.total_play_seconds = 10
        stamp = utc_now()
        run.sessions = [{"session_id": str(uuid4()), "started_at": stamp, "last_heartbeat": stamp,
                         "ended_at": stamp, "duration": 10}]
    elif state == "zone": run.current_zone = "Known zone"
    elif state == "badges": run.badges = 0
    elif state == "active": run.status = "active"
    env.manager.save(run)
    source = tree(env.source)
    with pytest.raises(ValueError, match="nouvelle aventure"):
        env.service.isolate(run, **kwargs)
    assert tree(env.source) == source
    assert not env.service.directory(run).exists()
    assert not tool.calls


def test_historical_randomizer_declaration_never_transforms_implicitly(randomizer):
    env, tool = randomizer
    run = create(env, challenge=challenge(configured=False))
    isolated = env.service.isolate(run)
    assert Path(isolated.launch_profile["rom_path"]).read_bytes() == env.rom.read_bytes()
    assert not tool.calls
    assert RunTransformationProvider(env.manager.root).for_run(isolated) is None


def test_failure_preserves_run_and_originals_and_is_retryable(randomizer):
    env, tool = randomizer
    run = create(env, challenge=challenge())
    original, metadata = tree(env.source), env.manager.load(run.run_id).to_dict()
    tool.changes["report"] = {"invalid": True}
    with pytest.raises(ValueError):
        env.service.isolate(run)
    assert not env.service.directory(run).exists()
    assert env.manager.load(run.run_id).to_dict() == metadata
    assert tree(env.source) == original
    tool.changes.clear()
    isolated = env.service.isolate(env.manager.load(run.run_id))
    env.service.validate(isolated)


@pytest.mark.parametrize("artifact", ["manifest", "report", "adapter", "rom", "isolation"])
def test_changed_derivation_evidence_is_rejected_on_resume(randomizer, artifact):
    env, tool = randomizer
    run = env.service.isolate(create(env, challenge=challenge()))
    root = env.service.directory(run)
    targets = {"manifest": root / "transformation/manifest.json", "report": root / "transformation/report.json",
               "adapter": root / "transformation/PceRandomizer.java", "rom": Path(run.launch_profile["rom_path"]),
               "isolation": root / "isolation.json"}
    if artifact == "isolation":
        data = json.loads(targets[artifact].read_text())
        data.pop("transformation")
        targets[artifact].write_text(json.dumps(data))
    else:
        with targets[artifact].open("ab") as handle: handle.write(b"changed")
    with pytest.raises(ValueError):
        env.service.validate(run)


def test_provider_returns_effective_data_and_reuses_only_unchanged_artifacts(randomizer, monkeypatch):
    env, tool = randomizer
    run = env.service.isolate(create(env, challenge=challenge()))
    provider = RunTransformationProvider(env.manager.root)
    first = provider.for_run(run)
    assert first["game_id"] == "white"
    assert first["rom_sha256"] == run.rom_fingerprint
    assert len(first["pokemon"]) == 649
    assert first["categories"] == ["wild", "types"]
    def no_hash(*args): raise AssertionError("Should use verified signatures cache")
    monkeypatch.setattr(transformation_module, "file_hash", no_hash)
    first["pokemon"][0]["types"] = ["fire"]
    assert provider.for_run(run)["pokemon"][0]["types"] == ["normal"]


def test_provider_detects_tampering_after_initial_load(randomizer):
    env, tool = randomizer
    run = env.service.isolate(create(env, challenge=challenge()))
    provider = RunTransformationProvider(env.manager.root)
    provider.for_run(run)
    path = env.service.directory(run) / "transformation/report.json"
    data = json.loads(path.read_text())
    data["pokemon"][0]["types"] = ["fire"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="provenance"):
        provider.for_run(run)


def test_provider_refuses_other_adventure_rom(randomizer):
    env, tool = randomizer
    first = env.service.isolate(create(env, challenge=challenge()))
    second = env.service.isolate(create(env, challenge=challenge()))
    corrupted = deepcopy(first)
    corrupted.launch_profile["rom_path"] = second.launch_profile["rom_path"]
    with pytest.raises(ValueError, match="espace"):
        RunTransformationProvider(env.manager.root).for_run(corrupted)


def test_prepared_randomizer_does_not_need_java_again(randomizer):
    env, tool = randomizer
    run = env.service.isolate(create(env, challenge=challenge()))
    calls = len(tool.calls)
    tool.service.java_path.unlink()
    tool.service.jar_path.unlink()
    env.service.validate(run)
    env.service.isolate(run)
    assert RunTransformationProvider(env.manager.root).for_run(run)["pokemon"]
    assert len(tool.calls) == calls
