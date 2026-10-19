"""Synthetic frame/PK5 checks; these do not constitute live Pokémon validation."""

import itertools
import json
from pathlib import Path
import struct

import pytest

from app.bridge.melonds import BRIDGE_VERSION, UPSTREAM_REVISION, MelonDSBridgeReader, decode_pk5
from app.bridge.protocol import ProtocolError, parse_message
from app.core.shiny import shiny_status
from app.services.bridge_service import BridgeService

PROJECT = Path(__file__).resolve().parents[1]
PROFILES = json.loads((PROJECT / "data/memory_profiles.json").read_text(encoding="utf-8"))
PERMUTATIONS = tuple(itertools.permutations(range(4)))


def encrypted_slot(permutation, *, species=501, form=0, level=5, hp=19, maximum=21, shiny=False):
    pid = 0xA3000555 | (permutation << 13)
    trainer = pid if shiny else pid ^ 8
    canonical = bytearray(128)
    struct.pack_into("<H", canonical, 0, species)
    struct.pack_into("<I", canonical, 4, trainer)
    canonical[0x38] = (form << 3) | 7
    checksum = sum(struct.unpack("<64H", canonical)) & 0xFFFF
    physical = b"".join(canonical[index*32:(index+1)*32] for index in PERMUTATIONS[permutation % 24])
    stats = bytearray(84)
    stats[4] = level
    struct.pack_into("<HH", stats, 6, hp, maximum)

    def crypt(raw, seed):
        result = bytearray()
        for (word,) in struct.iter_unpack("<H", raw):
            seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
            result.extend(struct.pack("<H", word ^ (seed >> 16)))
        return bytes(result)

    return struct.pack("<IHH", pid, 0, checksum) + crypt(physical, checksum) + crypt(stats, pid)


def frame(profile, session_id, *, slots=None, **changes):
    if slots is None:
        slots = [encrypted_slot(17)]
    result = {
        "bridge_version": BRIDGE_VERSION, "source_revision": UPSTREAM_REVISION,
        "session_id": session_id, "sequence": 1, "timestamp": 1770000000,
        "console_type": 0, "rom_code": profile["game_code"], "rom_revision": profile["revision"],
        "ram_code": profile["game_code"], "ram_revision": profile["revision"],
        "memory_profile": profile["id"], "party_count": len(slots),
        "party_hex": b"".join(slots).hex(), "map_id": 6 if profile["game_id"] in {"black", "white"} else None,
        "status": "ok",
    }
    result.update(changes)
    return result


def start(tmp_path, profile):
    bridge = BridgeService(tmp_path)
    bridge.start(profile["game_id"], profile["game_code"], profile["revision"])
    reader = MelonDSBridgeReader(bridge.session_dir, bridge.session_id, profile["game_code"], profile["revision"])
    return bridge, reader


def publish(reader, value):
    (reader.session_dir / "melonds-frame.json").write_text(json.dumps(value), encoding="utf-8")
    return reader.poll()


@pytest.mark.parametrize("permutation", range(32))
@pytest.mark.parametrize("form", [0, 1, 31])
def test_decrypts_all_pid_permutations_and_form_bits(permutation, form):
    pokemon = decode_pk5(encrypted_slot(permutation, form=form), 1)
    assert (pokemon["species_id"], pokemon["level"], pokemon["hp"], pokemon["max_hp"], pokemon["form"]) == (501, 5, 19, 21, form)
    assert pokemon["personality_id"] > 2**31
    assert shiny_status(pokemon) is False


@pytest.mark.parametrize("shiny", [False, True])
def test_identity_reuses_existing_shiny_calculation(shiny):
    assert shiny_status(decode_pk5(encrypted_slot(7, shiny=shiny), 1)) is shiny


@pytest.mark.parametrize("offset", [4, 6, 8, 57, 135])
def test_corrupt_pk5_never_publishes_a_party(tmp_path, offset):
    bridge, reader = start(tmp_path, PROFILES[0])
    raw = bytearray(encrypted_slot(7))
    raw[offset] ^= 1
    with pytest.raises(ValueError):
        publish(reader, frame(PROFILES[0], bridge.session_id, slots=[bytes(raw)]))
    assert bridge.poll().party is None
    assert not list(reader.session_dir.glob("snapshot-*"))


