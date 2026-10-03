"""Additive v2 individual identities; legacy producer messages stay usable."""
import json
import struct

import pytest

from app.bridge.protocol import ProtocolError, SCRIPT_VERSION, parse_message
from app.core.pokemon_identity import pokemon_identity
from test_bridge_protocol import party_message
from test_lua_gen5_reader import PROFILES, crypt, lua51, scenario, synthetic_slot


def identity_message(**changes):
    data = party_message(protocol_version=2, script_version=SCRIPT_VERSION, observation=None)
    data["capabilities"].append("party_identity")
    data["party"][0].update(personality_id=0xEE123456, original_trainer_id=0xABCDEF00)
    return data | changes


def decode(data):
    return parse_message(json.dumps(data).encode())


@pytest.mark.parametrize("version,script", [(1, "0.2.0"), (2, "0.3.0"), (2, "0.4.0")])
def test_legacy_party_fields_are_unchanged(version, script):
    data = party_message(protocol_version=version, script_version=script)
    if version == 2:
        data["observation"] = None
    assert decode(data).party == data["party"]
    assert pokemon_identity(decode(data).party[0]) is None


def test_new_identity_roundtrips_without_a_protocol_bump():
    data = identity_message()
    result = decode(data)
    assert result.protocol_version == 2 and result.script_version == "0.4.0"
    assert result.party == data["party"]
    assert pokemon_identity(result.party[0]) == "gen5:ee123456:abcdef00"


def test_current_lua_declares_its_own_version_with_an_older_local_configuration(tmp_path, lua51):
    from test_lua_bridge import prepare, run_producer
    bridge, script = prepare(tmp_path)
    config = bridge.session_dir / "config.lua"
    config.write_text(config.read_text(encoding="utf-8").replace('0.4.0', '0.3.0'), encoding="utf-8")
    run_producer(lua51, script, slots=[synthetic_slot(0)])
    state = bridge.poll()
    assert state.script_version == "0.4.0"
    assert state.connected and state.party[0]["personality_id"] == 0xA3000555


@pytest.mark.parametrize("field", ["personality_id", "original_trainer_id"])
@pytest.mark.parametrize("value", [-1, 0x100000000, True, False, 1.0, "12", {}, []])
def test_identity_accepts_only_exact_unsigned_32_bit_integers(field, value):
    data = identity_message()
    data["party"][0][field] = value
    with pytest.raises(ProtocolError):
        decode(data)


@pytest.mark.parametrize("value", [0, 0xFFFFFFFF, None])
def test_identity_unsigned_boundaries_and_unknown(value):
    data = identity_message()
    data["party"][0].update(personality_id=value, original_trainer_id=value)
    assert decode(data).party[0]["personality_id"] == value


def test_identity_requires_its_capability():
    data = identity_message()
    data["capabilities"].remove("party_identity")
    with pytest.raises(ProtocolError, match="capacité"):
        decode(data)


@pytest.mark.parametrize("version,script", [(1, "0.2.0"), (2, "0.3.0")])
def test_older_scripts_cannot_claim_the_new_identity(version, script):
    data = identity_message(protocol_version=version, script_version=script)
    if version == 1:
        del data["observation"]
    with pytest.raises(ProtocolError):
        decode(data)


def test_incomplete_pair_can_be_transported_but_is_not_strong_identity():
    data = identity_message()
    del data["party"][0]["original_trainer_id"]
    assert pokemon_identity(decode(data).party[0]) is None


def test_duplicate_individuals_remain_visible_for_run_ambiguity_handling():
    data = identity_message(party_size=2)
    data["party"].append(data["party"][0] | {"slot": 2})
    party = decode(data).party
    assert len(party) == 2
    assert pokemon_identity(party[0]) == pokemon_identity(party[1])


@pytest.mark.parametrize("script", [[], {}, None, 4, "0.5.0"])
def test_unknown_or_malformed_script_version_is_protocol_error(script):
    with pytest.raises(ProtocolError):
        decode(identity_message(script_version=script))


@pytest.mark.parametrize("permutation", range(32))
def test_lua_reads_unsigned_pid_and_original_trainer_from_every_permutation(lua51, permutation):
    script = scenario(PROFILES[2], [synthetic_slot(permutation)], after="""
local result = reader.read_party(memory, profile)
assert(result.status == 'ok', result.message)
return string.format('%.0f,%.0f', result.party[1].personality_id, result.party[1].original_trainer_id)
""")
    assert lua51.run(script) == f"{0xA3000555 | (permutation << 13)},{0x10EBC6A1}"


@pytest.mark.parametrize("pid,trainer", [(0, 0), (0xFFFFFFFF, 0xFFFFFFFF), (0x80000000, 0x80000000)])
def test_lua_identity_boundaries_survive_encryption(lua51, pid, trainer):
    # Independent canonical fixture, shuffled according to the actual PID.
    from test_lua_gen5_reader import PERMUTATIONS
    canonical = bytearray(128)
    struct.pack_into("<H", canonical, 0, 498)
    struct.pack_into("<I", canonical, 4, trainer)
    checksum = sum(word for (word,) in struct.iter_unpack("<H", canonical)) & 0xFFFF
    permutation = ((pid >> 13) & 31) % 24
    physical = b"".join(canonical[index * 32:index * 32 + 32] for index in PERMUTATIONS[permutation])
    stats = bytearray(84)
    stats[4] = 5
    struct.pack_into("<HH", stats, 6, 19, 21)
    slot = struct.pack("<IHH", pid, 0, checksum) + crypt(physical, checksum) + crypt(stats, pid)
    script = scenario(PROFILES[2], [slot], after="""
local result = reader.read_party(memory, profile)
assert(result.status == 'ok', result.message)
return string.format('%.0f,%.0f', result.party[1].personality_id, result.party[1].original_trainer_id)
""")
    assert lua51.run(script) == f"{pid},{trainer}"
