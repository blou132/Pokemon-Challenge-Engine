"""RAM synthétique seulement : cartes BW et refus de conclusions non sourcées."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.services.emulator_service import lua_literal
from test_lua_gen5_reader import lua51  # noqa: F401 — moteur Lua 5.1 réel, RAM factice


PROJECT = Path(__file__).resolve().parents[1]
PROFILES = json.loads((PROJECT / "data/tracking_profiles.json").read_text(encoding="utf-8"))
ZONES = json.loads((PROJECT / "data/capture_zones.json").read_text(encoding="utf-8"))
BW = [profile for profile in PROFILES if profile["game_id"] in {"black", "white"}]
BATTLE_FIELDS = (
    "battle_active", "battle_type", "encounter_kind", "battle_id", "species_id",
    "level", "hp", "max_hp", "encounter_slot", "outcome", "wild_encounter",
    "encounter_started", "encounter_ended", "capture_detected", "capture_success",
    "fainted_wild", "fled",
)


def scenario(profile, *, map_id=317, actual_code=None, actual_revision=0, before="", after=""):
    selected = copy.deepcopy(profile)
    selected["capture_zones"] = ZONES["tables"]["bw_fr_rev0"]["entries"]
    identity = {
        "game_id": profile["game_id"], "game_code": profile["game_code"],
        "game_region": profile["region"], "rom_revision": profile["revision"],
    }
    return f"""
local reader = dofile({lua_literal((PROJECT / 'lua/common/gen5_tracking_reader.lua').as_posix())})
local protocol = dofile({lua_literal((PROJECT / 'lua/common/protocol.lua').as_posix())})
local profile = {lua_literal(selected)}
local identity = {lua_literal(identity)}
local ram, reads = {{}}, {{}}
local code = {lua_literal(actual_code or profile['game_code'])}
for index = 1, 4 do ram[0x027FFE0B + index] = code:byte(index) end
ram[0x027FFE1E] = {actual_revision}
if profile.map_id_address then
    ram[profile.map_id_address] = {map_id} % 256
    ram[profile.map_id_address + 1] = math.floor({map_id} / 256)
