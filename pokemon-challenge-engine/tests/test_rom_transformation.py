"""Safety contract tests with a fake tool; these do not validate a playable ROM."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from app.services import rom_transformation_service as module
from app.services.rom_transformation_service import RandomizerOptions, RomTransformationService


def report(code="IRAF", categories=("wild", "starters", "trainers")):
    return {"schema_version": 1, "tool_version": "4.6.1", "game_code": code, "settings_string": "322test",
            "categories": {name: {"before": "a" * 64, "after": ("b" if name in categories else "a") * 64}
                           for name in module.CATEGORIES},
            "pokemon": [{"species_id": species, "form": 0, "types": ["normal"], "evolutions": [], "identity_evolutions": []}
                        for species in range(1, 650)]}


@pytest.fixture
def transformation(tmp_path, monkeypatch):
    java, jar, source = tmp_path / "java.exe", tmp_path / "tool.jar", tmp_path / "source.nds"
    java.write_bytes(b"fake-java")
    jar.write_bytes(b"synthetic-jar")
    monkeypatch.setattr(module, "ZX_JAR_SHA256", hashlib.sha256(jar.read_bytes()).hexdigest())
    header = bytearray(1024)
    header[12:16] = b"IRAF"
    source.write_bytes(header)
    calls = []
    changes = {}

    def execute(command, *, cwd, timeout):
        calls.append(command)
        if command[-1] == "-version":
            return SimpleNamespace(stderr='openjdk version "17.0.1"', stdout="", returncode=0)
        working, output, result = map(Path, command[6:9])
        contents = bytearray(working.read_bytes())
        contents[-1] = 42
        output.write_bytes(contents)
        data = deepcopy(changes.get("report", report(categories=command[10].split(","))))
        result.write_text(json.dumps(data), encoding="utf-8")
        if "action" in changes:
            changes["action"](working, output, result)
        return SimpleNamespace(stderr="", stdout="", returncode=0)

    service = RomTransformationService(java, jar)
    monkeypatch.setattr(service, "_execute", execute)
    return SimpleNamespace(service=service, source=source, jar=jar, destination=tmp_path / "result",
                           calls=calls, changes=changes)


def transform(case, **kwargs):
    return case.service.transform(case.source, case.destination, game_id=kwargs.pop("game_id", "white"),
                                  seed=kwargs.pop("seed", 512), options=kwargs.pop("options", RandomizerOptions()), **kwargs)


def test_transform_publishes_new_rom_and_provenance_without_touching_source(transformation):
    case = transformation
    source_bytes, source_stat = case.source.read_bytes(), case.source.stat()
    result = transform(case)
    assert case.source.read_bytes() == source_bytes
    assert case.source.stat().st_mtime_ns == source_stat.st_mtime_ns
    assert result.rom_path.read_bytes() != source_bytes
    assert not (case.destination / "source.nds").exists()
    assert result.manifest["seed"] == 512
    assert result.manifest["output_sha256"] == module.file_hash(result.rom_path)
    assert result.manifest["report_sha256"] == module.file_hash(result.report_path)
    assert result.manifest["validation"]["emulator"] == "not_tested"
    assert result.manifest["validation"]["lua"] == "not_tested"
    assert result.manifest["validation"]["shiny_rate"] == "original"
    assert json.loads(result.manifest_path.read_text(encoding="utf-8")) == result.manifest
    assert str(case.source) not in case.calls[-1]
    assert "--seed" not in case.calls[-1]
    assert case.calls[-1][9] == "512"


@pytest.mark.parametrize("seed", [-1, 2**63, True, 1.5, "512"])
def test_invalid_seed_cannot_create_destination(transformation, seed):
    with pytest.raises(ValueError, match="seed"):
        transform(transformation, seed=seed)
    assert not transformation.destination.exists()
    assert not transformation.calls


@pytest.mark.parametrize("categories", [(), ("unknown",), ("wild", "wild"), ["wild"], (True,)])
def test_unknown_or_duplicate_categories_are_refused(categories):
    with pytest.raises(ValueError):
        RandomizerOptions(categories=categories)


def test_balancing_requires_a_supported_category():
    with pytest.raises(ValueError, match="équilibrage"):
        RandomizerOptions(categories=("types",), balanced=True)
    with pytest.raises(ValueError):
        RandomizerOptions(balanced="yes")


def test_parameter_order_is_canonical():
    assert RandomizerOptions(categories=("trainers", "wild")).to_dict()["categories"] == ["wild", "trainers"]


@pytest.mark.parametrize("game_id,code,revision", [("black", "IRAF", 0), ("white", "IRAO", 0),
                                                   ("white", "IRAF", 1), ("unknown", "IRAF", 0)])
def test_distinct_game_region_revision_guard(transformation, game_id, code, revision):
    data = bytearray(transformation.source.read_bytes())
    data[12:16], data[0x1e] = code.encode(), revision
    transformation.source.write_bytes(data)
    with pytest.raises(ValueError, match="françaises"):
        transform(transformation, game_id=game_id)
    assert not transformation.calls


def test_existing_destination_never_replaced(transformation):
    transformation.destination.mkdir()
    personal = transformation.destination / "personal.txt"
    personal.write_text("keep")
    with pytest.raises(ValueError, match="nouveau dossier"):
        transform(transformation)
    assert personal.read_text() == "keep"
    assert not transformation.calls


def test_untrusted_jar_is_not_executed(transformation):
    transformation.jar.write_bytes(b"changed")
    with pytest.raises(ValueError, match="JAR non reconnu"):
        transform(transformation)
    assert not transformation.calls


def test_old_java_fails_before_copy(transformation, monkeypatch):
    monkeypatch.setattr(transformation.service, "_execute", lambda *args, **kwargs:
                        SimpleNamespace(stderr='java version "1.8.0_999"', stdout=""))
    with pytest.raises(ValueError, match="JDK 11"):
        transform(transformation)
    assert not list(transformation.destination.parent.glob(".pce-transform-*"))


@pytest.mark.parametrize("change", ["source", "working", "jar", "identity", "unchanged", "missing"])
def test_invalid_tool_output_is_not_published(transformation, change):
    case = transformation
    def mutate(working, output, result):
        if change in {"source", "working", "jar"}:
            target = {"source": case.source, "working": working, "jar": case.jar}[change]
            with target.open("ab") as handle:
                handle.write(b"changed")
        elif change == "identity":
            data = bytearray(output.read_bytes())
            data[12:16] = b"IREF"
            output.write_bytes(data)
        elif change == "unchanged":
            output.write_bytes(working.read_bytes())
        else:
            output.unlink()
    case.changes["action"] = mutate
    with pytest.raises((ValueError, OSError)):
        transform(case)
    assert not case.destination.exists()
    assert len(list(case.destination.parent.glob(".pce-transform-*/failed.json"))) == 1


@pytest.mark.parametrize("kind", ["version", "game", "category", "unselected", "species", "type", "duplicate", "form", "evolution", "identity_evolution"])
def test_incomplete_or_ambiguous_metadata_is_not_published(transformation, kind):
    data = report()
    if kind == "version": data["tool_version"] = "other"
    elif kind == "game": data["game_code"] = "IREF"
    elif kind == "category": data["categories"]["wild"]["after"] = "a" * 64
    elif kind == "unselected": data["categories"]["types"]["after"] = "b" * 64
    elif kind == "species": data["pokemon"].pop()
    elif kind == "type": data["pokemon"][0]["types"] = ["fairy"]
    elif kind == "duplicate": data["pokemon"].append(data["pokemon"][0])
    elif kind == "form": data["pokemon"][0]["form"] = 32
    elif kind == "evolution": data["pokemon"][0]["evolutions"] = [650]
    elif kind == "identity_evolution": data["pokemon"][0]["identity_evolutions"] = [2]
    transformation.changes["report"] = data
    with pytest.raises(ValueError):
        transform(transformation)
    assert not transformation.destination.exists()


def test_hardlinked_source_is_rejected(transformation):
    alias = transformation.source.with_name("alias.nds")
    os.link(transformation.source, alias)
    with pytest.raises(ValueError, match="lien partagé"):
        transform(transformation)
    assert not transformation.calls


def test_interruption_leaves_source_and_explicit_unpublished_stage(transformation):
    source_bytes = transformation.source.read_bytes()
    def fail(*args):
        raise ValueError("interrupted")
    transformation.changes["action"] = fail
    with pytest.raises(ValueError, match="interrupted"):
        transform(transformation)
    assert not transformation.destination.exists()
    assert transformation.source.read_bytes() == source_bytes
    stage = next(transformation.destination.parent.glob(".pce-transform-*"))
    assert json.loads((stage / "failed.json").read_text())["status"] == "not_published"
    assert (stage / "source.nds").read_bytes() == source_bytes


def test_competing_destination_is_preserved(transformation):
    def competing(*args):
        transformation.destination.mkdir()
        (transformation.destination / "keep.txt").write_text("keep")
    transformation.changes["action"] = competing
    with pytest.raises(ValueError, match="aucun remplacement"):
        transform(transformation)
    assert (transformation.destination / "keep.txt").read_text() == "keep"


def test_custom_shiny_rates_remain_unavailable():
    for game in module.SUPPORTED_CODES:
        support = RomTransformationService.shiny_rate_support(game)
        assert support["original"]
        assert support["custom_denominators"] == []


def test_external_process_timeout_is_bounded_and_hidden(tmp_path, monkeypatch):
    def timeout(command, **kwargs):
        assert kwargs["timeout"] == 23
        assert kwargs["capture_output"] and kwargs["check"] is False
        if os.name == "nt": assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
        raise subprocess.TimeoutExpired(command, 23)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(ValueError, match="délai"):
        RomTransformationService._execute(["java"], cwd=tmp_path, timeout=23)


def test_pce_cli_uses_adapter_seed_and_publishes_validation(transformation, monkeypatch, capsys):
    from tools import randomize_rom
    monkeypatch.setattr(randomize_rom, "RomTransformationService", lambda *args: transformation.service)
    assert randomize_rom.main(["--source", str(transformation.source), "--destination", str(transformation.destination),
                              "--game", "white", "--java", "selected-java", "--jar", "selected-jar", "--seed", "512",
                              "--categories", "wild", "starters", "--balanced"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["validation"]["emulator"] == "not_tested"
    assert Path(data["rom"]).is_file()


def test_pce_cli_error_is_nonzero_and_explicit(transformation, monkeypatch, capsys):
    from tools import randomize_rom
    monkeypatch.setattr(randomize_rom, "RomTransformationService", lambda *args: transformation.service)
    with pytest.raises(SystemExit) as error:
        randomize_rom.main(["--source", str(transformation.source), "--destination", str(transformation.destination),
                           "--game", "white", "--java", "selected-java", "--jar", "selected-jar", "--seed", "-1"])
    assert error.value.code == 1
    assert "Transformation refusée" in capsys.readouterr().err


@pytest.mark.parametrize("value", [False, {}, {"kind": "other", "categories": ["wild"], "balanced": False},
                                   {"kind": "zx", "categories": [], "balanced": False},
                                   {"kind": "zx", "categories": ["wild"], "balanced": False, "jar": "path"}])
def test_snapshot_contract_refuses_ambiguous_transformations(value):
    snapshot = {"active_rules": ["randomizer"], "seed": 12, "settings": {"rom_transformation": value}}
    with pytest.raises(ValueError):
        module.transformation_options(snapshot)


def test_snapshot_uses_unique_challenge_seed_and_rejects_inactive_randomizer():
    snapshot = {"active_rules": [], "seed": 12, "settings": {"rom_transformation": {
        "kind": "zx", "categories": ["wild"], "balanced": False}}}
    with pytest.raises(ValueError):
        module.transformation_options(snapshot)
    snapshot["active_rules"] = ["randomizer"]
    assert module.transformation_options(snapshot).categories == ("wild",)
    snapshot["seed"] = 2**63
    with pytest.raises(ValueError, match="seed"):
        module.transformation_options(snapshot)


def test_tool_config_is_validated_and_separate_from_challenge(transformation, monkeypatch):
    monkeypatch.setattr(module.RomTransformationService, "validate_tool", lambda self: 'java version "17"')
    store = module.RandomizerToolStore(transformation.destination.parent)
    with pytest.raises(ValueError, match="Configurez Java"):
        store.load()
    store.save(transformation.service.java_path, transformation.jar)
    data = store.load()
    assert set(data) == {"schema_version", "java_path", "jar_path"}
    assert data["jar_path"] == str(transformation.jar)
    assert module.RomTransformationService.from_local_config(transformation.destination.parent).jar_path == transformation.jar
    assert not list(transformation.destination.parent.glob(".randomizer-config-*"))


def test_tool_config_rejects_duplicate_or_unknown_keys(tmp_path):
    store = module.RandomizerToolStore(tmp_path)
    store.path.write_text('{"schema_version":1,"schema_version":1,"java_path":"a","jar_path":"b"}')
    with pytest.raises(ValueError): store.load()
    store.path.write_text('{"schema_version":1,"java_path":"a","jar_path":"b","unexpected":true}')
    with pytest.raises(ValueError): store.load()


def test_tool_config_failed_validation_preserves_previous_file(transformation, monkeypatch):
    store = module.RandomizerToolStore(transformation.destination.parent)
    store.path.write_text("previous local settings")
    def refuse(self): raise ValueError("untrusted tool")
    monkeypatch.setattr(module.RomTransformationService, "validate_tool", refuse)
    with pytest.raises(ValueError, match="untrusted"):
        store.save(transformation.service.java_path, transformation.jar)
    assert store.path.read_text() == "previous local settings"
