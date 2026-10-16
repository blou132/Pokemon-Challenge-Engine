"""Synthetic files and subprocess responses; no installed Java or ROM is launched."""

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import randomizer_tool_discovery_service as discovery
from app.services import rom_transformation_service as transformation


@pytest.fixture
def tools_case(tmp_path, monkeypatch):
    base = tmp_path / "storage"
    base.mkdir()
    home = tmp_path / "jdk"
    java = make_java(home / "bin")
    jar = base / "PokeRandoZX.jar"
    jar.write_bytes(b"synthetic official jar")
    monkeypatch.setattr(transformation, "ZX_JAR_SHA256", hashlib.sha256(jar.read_bytes()).hexdigest())
    calls = []

    def execute(command, *, cwd, timeout):
        calls.append((command, cwd, timeout))
        if command[1:] == ["-version"]:
            return SimpleNamespace(stderr='openjdk version "17.0.1"', stdout="", returncode=0)
        assert command[1:] == ["--describe-module", "jdk.compiler"]
        return SimpleNamespace(stderr="", stdout="jdk.compiler@17.0.1\nrequires java.compiler transitive", returncode=0)

    monkeypatch.setattr(transformation.RomTransformationService, "_execute", staticmethod(execute))
    return SimpleNamespace(base=base, home=home, java=java, jar=jar, calls=calls, execute=execute)


def make_java(folder):
    folder.mkdir(parents=True, exist_ok=True)
    java = folder / ("java.exe" if os.name == "nt" else "java")
    java.write_bytes(b"synthetic java")
    return java


def service(case, environment=None):
    return discovery.RandomizerToolDiscoveryService(case.base, environment=environment or {})


def test_java_home_and_local_verified_jar_are_discovered_without_writing(tools_case):
    case = tools_case
    original = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (case.java, case.jar)}
    result = service(case, {"JAVA_HOME": str(case.home)}).discover()
    assert result.verified
    assert result.java_path == str(case.java)
    assert result.jar_path == str(case.jar)
    assert "Enregistrez" in result.message and "ROM encore à vérifier" in result.message
    assert [call[0] for call in case.calls] == [[str(case.java), "-version"],
                                               [str(case.java), "--describe-module", "jdk.compiler"]]
    assert 0 < case.calls[1][2] <= case.calls[0][2] <= discovery.DISCOVERY_SECONDS
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in original} == original
    assert not (case.base / "randomizer.local.json").exists()


def test_unsupported_java_home_falls_back_to_path(tools_case, tmp_path, monkeypatch):
    case = tools_case
    other = make_java(tmp_path / "other")

    def execute(command, **kwargs):
        result = case.execute(command, **kwargs)
        if command[0] == str(case.java):
            result.stderr = 'java version "1.8.0_999"'
        return result

    monkeypatch.setattr(transformation.RomTransformationService, "_execute", staticmethod(execute))
    result = service(case, {"JAVA_HOME": str(case.home), "PATH": str(other.parent)}).discover()
    assert result.verified and result.java_path == str(other)
    assert [call[0] for call in case.calls] == [[str(case.java), "-version"],
                                               [str(other), "-version"],
                                               [str(other), "--describe-module", "jdk.compiler"]]


def test_runtime_without_compiler_falls_back_to_full_jdk(tools_case, tmp_path, monkeypatch):
    case = tools_case
    other = make_java(tmp_path / "full-jdk")

    def execute(command, **kwargs):
        result = case.execute(command, **kwargs)
        if command == [str(case.java), "--describe-module", "jdk.compiler"]:
            raise ValueError("module jdk.compiler not found")
        return result

    monkeypatch.setattr(transformation.RomTransformationService, "_execute", staticmethod(execute))
    result = service(case, {"JAVA_HOME": str(case.home), "PATH": str(other.parent)}).discover()
    assert result.verified and result.java_path == str(other)
    assert [call[0] for call in case.calls] == [
        [str(case.java), "-version"], [str(case.java), "--describe-module", "jdk.compiler"],
        [str(other), "-version"], [str(other), "--describe-module", "jdk.compiler"]]


