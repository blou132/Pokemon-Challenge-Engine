"""A third-party manifest cannot smuggle files outside its reviewed component."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def builder():
    path = Path(__file__).resolve().parents[1] / "packaging/windows/build_windows.py"
    spec = importlib.util.spec_from_file_location("pce_windows_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def component(tmp_path):
    root = tmp_path / "component"
    root.mkdir()
    (root / "COPYING").write_text("Synthetic license fixture")
    (root / "tool.exe").write_bytes(b"Synthetic component fixture, never executed")
    data = {"name": "fixture", "version": "1", "source_url": "https://example.org/source",
            "license_file": "COPYING", "files": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.iterdir()}}
    (root / "component-manifest.json").write_text(json.dumps(data))
    return root, data


def save(root, data):
    (root / "component-manifest.json").write_text(json.dumps(data))


def test_exact_component_file_inventory_is_selected(builder, component):
    root, data = component
    (root / "unlisted.txt").write_text("not part of the component")
    manifest, files = builder.component_files(root)
    assert {path.name for path in files} == {"COPYING", "tool.exe"}
    assert manifest == data


def test_component_tamper_is_rejected(builder, component):
    root, data = component
    (root / "tool.exe").write_bytes(b"changed")
    with pytest.raises(ValueError, match="failed verification"):
        builder.component_files(root)


@pytest.mark.parametrize("name", ["../outside.txt", "C:/outside.txt", "sub\\tool.exe", "tool.exe:stream"])
def test_component_path_escape_is_rejected(builder, component, name):
    root, data = component
    data["files"][name] = "0" * 64
    save(root, data)
    with pytest.raises(ValueError, match="Unsafe component path"):
        builder.component_files(root)


@pytest.mark.parametrize("name", ["game.nds", "GAME.NDS", "save.dsv", "firmware.bin", "state.dst",
                                 "state.ml1", "game.sav.bak", "backup.NDS.old", "state.ds0",
                                 "config.json", "run.json", "melonDS.toml"])
def test_component_rom_save_and_firmware_are_rejected(builder, component, name):
    root, data = component
    (root / name).write_bytes(b"synthetic restricted file")
    data["files"][name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    save(root, data)
    with pytest.raises(ValueError, match="cannot be distributed"):
        builder.component_files(root)


def test_component_without_license_is_rejected(builder, component):
    root, data = component
    del data["files"]["COPYING"]
    save(root, data)
    with pytest.raises(ValueError, match="license"):
        builder.component_files(root)
