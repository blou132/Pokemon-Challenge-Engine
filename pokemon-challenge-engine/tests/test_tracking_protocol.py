"""Contrat v2 et journal sur événements synthétiques, sans ROM ni émulateur."""
import json

import pytest

from app.bridge.protocol import OBSERVATION_FIELDS, ProtocolError, parse_message
from app.services.bridge_service import BridgeService
from test_bridge_protocol import message


def observation(**changes):
    return dict.fromkeys(OBSERVATION_FIELDS) | changes


def tracking_message(**changes):
    return message(protocol_version=2, script_version="0.3.0", game_id="white", game_code="IRAF",
                   capabilities=["heartbeat", "game_identity", "tracking"],
                   observation=observation(map_id=317, capture_zone_id="route_1", zone_name="Route 1")) | changes


def encode(data):
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def test_v1_and_v2_are_explicitly_compatible():
    assert parse_message(encode(message())).observation is None
    value = parse_message(encode(tracking_message()))
    assert value.protocol_version == 2 and value.observation["battle_active"] is None
    assert value.observation["map_id"] == 317


@pytest.mark.parametrize("changes", [
    {"protocol_version": 3}, {"protocol_version": True}, {"script_version": "0.2.0"},
    {"capabilities": ["heartbeat", "game_identity"]}, {"game_code": None},
    {"observation": {}}, {"observation": observation(battle_active=1)},
    {"observation": observation(hp=12, max_hp=10)},
    {"observation": observation(species_id=650)}, {"observation": observation(level=0)},
    {"observation": observation(battle_type="trainer", wild_encounter=True)},
    {"observation": observation(capture_success=True)},
    {"observation": observation(outcome="captured")},
    {"observation": observation(capture_zone_id="")},
])
def test_v2_rejects_ambiguous_or_unsupported_values(changes):
    with pytest.raises(ProtocolError):
        parse_message(encode(tracking_message(**changes)))


@pytest.mark.parametrize("outcome", ["captured", "fainted", "escaped", "player_fled", "battle_ended_unknown"])
def test_known_outcomes_are_transportable_without_inference(outcome):
    data = observation(battle_id="synthetic-pid-123", battle_active=False, battle_type="wild",
                       encounter_kind="wild_standard", species_id=504, level=3, outcome=outcome,
                       capture_detected=True if outcome == "captured" else None,
                       capture_success=True if outcome == "captured" else None)
    assert parse_message(encode(tracking_message(observation=data))).observation == data


def write_message(bridge, sequence, value, *, journal=False):
    data = tracking_message(session_id=bridge.session_id, sequence=sequence, observation=value)
    if journal:
        (bridge.session_dir / f"observation-{sequence:010d}.json").write_bytes(encode(data))
    (bridge.session_dir / f"snapshot-{sequence:010d}.json").write_bytes(encode(data))


def test_journal_preserves_skipped_snapshot_lifecycle_until_explicit_ack(tmp_path):
    bridge = BridgeService(tmp_path)
    bridge.start("white")
    for sequence, active, outcome in [(1, False, None), (2, True, None), (3, False, "fainted")]:
        write_message(bridge, sequence, observation(map_id=317, capture_zone_id="route_1",
                                                   battle_active=active, outcome=outcome), journal=True)
    (bridge.session_dir / "snapshot-0000000001.json").unlink()
    state = bridge.poll()
    assert state.sequence == 3
    assert [item["sequence"] for item in state.observations] == [1, 2, 3]
    assert bridge.poll().observations == state.observations
    assert len(list(bridge.session_dir.glob("observation-*.json"))) == 3
    bridge.acknowledge_observations(state)
    assert not list(bridge.session_dir.glob("observation-*.json"))
    assert (bridge.session_dir / "ack.txt").read_text() == "3"
    assert not bridge.poll().observations


def test_closing_can_drain_known_events_but_never_invents_result(tmp_path):
    bridge = BridgeService(tmp_path)
    bridge.start("white")
    write_message(bridge, 1, observation(map_id=317), journal=True)
    closing = tracking_message(session_id=bridge.session_id, sequence=2, event="emulator_closing", observation=None)
    (bridge.session_dir / "snapshot-0000000002.json").write_bytes(encode(closing))
    state = bridge.poll()
    assert not state.connected and state.observation is None
    assert len(state.observations) == 1 and state.observations[0]["observation"]["outcome"] is None
    bridge.acknowledge_observations(state)
    assert not list(bridge.session_dir.glob("observation-*.json"))


def test_journal_corruption_blocks_tracking_and_preserves_file(tmp_path):
    bridge = BridgeService(tmp_path)
    bridge.start("white")
    write_message(bridge, 1, observation(map_id=317), journal=True)
    path = bridge.session_dir / "observation-0000000001.json"
    path.write_bytes(b"{")
    assert bridge.poll().status == "error"
    assert path.read_bytes() == b"{"


def test_pending_journal_cannot_mix_games(tmp_path):
    bridge = BridgeService(tmp_path)
    bridge.start("white")
    write_message(bridge, 1, observation(map_id=317))
    foreign = tracking_message(session_id=bridge.session_id, game_id="black", game_code="IRBF")
    (bridge.session_dir / "observation-0000000001.json").write_bytes(encode(foreign))
    assert bridge.poll().status == "error"
