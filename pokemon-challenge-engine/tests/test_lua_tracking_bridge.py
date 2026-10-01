"""Production Lua → journal → Python, sur des observations explicitement factices.

Les cartes utilisent les adresses sourcées sur une RAM synthétique. Les combats
remplacent le lecteur par une fixture de contrat ; aucune adresse de combat
fictive n'est présentée comme une adresse du jeu.
"""

import json

import pytest

from app.services.bridge_service import BridgeService
from app.services.emulator_service import EmulatorService, lua_literal
from test_lua_gen5_reader import PROFILES, lua51, scenario


WHITE = next(profile for profile in PROFILES if profile["game_id"] == "white")


def prepare(tmp_path):
    bridge = BridgeService(tmp_path / "runtime/bridge")
    return bridge, EmulatorService(tmp_path, bridge).prepare("white")


def run_tracking(lua51, script, *, frame_code="", frames=120,
                 synthetic_reader=None, normal_exit=False):
    simulation = scenario(WHITE)
    simulation += f"""
_G.memory = memory
local frames = 0
ram[0x0224F8AC], ram[0x0224F8AD] = 61, 1 -- Route 1 : carte 317 documentée
os.time = function() return 1700000000 + math.floor(frames / 60) end
"""
    if synthetic_reader is not None:
        # Injection au contrat du lecteur, jamais faux offsets RAM de combat.
        simulation += f"""
local original_dofile = dofile
dofile = function(path)
    if path:match('gen5_tracking_reader%.lua$') then
        return {{read_observation = function(memory, identity, profile)
            {synthetic_reader}
        end}}
    end
    return original_dofile(path)
end
"""
    simulation += f"""
emu = {{frameadvance = function()
    frames = frames + 1
    {frame_code}
    if frames >= {frames} then error('FIN_TEST') end
end, registerexit = function(callback) _G.on_exit = callback end}}
local ok, problem = pcall(dofile, {lua_literal(script)})
assert({'ok' if normal_exit else "not ok and tostring(problem):match('FIN_TEST')"}, tostring(problem))
return 'ok'
"""
    return lua51.run(simulation)


def test_production_lua_map_journal_survives_lost_snapshots(tmp_path, lua51):
    bridge, script = prepare(tmp_path)
    changes = """
if frames == 24 then ram[0x0224F8AC] = 63 end -- Route 2 : 319
if frames == 48 then ram[0x0224F8AC] = 65 end -- Route 3 : 321
if frames == 72 then ram[0x0224F8AC] = 61 end -- Retour Route 1
"""
    run_tracking(lua51, script, frame_code=changes)
    assert len(list(bridge.session_dir.glob("snapshot-*.json"))) == 2
    assert not (bridge.session_dir / "snapshot-0000000001.json").exists()
    state = bridge.poll()
    assert state.sequence == 10
    assert [item["sequence"] for item in state.observations] == [1, 3, 5, 7]
    assert [item["observation"]["map_id"] for item in state.observations] == [317, 319, 321, 317]
    assert all(item["observation"]["battle_active"] is None for item in state.observations)
    assert bridge.poll().observations == state.observations
    bridge.acknowledge_observations(state)
    assert not list(bridge.session_dir.glob("observation-*.json"))
    assert (bridge.session_dir / "ack.txt").read_text() == "10"


