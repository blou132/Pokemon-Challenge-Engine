"""Execute a harmless Python child to verify the frozen subprocess boundary."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.services.external_process import child_environment, run_external


def test_child_environment_retains_user_paths_and_clears_frozen_qt(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    ordinary = tmp_path / "user tools"
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("QT_PLUGIN_PATH", str(bundle / "plugins"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("PATH", os.pathsep.join(map(str, [bundle, bundle / "Qt/bin", ordinary])))
    before = dict(os.environ)
    result = child_environment({"PCE_BRIDGE_SESSION": "a" * 32})
    assert result["PATH"] == str(ordinary)
    assert "QT_PLUGIN_PATH" not in result and "QT_QPA_PLATFORM" not in result
    assert result["PCE_BRIDGE_SESSION"] == "a" * 32
    assert dict(os.environ) == before


def test_frozen_child_starts_and_parent_environment_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("QT_PLUGIN_PATH", "pce-only-plugins")
    before = dict(os.environ)
    result = run_external([sys.executable, "-c", "import os;print(os.getenv('QT_PLUGIN_PATH', 'absent'))"],
                          cwd=tmp_path, timeout=15)
    assert result.returncode == 0 and result.stdout.strip() == "absent"
    assert dict(os.environ) == before


def test_child_timeout_is_visible(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        run_external([sys.executable, "-c", "import time;time.sleep(10)"], cwd=tmp_path, timeout=0.1)
