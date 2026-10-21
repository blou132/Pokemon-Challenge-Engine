"""Optional native config regression with upstream toml11; no emulator started.

Set PCE_MELONDS_SOURCE to the pinned melonDS checkout and PCE_CXX to its g++.
Both are explicit local inputs; this test downloads or installs nothing.
"""

import os
from pathlib import Path
import subprocess
import tomllib

import pytest

from app.services.melonds_runtime import UPSTREAM_COMMIT, initial_config


@pytest.fixture(scope="module")
def native_roundtrip(tmp_path_factory):
    source_path, compiler_path = os.environ.get("PCE_MELONDS_SOURCE"), os.environ.get("PCE_CXX")
    if not source_path or not compiler_path:
        pytest.skip("Native config check requires PCE_MELONDS_SOURCE and PCE_CXX.")
    source, compiler = Path(source_path), Path(compiler_path)
    assert compiler.is_file(), "Configured C++ compiler does not exist."
    header_root = source / "src/frontend/qt_sdl"
    assert (header_root / "toml/toml.hpp").is_file()
    revision = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=10, check=True).stdout.strip()
    assert revision == UPSTREAM_COMMIT, "Use the melonDS revision pinned by PCE."
    executable = tmp_path_factory.mktemp("native-config") / ("roundtrip.exe" if os.name == "nt" else "roundtrip")
    environment = os.environ | {"PATH": str(compiler.parent) + os.pathsep + os.environ.get("PATH", "")}
    cpp = Path(__file__).parent / "native/melonds_config_roundtrip.cpp"
    built = subprocess.run([str(compiler), "-std=c++17", "-O0", "-I", str(header_root), str(cpp), "-o", str(executable)],
                           capture_output=True, text=True, env=environment, timeout=120)
    assert built.returncode == 0, built.stderr

    def run(config):
        return subprocess.run([str(executable)], input=config, capture_output=True, text=True,
                              encoding="utf-8", env=environment, timeout=10)

    return run


def test_implicit_parent_reproduces_native_serializer_error(native_roundtrip):
    config = "[DSi.SD]\nEnable = false\n"
    assert tomllib.loads(config) == {"DSi": {"SD": {"Enable": False}}}
    result = native_roundtrip(config)
    assert result.returncode == 3
    assert "an implicit table cannot have non-table value" in result.stderr


def test_generated_config_accepts_native_scalar_defaults_and_roundtrips(native_roundtrip, tmp_path):
    config = initial_config(tmp_path / "synthetic adventure")
    result = native_roundtrip(config)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "roundtrip ok"
    # The former generated config is valid TOML but fails inside Config::Save.
    previous = config.replace("[DSi]\n", "")
    assert previous != config
    assert tomllib.loads(previous) == tomllib.loads(config)
    rejected = native_roundtrip(previous)
    assert rejected.returncode == 3
    assert "an implicit table cannot have non-table value" in rejected.stderr


def test_explicit_parent_roundtrips_with_the_same_native_defaults(native_roundtrip):
    result = native_roundtrip("[DSi]\n[DSi.SD]\nEnable = false\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "roundtrip ok"
