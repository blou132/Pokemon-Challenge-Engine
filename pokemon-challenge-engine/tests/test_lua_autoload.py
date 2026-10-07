"""Synthetic files/process probes only; no emulator, real ROM or user INI is used."""

import hashlib
import json
from pathlib import Path

import pytest

from app.services import emulator_capabilities as caps
from app.services import emulator_settings_service as settings
from app.services.lua_autoload_service import LuaAutoLoadService
from app.services.lua_runtime_installer import LuaDiagnostic, LuaRuntimeInstaller
from app.services.emulator_service import lua_literal
from app.services.emulator_settings_service import IniDocument


@pytest.fixture
def environment(tmp_path, monkeypatch):
    exe = tmp_path / "emulator" / "DeSmuME.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"synthetic autoload executable")
    ini = exe.with_name("desmume.ini")
    ini.write_bytes(b"; comment\r\n[Other]\r\nMystery = keep exactly\r\n"
                    b"[Scripting]\r\nAutoLoad = 0 ; keep integer comment\r\n"
                    b"[PathSettings]\r\n; personal scripts\r\nLua = .\\Personal Lua\r\n")
    personal = exe.parent / "Personal Lua"
    personal.mkdir()
    (personal / "Blanc.lua").write_bytes(b"-- personal script, never edited\n")
    base = tmp_path / "pce"
    session = base / "runtime" / "bridge" / ("a" * 32)
    session.mkdir(parents=True)
    script = session / "connect.lua"
    script.write_bytes(b"-- synthetic prepared connection\n")
    (session / "config.lua").write_bytes(b"return {}\n")
    rom = tmp_path / "Blanc.version 1.fr.NDS"
    rom.write_bytes(b"synthetic filename fixture, not a ROM")
    monkeypatch.setattr(caps, "VERIFIED_BUILD_SHA256", hashlib.sha256(exe.read_bytes()).hexdigest())
    monkeypatch.setattr(settings.tempfile, "gettempdir", lambda: str(tmp_path / "other-temp"))
    monkeypatch.setattr(LuaRuntimeInstaller, "diagnose", lambda self, path:
                        LuaDiagnostic("verified", "x64", (), True))
    service = LuaAutoLoadService(base, running_probe=lambda path: False)
    return service, exe, ini, rom, script, personal


def enable(environment):
    service, exe, ini, rom, script, personal = environment
    service.record_consent(exe, True)
    return service.prepare(exe, rom, script)


def test_consent_is_explicit_persisted_and_bound_to_binary(environment):
    service, exe, ini, rom, script, _ = environment
    before = ini.read_bytes()
    assert service.consent_status(exe) is None
    with pytest.raises(ValueError, match="accord"):
        service.prepare(exe, rom, script)
    assert not service.loader_root.exists()
    service.record_consent(exe, False)
    assert service.consent_status(exe) is False
    with pytest.raises(ValueError, match="accord"):
        service.prepare(exe, rom, script)
    service.record_consent(exe, True)
    assert LuaAutoLoadService(service.base_dir).consent_status(exe) is True
    exe.write_bytes(b"another build at the same path")
    assert service.consent_status(exe) is None
    assert ini.read_bytes() == before


@pytest.mark.parametrize("bad", [1, 0, "yes", None])
def test_non_boolean_consent_is_not_persisted(environment, bad):
    service, exe, *_ = environment
    with pytest.raises(ValueError, match="Consentement"):
        service.record_consent(exe, bad)
    assert not service.state_path.exists()