@pytest.mark.parametrize("profile", PROFILES, ids=lambda item: item["id"])
def test_four_game_profiles_publish_valid_party_and_only_documented_tracking(tmp_path, profile):
    bridge, reader = start(tmp_path, profile)
    slots = [encrypted_slot(index, species=index+1, level=100, hp=0) for index in range(6)]
    assert publish(reader, frame(profile, bridge.session_id, slots=slots))
    state = bridge.poll()
    assert state.status == "receiving"
    assert state.party_size == 6
    assert [entry["species_id"] for entry in state.party] == list(range(1, 7))
    assert all(entry["hp"] == 0 for entry in state.party)
    if profile["game_id"] in {"black", "white"}:
        assert state.observation["capture_zone_id"] == "striaton_city"
        assert state.observation["battle_active"] is None
        assert state.observation["capture_success"] is None
        assert len(state.observations) == 1
        bridge.acknowledge_observations(state)
        assert not list(reader.session_dir.glob("observation-*"))
    else:
        assert state.observation is None
        assert "tracking" not in state.capabilities


@pytest.mark.parametrize("change", [
    {"session_id": "f" * 32}, {"rom_code": "IRAO"}, {"rom_revision": 1},
    {"ram_code": "IRAF"}, {"ram_revision": 1}, {"console_type": 1}, {"console_type": False},
    {"memory_profile": "white_fr_rev0"}, {"sequence": True}, {"timestamp": -1},
    {"source_revision": "main"}, {"bridge_version": "1.1"}, {"party_count": 7},
    {"party_count": True}, {"party_hex": "00"}, {"map_id": 65536}, {"unexpected": 1},
])
def test_rejects_identity_revision_and_transport_mismatches(tmp_path, change):
    bridge, reader = start(tmp_path, PROFILES[0])
    with pytest.raises(ValueError):
        publish(reader, frame(PROFILES[0], bridge.session_id) | change)
    assert bridge.poll().party is None


def test_rejects_undocumented_sequel_map(tmp_path):
    profile = next(item for item in PROFILES if item["game_id"] == "black2")
    bridge, reader = start(tmp_path, profile)
    with pytest.raises(ValueError, match="Carte"):
        publish(reader, frame(profile, bridge.session_id, map_id=6))


def test_heartbeat_is_never_party_evidence_and_duplicates_do_not_refresh_timeout(tmp_path):
    ticks = [0.0]
    bridge = BridgeService(tmp_path, clock=lambda: ticks[0])
    profile = PROFILES[0]
    bridge.start(profile["game_id"], profile["game_code"], profile["revision"])
    reader = MelonDSBridgeReader(bridge.session_dir, bridge.session_id, profile["game_code"], profile["revision"])
    value = frame(profile, bridge.session_id, status="not_ready", party_count=0, party_hex=None, map_id=None)
    assert publish(reader, value)
    state = bridge.poll()
    assert state.status == "connected" and state.party is None
    assert state.capabilities == ("heartbeat", "game_identity")
    ticks[0] = 4
    assert not reader.poll()
    assert bridge.poll().status == "disconnected"


def test_changed_zones_persist_until_ack_and_stop_prevents_new_publications(tmp_path):
    bridge, reader = start(tmp_path, PROFILES[0])
    assert publish(reader, frame(PROFILES[0], bridge.session_id))
    assert publish(reader, frame(PROFILES[0], bridge.session_id, sequence=2, map_id=7))
    state = bridge.poll()
    assert len(state.observations) == 2
    assert len(list(reader.session_dir.glob("snapshot-*"))) == 1
    assert publish(reader, frame(PROFILES[0], bridge.session_id, sequence=3, map_id=7))
    assert len(bridge.poll().observations) == 2
    bridge.stop()
    assert not publish(reader, frame(PROFILES[0], reader.session_id, sequence=4))


def test_rejects_oversized_and_duplicate_json_without_publication(tmp_path):
    bridge, reader = start(tmp_path, PROFILES[0])
    path = reader.session_dir / "melonds-frame.json"
    path.write_bytes(b" " * 65537)
    with pytest.raises(ValueError, match="volumineux"):
        reader.poll()
    path.write_text('{"sequence":1,"sequence":2}', encoding="utf-8")
    with pytest.raises(ValueError, match="dupliqué"):
        reader.poll()


def test_protocol_accepts_only_current_melonds_protocol(tmp_path):
    bridge, reader = start(tmp_path, PROFILES[0])
    publish(reader, frame(PROFILES[0], bridge.session_id))
    message = json.loads(next(reader.session_dir.glob("snapshot-*.json")).read_text(encoding="utf-8"))
    assert parse_message(json.dumps(message).encode()).emulator == "melonds"
    for changed in ({"script_version": "0.4.0"}, {"emulator": "unknown"}, {"protocol_version": 1}):
        with pytest.raises(ProtocolError):
            parse_message(json.dumps(message | changed).encode())
