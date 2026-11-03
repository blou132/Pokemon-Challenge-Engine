"""Optional native tests of the exact shipped mailbox/input headers, without a ROM."""
import os
from pathlib import Path
import subprocess

import pytest


def test_native_command_mailbox_and_input_release(tmp_path):
    compiler_path = os.environ.get("PCE_CXX")
    if not compiler_path:
        pytest.skip("Set PCE_CXX to the local melonDS compiler for native command checks.")
    compiler = Path(compiler_path)
    assert compiler.is_file()
    include = compiler.parent.parent / "include"
    assert (include / "QtCore/QCoreApplication").is_file()
    root = Path(__file__).resolve().parents[1]
    executable = tmp_path / ("native-commands.exe" if os.name == "nt" else "native-commands")
    environment = os.environ | {"PATH": str(compiler.parent) + os.pathsep + os.environ.get("PATH", "")}
    build = subprocess.run([str(compiler), "-std=c++17", "-O0", "-I", str(root / "native/melonds"),
                            "-I", str(include), "-I", str(include / "QtCore"), str(root / "tests/native/melonds_commands.cpp"),
                            "-L", str(compiler.parent.parent / "lib"), "-lQt5Core", "-o", str(executable)],
                           capture_output=True, text=True, env=environment, timeout=120)
    assert build.returncode == 0, build.stderr
    result = subprocess.run([str(executable)], capture_output=True, text=True, env=environment, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "native commands and input pulse ok"