def test_loader_uses_actual_prepared_rom_stem_and_exact_immutable_session(environment):
    service, exe, ini, rom, script, personal = environment
    before = ini.read_bytes()
    result = enable(environment)
    assert result.enabled
    assert result.loader_path == service.loader_root / script.parent.name / (rom.stem + ".lua")
    assert "dofile(" + lua_literal(script) + ")" in result.loader_path.read_text(encoding="ascii")
    assert result.backup_path.read_bytes() == before
    assert "heartbeat" in result.message
    assert "connecté" not in result.message
    document = IniDocument(ini.read_bytes())
    assert document.get_int("Scripting", "AutoLoad", 0) == 1
    assert document.get_text("PathSettings", "Lua") == str(result.loader_path.parent)
    assert b"Mystery = keep exactly\r\n" in ini.read_bytes()
    assert b"; personal scripts\r\n" in ini.read_bytes()
    assert b"AutoLoad = 1 ; keep integer comment\r\n" in ini.read_bytes()
    assert (personal / "Blanc.lua").read_bytes() == b"-- personal script, never edited\n"
    assert rom.read_bytes() == b"synthetic filename fixture, not a ROM"


def test_restore_preserves_unrelated_new_settings_and_exact_original_key_lines(environment):
    service, exe, ini, *_ = environment
    before = ini.read_bytes()
    first = enable(environment)
    ini.write_bytes(ini.read_bytes() + b"[User Added]\r\nKeep=after launch\r\n")
    result = service.restore(exe)
    assert not result.enabled
    assert result.backup_path != first.backup_path
    assert ini.read_bytes() == before + b"[User Added]\r\nKeep=after launch\r\n"
    assert first.loader_path.is_file()
    assert service.consent_status(exe) is True
    assert service.restore(exe).backup_path is None


def test_refusal_does_not_implicitly_touch_ini_and_manual_restore_is_available(environment):
    service, exe, ini, *_ = environment
    before = ini.read_bytes()
    enable(environment)
    managed = ini.read_bytes()
    service.record_consent(exe, False)
    assert ini.read_bytes() == managed
    service.restore(exe)
    assert ini.read_bytes() == before
    assert service.consent_status(exe) is False


@pytest.mark.parametrize("running", [True, None])
def test_active_or_unknown_emulator_never_changes_ini(environment, running):
    service, exe, ini, rom, script, _ = environment
    service.record_consent(exe, True)
    before = ini.read_bytes()
    service.running_probe = lambda path: running
    with pytest.raises(ValueError, match="Fermez"):
        service.prepare(exe, rom, script)
    assert ini.read_bytes() == before
    assert not service.loader_root.exists()
    assert not list(exe.parent.glob("*.pce-backup*"))


def test_running_probe_failure_falls_back_without_mutation(environment):
    service, exe, ini, rom, script, _ = environment
    before = ini.read_bytes()
    service.record_consent(exe, True)
    def fail(path):
        raise RuntimeError("probe unavailable")
    service.running_probe = fail
    with pytest.raises(ValueError, match="vérifier"):
        service.prepare(exe, rom, script)
    assert ini.read_bytes() == before


def test_reconnection_refreshes_loader_without_editing_running_emulator(environment):
    service, exe, ini, rom, script, _ = environment
    first = enable(environment)
    (script.parent / "stop").touch()
    second = script.parent.parent / ("b" * 32)
    second.mkdir()
    (second / "connect.lua").write_bytes(b"-- next connection\n")
    (second / "config.lua").write_bytes(b"return {}\n")
    before, state = ini.read_bytes(), service.state_path.read_bytes()
    service.running_probe = lambda path: True
    result = service.prepare(exe, rom, second / "connect.lua", configure_ini=False)
    assert not result.enabled
    assert result.loader_path != first.loader_path
    assert lua_literal(second / "connect.lua") in result.loader_path.read_text()
    assert lua_literal(script) not in result.loader_path.read_text()
    assert ini.read_bytes() == before and service.state_path.read_bytes() == state
    assert "manuellement" in result.message
    with pytest.raises(ValueError, match="ancienne session"):
        service.prepare(exe, rom, script, configure_ini=False)


