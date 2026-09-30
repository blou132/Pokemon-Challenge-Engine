"""Exécute le producteur Lua réel avec une API mémoire synthétique explicite."""
import json

import pytest

from app.services.bridge_service import BridgeService
from app.services.emulator_service import EmulatorService, lua_literal
from test_lua_gen5_reader import PROJECT, PROFILES, lua51, scenario, synthetic_slot


def run_producer(lua51, script, *, slots=(), code="IREF", revision=0, extra="", frames=120, normal_exit=False, profile=None):
    simulation = scenario(profile or PROFILES[1], slots, code=code, revision=revision)
    # scenario définit memory localement ; le producteur consulte l'API globale.
    simulation += f"""
_G.memory = memory
local frames = 0
os.time = function() return 1700000000 + math.floor(frames / 60) end
emu = {{frameadvance = function()
    frames = frames + 1
    {extra}
    if frames >= {frames} then error('FIN_TEST') end
end, registerexit = function(callback) _G.on_exit = callback end}}
local ok, problem = pcall(dofile, {lua_literal(script)})
assert({'ok' if normal_exit else "not ok and tostring(problem):match('FIN_TEST')"}, tostring(problem))
return 'ok'
"""
    return lua51.run(simulation)


def prepare(tmp_path):
    service = BridgeService(tmp_path / "runtime/bridge")
    script = EmulatorService(tmp_path, service).prepare("black2")
    return service, script


def test_real_lua_json_is_accepted_by_python_and_bounds_files(tmp_path, lua51):
    bridge, script = prepare(tmp_path)
    assert run_producer(lua51, script) == "ok"
    files = list(bridge.session_dir.glob("snapshot-*.json"))
    assert len(files) == 2
    state = bridge.poll()
    assert state.connected and state.game_code == "IREF" and state.rom_revision == 0
    assert state.party is None and state.party_size is None
    assert state.sequence == 10  # cinq publications/s sur API synthétique à 60 images/s
    assert "initialisee" in state.last_error


def test_lua_reads_synthetic_party_then_python_validates(tmp_path, lua51):
    bridge, script = prepare(tmp_path)
    run_producer(lua51, script, slots=[synthetic_slot(5, hp=0)])
    state = bridge.poll()
    assert state.status == "receiving"
    assert state.party == [{"slot": 1, "species_id": 501, "level": 5, "hp": 0, "max_hp": 21}]
    assert state.memory_profile == "black2_fr_rev0"


@pytest.mark.parametrize("profile", PROFILES, ids=lambda profile: profile["id"])
def test_all_profiles_cross_the_lua_python_boundary_without_aliases(tmp_path, lua51, profile):
    bridge = BridgeService(tmp_path / "runtime/bridge")
    script = EmulatorService(tmp_path, bridge).prepare(profile["game_id"])
    run_producer(lua51, script, slots=[synthetic_slot(7)], code=profile["game_code"], profile=profile)
    state = bridge.poll()
    assert state.game_id == profile["game_id"] and state.game_code == profile["game_code"]
    assert state.memory_profile == profile["id"] and state.status == "receiving"
    assert state.party == [{"slot": 1, "species_id": 501, "level": 5, "hp": 19, "max_hp": 21}]


@pytest.mark.parametrize("code,revision", [("IREO", 0), ("IREF", 1), ("IREK", 0)])
def test_unsupported_profile_has_identity_only(tmp_path, lua51, code, revision):
    bridge, script = prepare(tmp_path)
    run_producer(lua51, script, slots=[synthetic_slot(0)], code=code, revision=revision)
    state = bridge.poll()
    assert state.connected and state.party is None and state.memory_profile is None
    assert "sans profil" in state.last_error


def test_restart_continues_sequence(tmp_path, lua51):
    bridge, script = prepare(tmp_path)
    run_producer(lua51, script)
    first = bridge.poll().sequence
    run_producer(lua51, script)
    assert bridge.poll().sequence > first
    assert len(list(bridge.session_dir.glob("snapshot-*.json"))) == 2


def test_shutdown_message_clears_party(tmp_path, lua51):
    bridge, script = prepare(tmp_path)
    run_producer(lua51, script, slots=[synthetic_slot(0)], extra="if frames == 119 then on_exit() end", normal_exit=True)
    state = bridge.poll()
    assert state.status == "disconnected" and state.party is None


def test_json_encoder_preserves_null_arrays_and_controls(lua51):
    module = PROJECT / "lua/common/protocol.lua"
    value = 'a\n\t\\"'
    payload = lua51.run(f"local j=dofile({lua_literal(module)}); return j.encode({{a=j.array(), n=j.null, text={lua_literal(value)}}})")
    assert json.loads(payload) == {"a": [], "n": None, "text": value}


def test_truncated_counter_requires_new_session_without_overwriting(tmp_path, lua51):
    bridge, script = prepare(tmp_path)
    run_producer(lua51, script)
    snapshots = {p.name: p.read_bytes() for p in bridge.session_dir.glob('snapshot-*.json')}
    (bridge.session_dir / 'sequence.txt').write_bytes(b'')
    with pytest.raises(AssertionError, match='Compteur local invalide'):
        run_producer(lua51, script)
    assert {p.name: p.read_bytes() for p in bridge.session_dir.glob('snapshot-*.json')} == snapshots


def test_python_stop_is_consumed_by_lua(tmp_path, lua51):
    bridge, script = prepare(tmp_path)
    session = bridge.session_dir
    bridge.stop()
    run_producer(lua51, script, normal_exit=True)
    payload = json.loads(next(session.glob('snapshot-*.json')).read_bytes())
    assert payload['event'] == 'emulator_closing'