def test_explicit_runtime_without_compiler_is_preserved_without_fallback(tools_case, tmp_path, monkeypatch):
    case = tools_case
    other = make_java(tmp_path / "full-jdk")

    def execute(command, **kwargs):
        result = case.execute(command, **kwargs)
        if command[1:] == ["--describe-module", "jdk.compiler"]:
            raise ValueError("module jdk.compiler not found")
        return result

    monkeypatch.setattr(transformation.RomTransformationService, "_execute", staticmethod(execute))
    result = service(case, {"PATH": str(other.parent)}).discover(java_path=str(case.java))
    assert not result.verified and result.java_path == str(case.java)
    assert "Choix conservé" in result.message
    assert [call[0] for call in case.calls] == [[str(case.java), "-version"],
                                               [str(case.java), "--describe-module", "jdk.compiler"]]


def test_second_exact_jar_location_is_checked_if_first_is_untrusted(tools_case):
    case = tools_case
    second = case.base / "tools" / "randomizer" / "PokeRandoZX.jar"
    second.parent.mkdir(parents=True)
    second.write_bytes(case.jar.read_bytes())
    case.jar.write_bytes(b"untrusted")
    result = service(case, {"JAVA_HOME": str(case.home)}).discover()
    assert result.verified and result.jar_path == str(second)


@pytest.mark.parametrize("missing", [True, False])
def test_invalid_explicit_jar_is_preserved_without_fallback_or_execution(tools_case, tmp_path, missing):
    chosen = tmp_path / "chosen.jar"
    if not missing:
        chosen.write_bytes(b"wrong jar")
    result = service(tools_case, {"JAVA_HOME": str(tools_case.home)}).discover(jar_path=str(chosen))
    assert not result.verified and result.jar_path == str(chosen)
    assert "Choix conservé" in result.message
    assert not tools_case.calls


def test_invalid_explicit_java_is_preserved_despite_valid_java_home(tools_case, tmp_path):
    missing = str(tmp_path / "chosen-java.exe")
    result = service(tools_case, {"JAVA_HOME": str(tools_case.home)}).discover(java_path=missing)
    assert not result.verified and result.java_path == missing
    assert result.jar_path == str(tools_case.jar)
    assert "Choix conservé" in result.message
    assert not tools_case.calls


def test_old_explicit_java_does_not_fall_back(tools_case, tmp_path, monkeypatch):
    other = make_java(tmp_path / "explicit")

    def execute(command, **kwargs):
        result = tools_case.execute(command, **kwargs)
        result.stderr = 'java version "1.8.0_999"'
        return result

    monkeypatch.setattr(transformation.RomTransformationService, "_execute", staticmethod(execute))
    result = service(tools_case, {"JAVA_HOME": str(tools_case.home)}).discover(java_path=str(other))
    assert not result.verified and result.java_path == str(other)
    assert len(tools_case.calls) == 1 and tools_case.calls[0][0][0] == str(other)