def test_two_launches_keep_original_restore_target(environment):
    service, exe, ini, rom, script, _ = environment
    before = ini.read_bytes()
    first = enable(environment)
    second = script.parent.parent / ("c" * 32)
    second.mkdir()
    (second / "connect.lua").write_bytes(b"-- next\n")
    (second / "config.lua").write_bytes(b"return {}\n")
    result = service.prepare(exe, rom, second / "connect.lua")
    assert result.loader_path != first.loader_path
    assert IniDocument(ini.read_bytes()).get_text("PathSettings", "Lua") == str(result.loader_path.parent)
    service.restore(exe)
    assert ini.read_bytes() == before


@pytest.mark.parametrize("key,value", [("AutoLoad", "0"), ("Lua", "C:\\Personal New")])
def test_user_changed_keys_are_not_overwritten_or_restored(environment, key, value):
    service, exe, ini, rom, script, _ = environment
    enable(environment)
    document = IniDocument(ini.read_bytes())
    document.set_text("Scripting" if key == "AutoLoad" else "PathSettings", key, value)
    ini.write_bytes(document.to_bytes())
    before = ini.read_bytes()
    with pytest.raises(ValueError, match="hors de PCE"):
        service.prepare(exe, rom, script)
    with pytest.raises(ValueError, match="hors de PCE"):
        service.restore(exe)
    assert ini.read_bytes() == before


def test_unknown_build_or_unverified_lua_cannot_write_ini(environment, monkeypatch):
    service, exe, ini, rom, script, _ = environment
    service.record_consent(exe, True)
    before = ini.read_bytes()
    monkeypatch.setattr(caps, "VERIFIED_BUILD_SHA256", "f" * 64)
    with pytest.raises(ValueError, match="build"):
        service.prepare(exe, rom, script)
    monkeypatch.setattr(caps, "VERIFIED_BUILD_SHA256", hashlib.sha256(exe.read_bytes()).hexdigest())
    monkeypatch.setattr(LuaRuntimeInstaller, "diagnose", lambda self, path:
                        LuaDiagnostic("missing", "x64", (), True, message="DLL absente"))
    with pytest.raises(ValueError, match="Support Lua"):
        service.prepare(exe, rom, script)
    assert ini.read_bytes() == before
    assert not service.loader_root.exists()


@pytest.mark.parametrize("invalid", ["wrong-id", "stopped", "outside", "missing-config", "archive"])
def test_invalid_session_or_unprepared_rom_refused(environment, invalid):
    service, exe, ini, rom, script, _ = environment
    before = ini.read_bytes()
    service.record_consent(exe, True)
    identifier = None
    if invalid == "wrong-id":
        identifier = "d" * 32
    elif invalid == "stopped":
        (script.parent / "stop").touch()
    elif invalid == "outside":
        script = rom.parent / "connect.lua"
        script.write_bytes(b"-- not a PCE session\n")
    elif invalid == "missing-config":
        (script.parent / "config.lua").unlink()
    elif invalid == "archive":
        rom = rom.with_suffix(".zip")
        rom.write_bytes(b"synthetic")
    with pytest.raises(ValueError):
        service.prepare(exe, rom, script, identifier)
    assert ini.read_bytes() == before
    assert not service.loader_root.exists()


def test_existing_non_pce_loader_is_never_replaced(environment):
    service, exe, ini, rom, script, _ = environment
    loader = service.loader_root / script.parent.name / (rom.stem + ".lua")
    loader.parent.mkdir(parents=True)
    loader.write_bytes(b"-- user file moved here\n")
    service.record_consent(exe, True)
    before = ini.read_bytes()
    with pytest.raises(ValueError, match="autre fichier"):
        service.prepare(exe, rom, script)
    assert loader.read_bytes() == b"-- user file moved here\n" and ini.read_bytes() == before


