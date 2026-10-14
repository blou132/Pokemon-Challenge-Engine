"""Optional stored Gen V forms, with legacy producer compatibility."""

import pytest

from app.bridge.protocol import ProtocolError
from test_identity_protocol import decode, identity_message
from test_lua_gen5_reader import PROFILES, lua51, scenario, synthetic_slot


def form_message(value=0, **changes):
    data = identity_message(script_version="0.5.0")
    data["capabilities"].append("party_form")
    data["party"][0]["form"] = value
    return data | changes


@pytest.mark.parametrize("value", [0, 1, 31, None])
def test_form_roundtrips_without_a_protocol_bump(value):
    data = form_message(value)
    result = decode(data)
    assert result.protocol_version == 2
    assert result.party == data["party"]


@pytest.mark.parametrize("value", [-1, 32, True, False, 1.0, "1", [], {}])
def test_form_rejects_non_five_bit_integers(value):
    with pytest.raises(ProtocolError):
        decode(form_message(value))


def test_available_form_requires_its_capability():
    data = form_message()
    data["capabilities"].remove("party_form")
    with pytest.raises(ProtocolError, match="party_form"):
        decode(data)


def test_unknown_form_does_not_claim_base_form_or_require_capability():
    data = form_message(None)
    data["capabilities"].remove("party_form")
    assert decode(data).party[0]["form"] is None
    del data["party"][0]["form"]
    assert "form" not in decode(data).party[0]


@pytest.mark.parametrize("script", ["0.3.0", "0.4.0"])
@pytest.mark.parametrize("include_field", [True, False])
def test_old_scripts_cannot_claim_form_data_or_capability(script, include_field):
    data = form_message(script_version=script)
    data["capabilities"].remove("party_identity")
    del data["party"][0]["personality_id"]
    del data["party"][0]["original_trainer_id"]
    if not include_field:
        del data["party"][0]["form"]
    else:
        data["capabilities"].remove("party_form")
    with pytest.raises(ProtocolError, match="forme"):
        decode(data)


@pytest.mark.parametrize("script", ["0.4.0", "0.5.0"])
def test_identity_remains_available_without_form(script):
    data = identity_message(script_version=script)
    assert decode(data).party == data["party"]
    assert "form" not in decode(data).party[0]


@pytest.mark.parametrize("profile", PROFILES, ids=lambda value: value["id"])
@pytest.mark.parametrize("permutation", range(32))
def test_lua_reads_block_b_form_in_every_pid_permutation(lua51, profile, permutation):
    script = scenario(profile, [synthetic_slot(permutation, form=permutation)], after="""
local result = reader.read_party(memory, profile)
assert(result.status == 'ok', result.message)
return tostring(result.party[1].form)
""")
    assert lua51.run(script) == str(permutation)


@pytest.mark.parametrize("flags", range(8))
@pytest.mark.parametrize("form", [0, 1, 31])
def test_lua_form_excludes_gender_and_fateful_encounter_bits(lua51, flags, form):
    script = scenario(PROFILES[2], [synthetic_slot(19, form=form, form_flags=flags)], after="""
local result = reader.read_party(memory, profile)
assert(result.status == 'ok', result.message)
return tostring(result.party[1].form)
""")
    assert lua51.run(script) == str(form)


def test_current_lua_publishes_form_with_capability(tmp_path, lua51):
    from test_lua_bridge import prepare, run_producer

    bridge, script = prepare(tmp_path)
    run_producer(lua51, script, slots=[synthetic_slot(23, species=479, form=2)])
    state = bridge.poll()
    assert state.connected
    assert state.script_version == "0.5.0"
    assert state.party[0]["form"] == 2
    assert "party_form" in state.capabilities