def test_explicit_paths_can_be_outside_search_roots_and_remain_exact(tools_case, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    java = str(tools_case.java.relative_to(tmp_path))
    jar = str(tools_case.jar.relative_to(tmp_path))
    result = service(tools_case).discover(java, jar)
    assert result.verified and result.java_path == java and result.jar_path == jar


def test_missing_jar_does_not_trigger_java_or_search_java_directory(tools_case):
    case = tools_case
    case.jar.rename(case.java.parent / "PokeRandoZX.jar")
    result = service(case, {"JAVA_HOME": str(case.home)}).discover()
    assert not result.verified and not result.jar_path and not result.java_path
    assert "Sélectionnez PokeRandoZX.jar" in result.message
    assert not case.calls


def test_missing_java_keeps_verified_jar_without_claiming_pair_compatible(tools_case):
    result = service(tools_case).discover()
    assert result.jar_path == str(tools_case.jar) and result.java_path == ""
    assert not result.verified and "aucun Java compatible vérifié" in result.message


@pytest.mark.parametrize("relative", ["", ".", "relative", "//server/share", r"\\server\share"])
def test_empty_relative_or_network_environment_never_searches_cwd(tools_case, monkeypatch, relative):
    monkeypatch.chdir(tools_case.java.parent)
    result = service(tools_case, {"JAVA_HOME": relative, "PATH": relative}).discover()
    assert not result.verified and not result.java_path and not tools_case.calls


def test_jar_size_is_bounded_before_hashing(tools_case, monkeypatch):
    monkeypatch.setattr(discovery, "MAX_JAR_BYTES", 1)
    monkeypatch.setattr(transformation, "file_hash", lambda path: pytest.fail("oversized JAR hashed"))
    result = service(tools_case, {"JAVA_HOME": str(tools_case.home)}).discover()
    assert not result.verified and not tools_case.calls


def test_shared_hardlink_jar_is_rejected(tools_case):
    alias = tools_case.base / "alias.jar"
    os.link(tools_case.jar, alias)
    result = service(tools_case, {"JAVA_HOME": str(tools_case.home)}).discover()
    assert not result.verified and not tools_case.calls


@pytest.mark.parametrize("link_check", ["is_symlink", "is_junction"])
def test_link_or_junction_in_jar_parent_prevents_hash_and_execution(tools_case, monkeypatch, link_check):
    original = getattr(Path, link_check)
    monkeypatch.setattr(Path, link_check, lambda path: path == tools_case.base or original(path))
    monkeypatch.setattr(transformation, "file_hash", lambda path: pytest.fail("linked JAR hashed"))
    result = service(tools_case, {"JAVA_HOME": str(tools_case.home)}).discover()
    assert not result.verified and not tools_case.calls


def test_path_search_stops_after_entry_budget(tools_case, tmp_path):
    entries = [str(tmp_path / f"absent-{i}") for i in range(discovery.MAX_PATH_ENTRIES)]
    entries.append(str(tools_case.java.parent))
    result = service(tools_case, {"PATH": os.pathsep.join(entries)}).discover()
    assert not result.verified and not tools_case.calls


def test_deduplication_and_probe_budget_are_global(tools_case, tmp_path, monkeypatch):
    java_paths = [tools_case.java] + [make_java(tmp_path / f"jdk-{i}") for i in range(4)]

    def execute(command, **kwargs):
        tools_case.execute(command, **kwargs)
        raise ValueError("bad Java")

    monkeypatch.setattr(transformation.RomTransformationService, "_execute", staticmethod(execute))
    result = service(tools_case, {"JAVA_HOME": str(tools_case.home),
        "PATH": os.pathsep.join(str(path.parent) for path in [java_paths[0], *java_paths])}).discover()
    assert not result.verified
    assert [call[0][0] for call in tools_case.calls] == [str(path) for path in java_paths[:3]]


def test_probes_share_one_time_budget(tools_case, tmp_path, monkeypatch):
    clock = [100.0]
    other = make_java(tmp_path / "other")
    monkeypatch.setattr(discovery.time, "monotonic", lambda: clock[0])

    def execute(command, **kwargs):
        tools_case.execute(command, **kwargs)
        clock[0] += 21
        raise ValueError("timeout")

    monkeypatch.setattr(transformation.RomTransformationService, "_execute", staticmethod(execute))
    result = service(tools_case, {"JAVA_HOME": str(tools_case.home), "PATH": str(other.parent)}).discover()
    assert not result.verified and len(tools_case.calls) == 1
    assert tools_case.calls[0][2] == discovery.DISCOVERY_SECONDS


def test_subprocess_receives_only_remaining_budget(tools_case, tmp_path, monkeypatch):
    clock = [100.0]
    other = make_java(tmp_path / "other")
    monkeypatch.setattr(discovery.time, "monotonic", lambda: clock[0])

    def execute(command, **kwargs):
        result = tools_case.execute(command, **kwargs)
        if len(tools_case.calls) == 1:
            clock[0] += 7
            raise ValueError("bad Java")
        return result

    monkeypatch.setattr(transformation.RomTransformationService, "_execute", staticmethod(execute))
    result = service(tools_case, {"JAVA_HOME": str(tools_case.home), "PATH": str(other.parent)}).discover()
    assert result.verified
    assert [call[2] for call in tools_case.calls] == [20, 13, 13]


def test_slow_jar_hash_cannot_leave_a_fresh_twenty_second_java_budget(tools_case, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(discovery.time, "monotonic", lambda: clock[0])
    original = transformation.file_hash

    def slow_hash(path):
        clock[0] += 21
        return original(path)

    monkeypatch.setattr(transformation, "file_hash", slow_hash)
    result = service(tools_case, {"JAVA_HOME": str(tools_case.home)}).discover()
    assert not result.verified and not tools_case.calls


def test_validation_timeout_includes_hashing_before_launch(tools_case, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(transformation.time, "monotonic", lambda: clock[0])
    original = transformation.file_hash

    def slow_hash(path):
        clock[0] += 6
        return original(path)

    monkeypatch.setattr(transformation, "file_hash", slow_hash)
    with pytest.raises(ValueError, match="délai de vérification"):
        transformation.RomTransformationService(tools_case.java, tools_case.jar).validate_tool(timeout=5)
    assert not tools_case.calls


def test_compiler_probe_receives_only_budget_left_after_version(tools_case, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(transformation.time, "monotonic", lambda: clock[0])

    def execute(command, **kwargs):
        result = tools_case.execute(command, **kwargs)
        if command[1:] == ["-version"]:
            clock[0] += 7
        return result

    monkeypatch.setattr(transformation.RomTransformationService, "_execute", staticmethod(execute))
    result = service(tools_case, {"JAVA_HOME": str(tools_case.home)}).discover()
    assert result.verified
    assert [call[0][1:] for call in tools_case.calls] == [["-version"], ["--describe-module", "jdk.compiler"]]
    assert [call[2] for call in tools_case.calls] == [20, 13]


def test_elapsed_version_probe_cannot_start_compiler_probe(tools_case, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(transformation.time, "monotonic", lambda: clock[0])

    def execute(command, **kwargs):
        result = tools_case.execute(command, **kwargs)
        clock[0] += 21
        return result

    monkeypatch.setattr(transformation.RomTransformationService, "_execute", staticmethod(execute))
    with pytest.raises(ValueError, match="délai de vérification"):
        transformation.RomTransformationService(tools_case.java, tools_case.jar).validate_tool()
    assert [call[0][1:] for call in tools_case.calls] == [["-version"]]


def test_compiler_timeout_cannot_start_another_java_candidate(tools_case, tmp_path, monkeypatch):
    clock = [100.0]
    other = make_java(tmp_path / "other")
    monkeypatch.setattr(transformation.time, "monotonic", lambda: clock[0])

    def execute(command, **kwargs):
        result = tools_case.execute(command, **kwargs)
        if command[1:] == ["-version"]:
            clock[0] += 8
        else:
            clock[0] += kwargs["timeout"]
            raise ValueError("compiler check timed out")
        return result

    monkeypatch.setattr(transformation.RomTransformationService, "_execute", staticmethod(execute))
    result = service(tools_case, {"JAVA_HOME": str(tools_case.home), "PATH": str(other.parent)}).discover()
    assert not result.verified
    assert [call[0][0] for call in tools_case.calls] == [str(tools_case.java)] * 2
    assert [call[2] for call in tools_case.calls] == [20, 12]