@pytest.mark.parametrize("target", ["ini", "journal", "loader"])
def test_atomic_failure_leaves_ini_and_complete_backup_recoverable(environment, monkeypatch, target):
    service, exe, ini, rom, script, _ = environment
    service.record_consent(exe, True)
    before = ini.read_bytes()
    replace = Path.replace
    def deny(path, destination):
        destination = Path(destination)
        if ((target == "ini" and destination == ini)
                or (target == "journal" and destination == service.state_path)
                or (target == "loader" and destination.suffix == ".lua")):
            raise PermissionError("synthetic lock")
        return replace(path, destination)
    monkeypatch.setattr(Path, "replace", deny)
    with pytest.raises(ValueError):
        service.prepare(exe, rom, script)
    assert ini.read_bytes() == before
    backups = list(exe.parent.glob("*.pce-backup*"))
    assert all(path.read_bytes() == before for path in backups)
    assert not list(exe.parent.glob(".pce_ini_*"))
    monkeypatch.setattr(Path, "replace", replace)
    if target == "ini":
        # Journal persisted first: process interruption/failing replacement is recoverable.
        assert service.restore(exe).enabled is False
        assert ini.read_bytes() == before
    result = service.prepare(exe, rom, script)
    assert result.enabled


def test_late_process_start_prevents_ini_commit(environment):
    service, exe, ini, rom, script, _ = environment
    service.record_consent(exe, True)
    before = ini.read_bytes()
    calls = iter([False, False, True])
    service.running_probe = lambda path: next(calls)
    with pytest.raises(ValueError, match="Fermez"):
        service.prepare(exe, rom, script)
    assert ini.read_bytes() == before
    assert list(exe.parent.glob("*.pce-backup*"))


def test_concurrent_ini_edit_during_journal_is_retained(environment, monkeypatch):
    service, exe, ini, rom, script, _ = environment
    service.record_consent(exe, True)
    before = ini.read_bytes()
    save = service._save_state
    def concurrent(data, raw):
        save(data, raw)
        ini.write_bytes(before + b"; user added while preparing\r\n")
    monkeypatch.setattr(service, "_save_state", concurrent)
    with pytest.raises(ValueError, match="changé"):
        service.prepare(exe, rom, script)
    assert ini.read_bytes() == before + b"; user added while preparing\r\n"


@pytest.mark.parametrize("raw", [b"not json", b'{"schema_version":1,"executables":{},"executables":{}}',
                                b'{"schema_version":true,"executables":{}}'])
def test_invalid_state_is_preserved_and_blocks_changes(environment, raw):
    service, exe, ini, rom, script, _ = environment
    before = ini.read_bytes()
    service.state_path.write_bytes(raw)
    with pytest.raises(ValueError, match="Journal Lua illisible"):
        service.record_consent(exe, True)
    with pytest.raises(ValueError, match="Journal Lua illisible"):
        service.prepare(exe, rom, script)
    assert service.state_path.read_bytes() == raw and ini.read_bytes() == before


def test_corrupt_restore_line_cannot_inject_an_ini_section(environment):
    service, exe, ini, *_ = environment
    enable(environment)
    data = json.loads(service.state_path.read_text(encoding="utf-8"))
    entry = next(iter(data["executables"].values()))
    entry["managed"]["original"][1] = "Lua=personal\n[Malicious]\nOther=1\n"
    service.state_path.write_text(json.dumps(data), encoding="utf-8")
    before = ini.read_bytes()
    with pytest.raises(ValueError, match="Journal Lua"):
        service.restore(exe)
    assert ini.read_bytes() == before


@pytest.mark.parametrize("encoding,bom", [("cp1252", b""), ("utf-16-le", b"\xff\xfe")])
def test_supported_ini_encodings_keep_comments_and_restore(environment, encoding, bom):
    service, exe, ini, *_ = environment
    text = "; café\r\n[Scripting]\r\nAutoLoad=0\r\n[PathSettings]\r\nLua=personnel\r\n"
    before = bom + text.encode(encoding)
    ini.write_bytes(before)
    enable(environment)
    assert ini.read_bytes().startswith(bom + "; café\r\n".encode(encoding))
    service.restore(exe)
    assert ini.read_bytes() == before


