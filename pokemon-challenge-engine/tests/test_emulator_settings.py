"""Synthetic INI files only: no emulator or user configuration is modified."""

from dataclasses import replace
import os
from pathlib import Path

import pytest

from app.services import emulator_capabilities as caps
from app.services import emulator_settings_service as settings
from app.services.emulator_settings_service import (
    DEFAULT_CONTROLS, ControlProfileStore, EmulatorSettingsService, IniDocument,
    control_conflicts, key_label, validate_controls,
)


@pytest.fixture
def service(tmp_path, monkeypatch):
    exe = tmp_path / "DeSmuME.exe"
    exe.write_bytes(b"synthetic build")
    ini = tmp_path / "desmume.ini"
    ini.write_bytes(b"; keep comment\r\n[Unknown]\r\nMystery = keep exactly\r\n[Controls]\r\nA=88\r\n")
    monkeypatch.setattr(settings, "detect_capabilities", lambda path: caps.EmulatorCapabilities(
        known_build=True, supports_controls_config=True, supports_internal_resolution=True))
    monkeypatch.setattr(settings.tempfile, "gettempdir", lambda: str(tmp_path / "other-temp"))
    return EmulatorSettingsService(exe, running_probe=lambda path: False)


@pytest.mark.parametrize("encoding,bom", [("cp1252", b""), ("utf-16-le", b"\xff\xfe"),
                                          ("utf-16-be", b"\xfe\xff"), ("utf-8", b"\xef\xbb\xbf")])
def test_lossless_encodings(encoding, bom):
    source = "; café\r\n[Other]\r\nKeep  = value\r\n[Controls]\r\n A = 88 ; hello\r\n"
    document = IniDocument(bom + source.encode(encoding))
    assert document.to_bytes() == bom + source.encode(encoding)
    document.set_int("Controls", "A", 67)
    result = document.to_bytes()
    assert result == bom + source.replace("88", "67").encode(encoding)


def test_launch_honours_a_saved_profile_named_default(service, tmp_path):
    controls = DEFAULT_CONTROLS | {"A": 67}
    ControlProfileStore(tmp_path / "controls.local.json").save("default", controls)
    service.apply_launch_profile({"controls_profile": "default", "speed": "x1"}, tmp_path)
    assert service.inspect().controls["A"] == 67


@pytest.mark.parametrize("raw", [b"[Controls]\nA=1\na=2", b"[Controls]\na=1\n[controls]", b"a=\x00", b"a" * (1024 * 1024 + 1)],
                         ids=["duplicate-key", "duplicate-section", "nul", "oversize"])
def test_ambiguous_or_invalid_ini_refused(raw):
    with pytest.raises(ValueError):
        IniDocument(raw)


def test_new_keys_stay_in_correct_section():
    document = IniDocument(b"[Other]\nX=keep\n[Controls]\nA=88\n[Last]\nZ=ok")
    document.set_int("Controls", "B", 90)
    document.set_int("3D", "PrescaleHD", 2)
    assert b"A=88\nB=90\n[Last]" in document.to_bytes()
    assert b"Z=ok\n[3D]\nPrescaleHD=2\n" in document.to_bytes()


@pytest.mark.parametrize("header", ["[Controls] ; annotation", "[Controls] # note", "[Controls"])
def test_windows_annotated_section_is_preserved_and_edited_in_place(header):
    document = IniDocument(f"{header}\r\nA=88\r\n".encode())
    assert document.get_int("Controls", "A", 0) == 88
    document.set_int("Controls", "A", 67)
    assert document.to_bytes() == f"{header}\r\nA=67\r\n".encode()


def test_annotated_duplicate_section_cannot_bypass_ambiguity_guard():
    with pytest.raises(ValueError, match="dupliquée"):
        IniDocument(b"[Controls] ; first\nA=88\n[controls]\nA=67\n")


