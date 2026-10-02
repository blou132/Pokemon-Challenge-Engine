"""Préparation locale : lecture d'en-tête, ressources et absence d'écriture ROM."""
import pytest

from app.services.bridge_service import BridgeService
from app.services.emulator_service import EmulatorService, lua_literal
from test_lua_gen5_reader import lua51


def test_prepare_reads_header_without_modifying_rom(tmp_path, lua51):
    rom = tmp_path / "jeu.nds"
    header = bytearray(512)
    header[12:16] = b"IREF"
    rom.write_bytes(header)
    before = rom.stat().st_mtime_ns
    bridge = BridgeService(tmp_path / "runtime/bridge")
    script = EmulatorService(tmp_path, bridge).prepare("black2", str(rom))
    assert script.name == "connect.lua" and script.is_file()
    assert bridge.state.status == "waiting"
    config = bridge.root / "current-black2.lua"
    assert lua51.run(f"local c=dofile({lua_literal(config)}); return c.expected_code .. ':' .. c.expected_revision") == "IREF:0"
    assert rom.read_bytes() == header and rom.stat().st_mtime_ns == before


@pytest.mark.parametrize("name,header", [("bad.zip", bytes(512)), ("short.nds", b"IRE"), ("wrong.nds", bytes(512))])
def test_invalid_rom_does_not_start_session(tmp_path, name, header):
    path = tmp_path / name
    path.write_bytes(header)
    bridge = BridgeService(tmp_path / "runtime/bridge")
    with pytest.raises(ValueError):
        EmulatorService(tmp_path, bridge).prepare("black2", str(path))
    assert bridge.session_dir is None
    assert path.read_bytes() == header


def test_session_ids_are_new_and_manual_mode_requires_no_rom(tmp_path):
    bridge = BridgeService(tmp_path / "runtime/bridge")
    service = EmulatorService(tmp_path, bridge)
    first = service.prepare("black")
    second = service.prepare("black")
    assert first.parent != second.parent
    assert first.is_file() and second.is_file()
    assert bridge.state.received_count == 0


def test_lua_literal_does_not_execute_string_content(lua51):
    value = '\"; error("injection") --\n\\é'
    assert lua51.run(f"return {lua_literal(value)}") == value


def test_reconnect_keeps_stopped_script_bound_to_its_original_session(tmp_path, lua51):
    bridge = BridgeService(tmp_path / "runtime/bridge")
    service = EmulatorService(tmp_path, bridge)
    first = service.prepare("white")
    first_id = bridge.session_id
    original = first.read_bytes()
    bridge.stop()
    second = service.prepare("white")
    assert (first.parent / "stop").exists()
    assert first.read_bytes() == original
    for script, session_id in ((first, first_id), (second, bridge.session_id)):
        # Run the generated entrypoint with a bridge spy: verify which config
        # it actually supplies, not just the spelling of a path in its source.
        code = ("local original=dofile; local selected; "
                "dofile=function(path) if path:match('bridge.lua$') then "
                "return {run=function(config) selected=original(config) end} "
                "end return original(path) end; dofile(" + lua_literal(script) + "); "
                "return selected.session_id")
        assert lua51.run(code) == session_id


def test_missing_rom_is_read_only_error(tmp_path):
    bridge = BridgeService(tmp_path / "runtime/bridge")
    with pytest.raises(OSError):
        EmulatorService(tmp_path, bridge).prepare("black", str(tmp_path / "missing.nds"))
    assert not (tmp_path / "missing.nds").exists()


@pytest.mark.parametrize("game,code", [("black", "IRBF"), ("white", "IRAF"), ("black2", "IREF"), ("white2", "IRDF")])
def test_all_four_rom_headers_select_the_exact_game(tmp_path, game, code):
    header = bytearray(512)
    header[12:16] = code.encode("ascii")
    rom = tmp_path / "game.nds"
    rom.write_bytes(header)
    bridge = BridgeService(tmp_path / "runtime/bridge")
    service = EmulatorService(tmp_path, bridge)
    assert service.prepare(game, str(rom)).is_file()
    session = bridge.session_id
    for other in {"black", "white", "black2", "white2"} - {game}:
        with pytest.raises(ValueError, match="ne correspond pas"):
            service.prepare(other, str(rom))
        assert bridge.session_id == session
    assert rom.read_bytes() == header