def test_missing_keys_restored_to_absence(environment):
    service, exe, ini, *_ = environment
    ini.write_bytes(b"; keep\n[Other]\nX=42\n")
    enable(environment)
    service.restore(exe)
    document = IniDocument(ini.read_bytes())
    assert document.entry_line("Scripting", "AutoLoad") is None
    assert document.entry_line("PathSettings", "Lua") is None
    assert b"; keep\n[Other]\nX=42\n" in ini.read_bytes()


@pytest.mark.parametrize("source", [b"[PathSettings]\nLua=\n[Other]\nX=1\n",
                                  b"[PathSettings]\nLua=", b"[PathSettings]\nLua='C:\\a;literal'\n"])
def test_ini_text_values_handle_empty_and_literal_semicolon(source):
    document = IniDocument(source)
    line = document.entry_line("PathSettings", "Lua")
    document.set_text("PathSettings", "Lua", "C:\\managed path")
    assert document.get_text("PathSettings", "Lua") == "C:\\managed path"
    document.restore_entry("PathSettings", "Lua", line)
    assert document.to_bytes() == source


def test_loader_path_length_cannot_silently_exceed_desmume_buffer(environment):
    service, exe, ini, rom, script, _ = environment
    long_rom = rom.parent / (("R" * 180) + ".nds")
    long_rom.write_bytes(b"filename fixture")
    before = ini.read_bytes()
    service.record_consent(exe, True)
    with pytest.raises(ValueError, match="trop long"):
        service.prepare(exe, long_rom, script)
    assert ini.read_bytes() == before


def test_loader_and_configuration_are_not_redirected_through_links(environment, monkeypatch):
    service, exe, ini, rom, script, _ = environment
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == script.parent or original(path))
    with pytest.raises(ValueError, match="lien ou jonction"):
        service.prepare(exe, rom, script, configure_ini=False)


def test_unreadable_ini_is_a_manual_fallback_not_an_unhandled_oserror(environment, monkeypatch):
    service, exe, ini, rom, script, _ = environment
    service.record_consent(exe, True)
    read = Path.read_bytes
    def denied(path):
        if path == ini:
            raise PermissionError("synthetic locked INI")
        return read(path)
    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(ValueError, match="mode manuel"):
        service.prepare(exe, rom, script)
    assert not service.loader_root.exists()


def test_restore_failure_after_ini_commit_keeps_recovery_journal_for_retry(environment, monkeypatch):
    service, exe, ini, *_ = environment
    before = ini.read_bytes()
    enable(environment)
    state = service.state_path.read_bytes()
    save = service._save_state
    monkeypatch.setattr(service, "_save_state", lambda *args: (_ for _ in ()).throw(PermissionError("locked")))
    with pytest.raises(ValueError):
        service.restore(exe)
    assert ini.read_bytes() == before
    assert service.state_path.read_bytes() == state
    monkeypatch.setattr(service, "_save_state", save)
    assert service.restore(exe).backup_path is None


def test_failed_second_ini_commit_can_restore_first_session_configuration(environment, monkeypatch):
    service, exe, ini, rom, script, _ = environment
    original = ini.read_bytes()
    enable(environment)
    before = ini.read_bytes()
    second = script.parent.parent / ("d" * 32)
    second.mkdir()
    (second / "connect.lua").write_bytes(b"-- next\n")
    (second / "config.lua").write_bytes(b"return {}\n")
    replace = Path.replace
    def denied(path, destination):
        if Path(destination) == ini:
            raise PermissionError("locked")
        return replace(path, destination)
    monkeypatch.setattr(Path, "replace", denied)
    with pytest.raises(ValueError):
        service.prepare(exe, rom, second / "connect.lua")
    assert ini.read_bytes() == before
    monkeypatch.setattr(Path, "replace", replace)
    service.restore(exe)
    assert ini.read_bytes() == original
