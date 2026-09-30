"""Exécuter le module Lua réel sur une RAM synthétique chiffrée, sans sauvegarde.

Le moteur Lua 5.1 optionnel est fourni localement via PCE_LUA51_DLL ou le dossier
ignoré runtime/probe. Ces tests ne prouvent pas la compatibilité avec un jeu réel.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import itertools
import json
import os
import struct
from pathlib import Path

import pytest


PROJECT = Path(__file__).resolve().parents[1]
PROFILES = json.loads((PROJECT / "data/memory_profiles.json").read_text(encoding="utf-8"))
PERMUTATIONS = list(itertools.permutations(range(4)))


class Lua51:
    def __init__(self, library: str):
        self.dll = ctypes.CDLL(library)
        self.dll.luaL_newstate.restype = ctypes.c_void_p
        self.dll.luaL_openlibs.argtypes = [ctypes.c_void_p]
        self.dll.luaL_loadstring.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self.dll.luaL_loadstring.restype = ctypes.c_int
        self.dll.lua_pcall.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self.dll.lua_pcall.restype = ctypes.c_int
        self.dll.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_size_t)]
        self.dll.lua_tolstring.restype = ctypes.c_void_p
        self.dll.lua_close.argtypes = [ctypes.c_void_p]

    def run(self, script: str) -> str:
        state = self.dll.luaL_newstate()
        if not state:
            raise RuntimeError("Impossible de créer l'état Lua")
        try:
            self.dll.luaL_openlibs(state)
            status = self.dll.luaL_loadstring(state, script.encode("utf-8"))
            if status == 0:
                status = self.dll.lua_pcall(state, 0, 1, 0)
            size = ctypes.c_size_t()
            pointer = self.dll.lua_tolstring(state, -1, ctypes.byref(size))
            result = ctypes.string_at(pointer, size.value).decode("utf-8") if pointer else ""
            assert status == 0, result
            return result
        finally:
            self.dll.lua_close(state)


@pytest.fixture(scope="module")
def lua51():
    configured = os.environ.get("PCE_LUA51_DLL")
    local = PROJECT.parent / "runtime/probe/lua5.1.dll"
    library = configured or (str(local) if local.is_file() else ctypes.util.find_library("lua5.1"))
    if not library:
        pytest.skip("Lua 5.1 absent ; définir PCE_LUA51_DLL pour tester le décodeur Lua")
    return Lua51(library)


def crypt(data: bytes, seed: int) -> bytes:
    """Implémentation indépendante du flux XOR documenté, en arithmétique entière."""
    result = bytearray()
    for (value,) in struct.iter_unpack("<H", data):
        seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        result.extend(struct.pack("<H", value ^ (seed >> 16)))
    return bytes(result)


def synthetic_slot(permutation: int, *, species=501, level=5, hp=19, max_hp=21) -> bytes:
    # Le bit de poids fort vérifie le calcul exact du PID non signé dans Lua 5.1.
    pid = 0xA3000555 | (permutation << 13)
    canonical = bytearray((index * 37 + 13) % 256 for index in range(128))
    struct.pack_into("<H", canonical, 0, species)
    checksum = sum(value for (value,) in struct.iter_unpack("<H", canonical)) & 0xFFFF
    physical = b"".join(canonical[index * 32 : (index + 1) * 32]
                        for index in PERMUTATIONS[permutation % 24])
    stats = bytearray(84)
    stats[4] = level
    struct.pack_into("<HH", stats, 6, hp, max_hp)
    return struct.pack("<IHH", pid, 0, checksum) + crypt(physical, checksum) + crypt(stats, pid)


def scenario(profile, slots=(), *, count=None, code=None, revision=0, after=""):
    fields = ("game_id", "game_code", "region", "revision", "party_address",
              "party_count_address", "pokemon_size")
    literal = "{" + ",".join(f"{key}={json.dumps(profile[key])}" for key in fields) + "}"
    encoded = "{" + ",".join(json.dumps(slot.hex()) for slot in slots) + "}"
    code = code or profile["game_code"]
    return f"""
