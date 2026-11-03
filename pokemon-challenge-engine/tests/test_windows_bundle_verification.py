"""Portable artifacts must be complete, unmodified and safe to extract."""

import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest


@pytest.fixture
def verifier():
    path = Path(__file__).resolve().parents[1] / "packaging/windows/verify_windows_bundle.py"
    spec = importlib.util.spec_from_file_location("pce_bundle_verifier_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def artifact(tmp_path, *, changed=False, extra=None, missing=False):
    files = {"Pokemon-Challenge-Engine.exe": b"synthetic executable, never run", "LISEZ-MOI.txt": b"instructions"}
    manifest = {"name": "Pokemon-Challenge-Engine", "version": "0.5.0", "components": [],
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    if changed:
        files["LISEZ-MOI.txt"] = b"tampered"
    if missing:
        del files["LISEZ-MOI.txt"]
    if extra:
        files[extra] = b"unexpected"
    files["distribution-manifest.json"] = json.dumps(manifest).encode()
    archive = tmp_path / "distribution.zip"
    with zipfile.ZipFile(archive, "x") as zipped:
        for name, data in files.items():
            zipped.writestr("Pokemon-Challenge-Engine/" + name, data)
    return archive


def test_verified_zip_extracts_only_to_new_directory(verifier, tmp_path):
    archive = artifact(tmp_path)
    target = tmp_path / "extracted"
    result = verifier.verify(archive, target)
    assert result["ok"] and result["files_verified"] == 2
    assert Path(result["extracted_exe"]).read_bytes() == b"synthetic executable, never run"
    with pytest.raises(FileExistsError):
        verifier.verify(archive, target)


@pytest.mark.parametrize("options,reason", [
    ({"changed": True}, "checksum mismatch"),
    ({"missing": True}, "inventory"),
    ({"extra": "unlisted.txt"}, "inventory"),
    ({"extra": "game.sav.bak"}, "Personal game data"),
    ({"extra": "../outside.txt"}, "Unsafe archive path"),
    ({"extra": "CON.txt"}, "Unsafe archive path"),
    ({"extra": "lisez-moi.TXT"}, "Duplicate archive path"),
])
def test_invalid_zip_is_rejected_before_extraction(verifier, tmp_path, options, reason):
    archive = artifact(tmp_path, **options)
    target = tmp_path / "extracted"
    with pytest.raises(ValueError, match=reason):
        verifier.verify(archive, target)
    assert not target.exists()