@pytest.mark.parametrize("outcome", ["captured", "fainted", "player_fled", "escaped", "battle_ended_unknown"])
def test_synthetic_reader_lifecycle_survives_lua_transport(tmp_path, lua51, outcome):
    bridge, script = prepare(tmp_path)
    fixture = f"""
local value = {{status = 'ok', map_id = 317, capture_zone_id = 'route_1', zone_name = 'Route 1',
                battle_active = false}}
if frames >= 12 then
    value.battle_id = 'synthetic-battle-1'
    value.battle_type = 'wild'
    value.encounter_kind = 'wild_standard'
    value.wild_encounter = true
    value.species_id, value.level, value.hp, value.max_hp = 504, 3, 11, 11
    value.encounter_slot = 0
    value.battle_active = true
    value.encounter_started = true
end
if frames >= 36 then
    value.battle_active, value.encounter_started, value.encounter_ended = false, false, true
    value.outcome = {lua_literal(outcome)}
    if value.outcome == 'captured' then value.capture_detected, value.capture_success = true, true end
    if value.outcome == 'fainted' then value.hp, value.fainted_wild = 0, true end
    if value.outcome == 'player_fled' then value.fled = 'player' end
    if value.outcome == 'escaped' then value.fled = 'wild' end
    if value.outcome == 'battle_ended_unknown' then value.fled = 'unknown' end
end
return value
"""
    run_tracking(lua51, script, synthetic_reader=fixture)
    state = bridge.poll()
    assert state.connected
    assert [item["sequence"] for item in state.observations] == [1, 2, 4]
    initial, started, ended = [item["observation"] for item in state.observations]
    assert initial["battle_active"] is False and initial["outcome"] is None
    assert started["battle_id"] == ended["battle_id"] == "synthetic-battle-1"
    assert started["species_id"] == 504 and started["level"] == 3
    assert ended["battle_active"] is False and ended["outcome"] == outcome
    assert ended["capture_success"] is (True if outcome == "captured" else None)
    # Continuer jusqu'aux fichiers du profil avec le service de production.
    from app.services.tracking_service import TrackingService
    from test_tracking_persistence import create
    manager, profile = create(tmp_path)
    tracker = TrackingService(tmp_path)
    tracker.select_profile(profile.id)
    assert tracker.consume(state).zone_used is True
    saved = manager.load(profile.id)
    zone = saved.progress["nuzlocke"]["zones"]["route_1"]
    assert zone["first_encounter"]["result"] == outcome
    assert len(saved.history) == 3
    before = saved.history
    restarted = TrackingService(tmp_path)
    restarted.select_profile(profile.id)
    restarted.consume(state)
    assert manager.load(profile.id).history == before
    bridge.acknowledge_observations(state)
    assert not bridge.poll().observations


def test_closing_preserves_earlier_production_lua_observations(tmp_path, lua51):
    bridge, script = prepare(tmp_path)
    run_tracking(lua51, script, frame_code="if frames == 119 then on_exit() end", normal_exit=True)
    state = bridge.poll()
    assert state.status == "disconnected" and state.last_event == "emulator_closing"
    assert state.observation is None
    assert len(state.observations) == 1
    assert state.observations[0]["observation"]["map_id"] == 317
    bridge.acknowledge_observations(state)
    assert not list(bridge.session_dir.glob("observation-*.json"))


def test_restart_keeps_unacknowledged_observations_and_sequence(tmp_path, lua51):
    bridge, script = prepare(tmp_path)
    run_tracking(lua51, script)
    first = bridge.poll()
    run_tracking(lua51, script)
    second = bridge.poll()
    assert second.sequence > first.sequence
    assert [item["sequence"] for item in second.observations] == [1, 11]
    assert second.observations[0] == first.observations[0]


def test_foreign_session_ack_cannot_delete_live_journal(tmp_path, lua51):
    from dataclasses import replace

    bridge, script = prepare(tmp_path)
    run_tracking(lua51, script)
    state = bridge.poll()
    bridge.acknowledge_observations(replace(state, session_id="0" * 32))
    assert len(list(bridge.session_dir.glob("observation-*.json"))) == 1
    assert not (bridge.session_dir / "ack.txt").exists()


def test_long_heartbeat_stream_does_not_fill_observation_journal(tmp_path, lua51):
    bridge, script = prepare(tmp_path)
    run_tracking(lua51, script, frames=3900,
                 frame_code="if frames == 3840 then ram[0x0224F8AC] = 63 end")
    state = bridge.poll()
    assert state.connected and state.sequence == 325
    assert [item["observation"]["map_id"] for item in state.observations] == [317, 319]
    assert len(list(bridge.session_dir.glob("pending-*.txt"))) == 2


def test_full_journal_stops_with_visible_error_without_losing_pending_events(tmp_path, lua51):
    bridge, script = prepare(tmp_path)
    fixture = "return {status='ok', map_id=math.floor(frames / 12)}"
    run_tracking(lua51, script, frames=4000, synthetic_reader=fixture, normal_exit=True)
    state = bridge.poll()
    assert not state.connected
    assert "Journal plein" in state.last_error
    assert len(state.observations) == 256
    assert len(list(bridge.session_dir.glob("observation-*.json"))) == 256


def test_corrupted_pending_index_refuses_restart_without_erasing_evidence(tmp_path, lua51):
    bridge, script = prepare(tmp_path)
    run_tracking(lua51, script)
    path = bridge.session_dir / "pending-0000000010.txt"
    path.write_bytes(b"broken")
    with pytest.raises(AssertionError, match="Index du journal"):
        run_tracking(lua51, script)
    assert path.read_bytes() == b"broken"
    assert len(list(bridge.session_dir.glob("observation-*.json"))) == 1