end
local memory = {{readbyte = function(address)
    reads[address] = (reads[address] or 0) + 1
    return ram[address] or 0
end}}
{before}
local result = reader.read_observation(memory, identity, profile)
{after}
return protocol.encode(result)
"""


@pytest.mark.parametrize("profile", BW, ids=lambda item: item["game_id"])
@pytest.mark.parametrize("map_id,zone,name", [
    (317, "route_1", "Route 1"), (319, "route_2", "Route 2"),
    (321, "route_3", "Route 3"), (323, "route_3", "Route 3"),
    (154, "pinwheel_forest", "Forêt d'Empoigne"),
    (155, "pinwheel_forest", "Forêt d'Empoigne"),
    (324, "wellspring_cave", "Veine Souterraine"),
    (325, "wellspring_cave", "Veine Souterraine"),
])
def test_source_documented_map_and_capture_zone(lua51, profile, map_id, zone, name):
    observed = json.loads(lua51.run(scenario(profile, map_id=map_id)))
    assert observed == {"status": "ok", "map_id": map_id,
                        "capture_zone_id": zone, "zone_name": name}


@pytest.mark.parametrize("map_id", [0, 318, 427, 65535])
def test_unsupported_map_keeps_raw_id_without_inventing_zone(lua51, map_id):
    observed = json.loads(lua51.run(scenario(BW[1], map_id=map_id)))
    assert observed == {"status": "ok", "map_id": map_id}


@pytest.mark.parametrize("profile", PROFILES, ids=lambda item: item["game_id"])
def test_no_profile_claims_a_sourced_battle_layout(profile):
    assert profile["battle"] is None
    assert set(BATTLE_FIELDS[:10]) <= set(profile["unavailable"])
    assert profile["validation"] != "real_sample_verified"
    assert profile["validation_note"] == "En attente de validation sur la machine utilisateur."


@pytest.mark.parametrize("profile", PROFILES[2:], ids=lambda item: item["game_id"])
def test_bw2_never_falls_back_to_bw_offsets(lua51, profile):
    observed = json.loads(lua51.run(scenario(profile, after="assert(next(reads) == nil)")))
    assert observed["status"] == "unsupported"
    assert "map_id" not in observed


@pytest.mark.parametrize("code,revision", [
    ("IRBF", 0), ("IREF", 0), ("IRDF", 0), ("IRAO", 0), ("IRAF", 1),
])
def test_real_header_rejects_wrong_game_language_or_revision_before_map_read(lua51, code, revision):
    observed = json.loads(lua51.run(scenario(BW[1], actual_code=code, actual_revision=revision,
        after="assert(reads[profile.map_id_address] == nil)")))
    assert observed["status"] == "unsupported"
    assert "capture_zone_id" not in observed


@pytest.mark.parametrize("field,value", [
    ("game_id", "black"), ("game_code", "IRBF"),
    ("game_region", "EN"), ("rom_revision", 1),
])
def test_stale_identity_rejected_before_any_ram_read(lua51, field, value):
    observed = json.loads(lua51.run(scenario(BW[1],
        before=f"identity.{field} = {lua_literal(value)}",
        after="assert(next(reads) == nil)")))
    assert observed["status"] == "unsupported"


def test_white_uses_its_documented_address_not_black(lua51):
    before = "ram[0x0224F88C] = 63; ram[0x0224F88D] = 1"  # Black's Route 2
    result = json.loads(lua51.run(scenario(BW[1], map_id=317, before=before,
        after="assert(reads[0x0224F88C] == nil and reads[0x0224F88D] == nil)")))
    assert result["capture_zone_id"] == "route_1"


@pytest.mark.parametrize("value", ["-1", "256", "0.5", "nil", "'317'", "0/0"])
def test_invalid_ram_byte_never_produces_zone(lua51, value):
    before = f"""
local original = memory.readbyte
memory.readbyte = function(address)
    if address == profile.map_id_address then return {value} end
    return original(address)
end
"""
    result = json.loads(lua51.run(scenario(BW[1], before=before)))
    assert result["status"] == "invalid_data"
    assert "map_id" not in result


def test_changing_map_is_discarded(lua51):
    before = """
local original = memory.readbyte
memory.readbyte = function(address)
    local value = original(address)
    if address == profile.map_id_address and reads[address] > 1 then return value + 1 end
    return value
end
"""
    result = json.loads(lua51.run(scenario(BW[1], before=before)))
    assert result["status"] == "invalid_data"
    assert "capture_zone_id" not in result


def test_enemy_buffer_never_proves_battle_capture_or_flee(lua51):
    # L'adresse PokeLua de l'ennemi est connue, pas sa durée de validité ni
    # le type de combat. Le lecteur ne doit même pas consulter ce tampon.
    after = """
for address in pairs(reads) do
    assert(address == profile.map_id_address or address == profile.map_id_address + 1
        or (address >= 0x027FFE0C and address <= 0x027FFE0F) or address == 0x027FFE1E)
end
"""
    for field in BATTLE_FIELDS:
        after += f"assert(result.{field} == nil)\n"
    observed = json.loads(lua51.run(scenario(BW[1], before="ram[0x0226AC94] = 1", after=after)))
    assert observed["map_id"] == 317


def test_zone_table_does_not_confuse_map_ids_with_pkhex_met_location_ids():
    table = ZONES["tables"]["bw_fr_rev0"]
    assert table["games"] == ["black", "white"]
    assert table["entries"]["317"]["name_location_id"] == 14
    assert table["entries"]["14"]["capture_zone_id"] == "striaton_city"
    assert table["entries"]["317"]["capture_zone_id"] == "route_1"
    for entry in table["entries"].values():
        assert entry["source_area_name"]
        assert "Gate" not in entry["source_area_name"]