def test_unknown_binary_exposes_no_write_capabilities(tmp_path):
    exe = tmp_path / "DeSmuME.exe"
    exe.write_bytes(b"arbitrary executable")
    actual = caps.detect_capabilities(exe)
    assert not actual.known_build
    assert not actual.supports_controls_config
    assert not actual.supports_lua
    assert not actual.supports_internal_resolution
    assert not actual.supports_speed_control


def test_recognized_build_requires_both_lua_dlls(tmp_path, monkeypatch):
    import hashlib
    exe = tmp_path / "DeSmuME.exe"
    exe.write_bytes(b"synthetic")
    monkeypatch.setattr(caps, "VERIFIED_BUILD_SHA256", hashlib.sha256(b"synthetic").hexdigest())
    assert caps.detect_capabilities(exe).known_build
    assert not caps.detect_capabilities(exe).supports_lua
    for name in ("lua51.dll", "lua5.1.dll"):
        (tmp_path / name).write_bytes(b"test")
    assert caps.detect_capabilities(exe).supports_lua
    assert caps.detect_capabilities(exe).verification != "real_validated"


def test_import_uses_documented_defaults_and_preserves_gamepad_codes(service):
    path = Path(service.executable).with_name("desmume.ini")
    path.write_bytes(b"[Controls]\nA=32780\n")
    snapshot = service.inspect()
    assert snapshot.controls["A"] == 32780
    assert snapshot.controls["Select"] == 161
    assert "Manette" in key_label(32780)
    with pytest.raises(ValueError, match="manette"):
        service.apply(controls=snapshot.controls)


def test_export_backs_up_each_version_and_preserves_unknown_data(service):
    path = Path(service.executable).with_name("desmume.ini")
    original = path.read_bytes()
    first = service.apply(graphics={"internal_resolution": 2})
    assert first.backup_path.read_bytes() == original
    assert b"Mystery = keep exactly\r\n" in path.read_bytes()
    second_original = path.read_bytes()
    second = service.apply(controls=DEFAULT_CONTROLS | {"A": 67})
    assert second.backup_path != first.backup_path
    assert first.backup_path.read_bytes() == original
    assert second.backup_path.read_bytes() == second_original
    assert service.import_controls()["A"] == 67


@pytest.mark.parametrize("running", [True, None])
def test_running_or_unknown_process_state_never_writes(service, running):
    path = Path(service.executable).with_name("desmume.ini")
    before = path.read_bytes()
    service.running_probe = lambda: running
    with pytest.raises(ValueError, match="Fermez"):
        service.apply(speed="MAX")
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.pce-backup*"))


@pytest.mark.parametrize("speed,index,limiter", [("x1", 5, 1), ("MAX", 5, 0)])
def test_speed_changes_only_documented_limiter(service, speed, index, limiter):
    change = service.apply(speed=speed)
    document = IniDocument(Path(service.executable).with_name("desmume.ini").read_bytes())
    assert document.get_int("FrameLimit", "FrameLimit", 1) == limiter
    assert document.get_int("Video", "FPS Scaler Index", 5) == index
    assert change.requested_speed == speed
    assert change.confirmed_speed is None
    assert ("video", "frameskip") not in document.entries


@pytest.mark.parametrize("speed", ["x2", "x4", "x8", "bad"])
def test_unverified_startup_speeds_refused_without_writing(service, speed):
    path = Path(service.executable).with_name("desmume.ini")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        service.apply(speed=speed)
    assert path.read_bytes() == before


@pytest.mark.parametrize("graphics", [{"shader": 1}, {"internal_resolution": 0},
                                      {"internal_resolution": 17}, {"vsync": True}, {"rotation": 45}])
def test_invalid_graphics_never_written(service, graphics):
    with pytest.raises(ValueError):
        service.apply(graphics=graphics)


def test_control_conflicts_include_default_savestates_and_custom_hotkeys(service):
    path = Path(service.executable).with_name("desmume.ini")
    path.write_bytes(path.read_bytes() + b"[Hotkeys]\nSomeCustomAction=67\n")
    for key in (67, 112, 73, 80, 78):
        with pytest.raises(ValueError, match="Conflit"):
            service.apply(controls=DEFAULT_CONTROLS | {"A": key})


