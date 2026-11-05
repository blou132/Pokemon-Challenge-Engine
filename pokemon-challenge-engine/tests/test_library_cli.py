"""Exercise the same local preparation entrypoint used by the Windows executable."""

import json
import sys

from app.main import main
from test_rom_library_service import rom_bytes


def test_prepare_then_verify_from_another_data_dir_without_reimport(tmp_path, monkeypatch):
    source = tmp_path / "sources"
    source.mkdir()
    original = source / "diamond.nds"
    original.write_bytes(rom_bytes("ADAF", revision=5))
    library = tmp_path / "personal-library"
    report = tmp_path / "import.json"
    monkeypatch.setattr(sys, "argv", ["PCE", "--library-dir", str(library),
        "--prepare-library", str(source), "--library-report", str(report)])
    assert main() == 0
    imported = json.loads(report.read_text(encoding="utf-8"))
    assert imported["imported"] == 1
    assert imported["games"][0]["game_id"] == "diamond"
    assert original.read_bytes() == rom_bytes("ADAF", revision=5)
    original.unlink()  # Synthetic source only: subsequent builds no longer need it.
    checked = tmp_path / "verify.json"
    monkeypatch.setattr(sys, "argv", ["PCE", "--data-dir", str(tmp_path / "new-build-data"),
        "--library-dir", str(library), "--verify-library", "--library-report", str(checked)])
    assert main() == 0
    assert json.loads(checked.read_text(encoding="utf-8"))["games"] == imported["games"]


def test_cli_refuses_corrupted_master_and_does_not_overwrite_report(tmp_path, monkeypatch):
    from app.services.rom_library_service import RomLibraryService
    library = RomLibraryService(tmp_path / "library")
    source = tmp_path / "white.nds"
    source.write_bytes(rom_bytes())
    entry = library.import_source(source).entry
    with library.master_path(entry).open("ab") as handle:
        handle.write(b"synthetic corruption")
    report = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["PCE", "--library-dir", str(library.root),
        "--verify-library", "--library-report", str(report)])
    assert main() == 1
    assert json.loads(report.read_text(encoding="utf-8"))["games"][0]["valid"] is False
    before = report.read_bytes()
    assert main() == 1
    assert report.read_bytes() == before