local reader = dofile({json.dumps((PROJECT / 'lua/common/gen5_reader.lua').as_posix())})
local profile = {literal}
local ram = {{}}
local code = {json.dumps(code)}
for index = 1, 4 do ram[0x027FFE0B + index] = code:byte(index) end
ram[0x027FFE1E] = {revision}
ram[profile.party_count_address] = {len(slots) if count is None else count}
for slot, hex in ipairs({encoded}) do
    for index = 1, #hex, 2 do
        ram[profile.party_address + (slot - 1) * 220 + (index - 1) / 2] =
            tonumber(hex:sub(index, index + 1), 16)
    end
end
local memory = {{readbyte = function(address) return ram[address] or 0 end}}
{after}
"""


@pytest.mark.parametrize("profile", PROFILES, ids=lambda value: value["id"])
@pytest.mark.parametrize("permutation", range(32))
def test_reads_every_pid_permutation(lua51, profile, permutation):
    script = scenario(profile, [synthetic_slot(permutation)], after="""
local result = reader.read_party(memory, profile)
assert(result.status == 'ok', result.message)
assert(result.party_size == 1 and #result.party == 1)
local pokemon = result.party[1]
return table.concat({pokemon.slot, pokemon.species_id, pokemon.level, pokemon.hp, pokemon.max_hp}, ',')
""")
    assert lua51.run(script) == "1,501,5,19,21"


@pytest.mark.parametrize("profile", PROFILES, ids=lambda value: value["id"])
def test_six_slots_with_zero_hp_and_level_100(lua51, profile):
    slots = [synthetic_slot(index, species=index + 1, level=100, hp=0) for index in range(6)]
    script = scenario(profile, slots, after="""
local result = reader.read_party(memory, profile)
assert(result.status == 'ok' and result.party_size == 6)
for index, pokemon in ipairs(result.party) do
    assert(pokemon.slot == index and pokemon.species_id == index)
    assert(pokemon.level == 100 and pokemon.hp == 0)
end
return 'ok'
""")
    assert lua51.run(script) == "ok"


@pytest.mark.parametrize("count,status", [(0, "not_ready"), (7, "invalid_data"), (255, "invalid_data")])
def test_rejects_uninitialized_or_invalid_count(lua51, count, status):
    assert lua51.run(scenario(PROFILES[0], count=count, after="""
local result = reader.read_party(memory, profile)
assert(result.party == nil and result.party_size == nil)
return result.status
""")) == status


@pytest.mark.parametrize("change", [
    {"species": 0}, {"species": 650}, {"level": 0}, {"level": 101},
    {"hp": 22}, {"max_hp": 0}, {"max_hp": 10000},
])
def test_rejects_invalid_decrypted_values(lua51, change):
    script = scenario(PROFILES[0], [synthetic_slot(7, **change)], after="""
local result = reader.read_party(memory, profile)
assert(result.party == nil)
return result.status
""")
    assert lua51.run(script) == "invalid_data"


@pytest.mark.parametrize("offset", [4, 6, 8, 57, 135])
def test_corruption_rejects_whole_party(lua51, offset):
    broken = bytearray(synthetic_slot(23))
    broken[offset] ^= 1
    script = scenario(PROFILES[1], [synthetic_slot(0), bytes(broken)], after="""
local result = reader.read_party(memory, profile)
assert(result.party == nil and result.party_size == nil)
return result.status
""")
    assert lua51.run(script) == "invalid_data"


@pytest.mark.parametrize("code,revision", [("IRBF", 1), ("IRBO", 0), ("IRAF", 0), ("IREF", 0)])
def test_profile_must_match_identity(lua51, code, revision):
    script = scenario(PROFILES[0], code=code, revision=revision, after="""
return reader.read_party(memory, profile).status
""")
    assert lua51.run(script) == "unsupported"


@pytest.mark.parametrize("profile", PROFILES, ids=lambda value: value["id"])
def test_detection_reports_actual_header(lua51, profile):
    script = scenario(profile, revision=2, after="""
local value = reader.detect(memory.readbyte)
return table.concat({value.game_id, value.game_code, value.game_region, value.rom_revision}, ',')
""")
    assert lua51.run(script) == f"{profile['game_id']},{profile['game_code']},FR,2"


@pytest.mark.parametrize("profile,other", [
    (profile, other) for profile in PROFILES for other in PROFILES
    if profile["game_id"] != other["game_id"]
], ids=lambda value: value["game_id"])
def test_foreign_profile_is_rejected_before_any_party_read(lua51, profile, other):
    # Même avec un Pokémon valide au mauvais emplacement, aucune équipe étrangère
    # ne doit être lue : seules les lectures de l'identité RAM sont autorisées.
    script = scenario(profile, [synthetic_slot(0)], code=other["game_code"], after="""
local original = memory.readbyte
local party_read = false
memory.readbyte = function(address)
    if address < 0x027FFE00 or address > 0x027FFE1F then party_read = true end
    return original(address)
end
local result = reader.read_party(memory, profile)
assert(not party_read, 'Lecture equipe interdite pour un autre jeu')
assert(result.party == nil and result.party_size == nil)
return result.status
""")
    assert lua51.run(script) == "unsupported"


@pytest.mark.parametrize("code", ["ABAF", "ABDF", "IRCF", "????"])
def test_unknown_header_never_falls_back_to_a_gen5_game(lua51, code):
    script = scenario(PROFILES[0], code=code, after="""
local result = reader.detect(memory.readbyte)
assert(result.game_id == nil)
return reader.read_party(memory, profile).status
""")
    assert lua51.run(script) == "unsupported"


def test_detection_uses_protocol_region_for_korean_game(lua51):
    script = scenario(PROFILES[1], code="IREK", after="""
local value = reader.detect(memory.readbyte)
assert(reader.read_party(memory, profile).status == 'unsupported')
return value.game_region
""")
    assert lua51.run(script) == "KO"


def test_memory_exceptions_do_not_escape(lua51):
    script = scenario(PROFILES[1], [synthetic_slot(0)], after="""
local original = memory.readbyte
memory.readbyte = function(address)
    if address == profile.party_address + 100 then error('unavailable') end
    return original(address)
end
return reader.read_party(memory, profile).status
""")
    assert lua51.run(script) == "invalid_data"


def test_count_change_during_snapshot_is_rejected(lua51):
    script = scenario(PROFILES[1], [synthetic_slot(0)], after="""
local original, reads = memory.readbyte, 0
memory.readbyte = function(address)
    if address == profile.party_count_address then
        reads = reads + 1
        if reads > 1 then return 2 end
    end
    return original(address)
end
return reader.read_party(memory, profile).status
""")
    assert lua51.run(script) == "invalid_data"


def test_profile_offsets_match_pinned_sources():
    assert [(p["game_code"], p["party_count_address"], p["party_address"]) for p in PROFILES] == [
        ("IRBF", 0x02234930, 0x02234934), ("IREF", 0x0221E408, 0x0221E40C),
        ("IRAF", 0x02234950, 0x02234954), ("IRDF", 0x0221E428, 0x0221E42C),
    ]
    assert all(p["validation"] == "source_documented" and p["revision"] == 0 for p in PROFILES)


def test_four_separate_profiles_keep_sourced_version_offsets():
    profiles = {profile["game_id"]: profile for profile in PROFILES}
    assert set(profiles) == {"black", "white", "black2", "white2"}
    assert len({profile["id"] for profile in PROFILES}) == 4
    assert len({profile["party_count_address"] for profile in PROFILES}) == 4
    assert len({profile["party_address"] for profile in PROFILES}) == 4
    for game, profile in profiles.items():
        assert profile["id"] == f"{game}_fr_rev0"
        assert profile["region"] == "FR" and profile["pokemon_size"] == 220
        assert profile["sources"] and "PokeLua ne qualifie pas" in profile["revision_note"]
    for black, white in (("black", "white"), ("black2", "white2")):
        # Le décalage +0x20 est explicite dans les branches françaises PokeLua.
        for field in ("party_count_address", "party_address"):
            assert profiles[white][field] == profiles[black][field] + 0x20
        assert len(profiles[white]["sources"]) >= 2