def test_modified_hotkeys_preserved_when_exporting_controls(service):
    path = Path(service.executable).with_name("desmume.ini")
    path.write_bytes(path.read_bytes() + b"[Hotkeys]\nIncreaseSpeed=67\nIncreaseSpeed MOD=2\n")
    assert "IncreaseSpeed" not in service.inspect().hotkeys
    service.apply(controls=DEFAULT_CONTROLS)
    assert b"IncreaseSpeed MOD=2" in path.read_bytes()
    assert b"IncreaseSpeed=67" in path.read_bytes()


def test_replace_failure_leaves_original_and_valid_backup(service, monkeypatch):
    path = Path(service.executable).with_name("desmume.ini")
    original = path.read_bytes()
    def denied(self, other):
        raise PermissionError("locked")
    monkeypatch.setattr(Path, "replace", denied)
    with pytest.raises(ValueError, match="verrouillé"):
        service.apply(graphics={"vsync": 1})
    assert path.read_bytes() == original
    assert path.with_name("desmume.ini.pce-backup").read_bytes() == original
    assert not list(path.parent.glob(".pce_ini_*"))


def test_backup_failure_never_replaces_original(service, monkeypatch):
    path = Path(service.executable).with_name("desmume.ini")
    original = path.read_bytes()
    def denied(*args):
        raise PermissionError("denied")
    monkeypatch.setattr(service, "_backup", denied)
    with pytest.raises(ValueError):
        service.apply(graphics={"vsync": 1})
    assert path.read_bytes() == original


def test_profile_roundtrip_and_corrupt_profile_is_retained(tmp_path):
    path = tmp_path / "controls.local.json"
    store = ControlProfileStore(path)
    store.save("AZERTY", DEFAULT_CONTROLS)
    assert store.load()["AZERTY"] == DEFAULT_CONTROLS
    path.write_text("invalid", encoding="utf-8")
    with pytest.raises(ValueError):
        store.save("Other", DEFAULT_CONTROLS)
    assert path.read_text() == "invalid"


@pytest.mark.parametrize("raw", ['{"schema_version": 1, "profiles": {}, "profiles": {}}',
                                '{"schema_version": true, "profiles": {}}',
                                '{"schema_version": 1, "profiles": {}, "unknown": 1}'])
def test_ambiguous_profile_file_is_never_overwritten(tmp_path, raw):
    path = tmp_path / "controls.local.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="conservé"):
        ControlProfileStore(path).save("Keyboard", DEFAULT_CONTROLS)
    assert path.read_text(encoding="utf-8") == raw


@pytest.mark.parametrize("controls", [{}, DEFAULT_CONTROLS | {"A": True}, DEFAULT_CONTROLS | {"A": -1}])
def test_invalid_control_profiles(controls):
    with pytest.raises(ValueError):
        validate_controls(controls)


def test_launch_default_controls_and_named_profile(service, tmp_path):
    service.apply_launch_profile({"controls_profile": "default", "graphics_preset": "hd", "speed": "x1"}, tmp_path)
    assert service.inspect().graphics["internal_resolution"] == 2
    ControlProfileStore(tmp_path / "controls.local.json").save("Mine", DEFAULT_CONTROLS | {"A": 67})
    service.apply_launch_profile({"controls_profile": "Mine"}, tmp_path)
    assert service.inspect().controls["A"] == 67


def test_mismatched_ini_and_missing_profile_refused(service, tmp_path):
    for options in ({"ini_path": str(tmp_path / "other.ini")}, {"controls_profile": "missing"}):
        with pytest.raises(ValueError):
            service.apply_launch_profile(options, tmp_path)


def test_unknown_build_refuses_backup_and_edits(tmp_path):
    service = EmulatorSettingsService(tmp_path / "missing.exe", running_probe=lambda: False)
    assert service.inspect().controls == {}
    with pytest.raises(ValueError):
        service.apply(controls=DEFAULT_CONTROLS)
    with pytest.raises(ValueError):
        service.backup_config()
