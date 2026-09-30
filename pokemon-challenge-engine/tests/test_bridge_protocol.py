"""Messages Lua simulés : validation avant toute exposition à l'interface."""

import json

import pytest

from app.bridge.protocol import MAX_MESSAGE_BYTES, ProtocolError, parse_message


def message(**changes: object) -> dict:
    return {
        "protocol_version": 1, "session_id": "a" * 32, "sequence": 1, "event": "hello",
        "timestamp": 1_790_000_000, "emulator": "desmume", "script_version": "0.2.0",
        "game_id": "black", "game_code": "IRBF", "game_region": "FR", "rom_revision": 0,
        "capabilities": ["heartbeat", "game_identity"], "memory_profile": None,
        "party_size": None, "party": None, "error": None,
    } | changes


def encoded(**changes: object) -> bytes:
    return json.dumps(message(**changes), ensure_ascii=False).encode("utf-8")


def party_message(**changes: object) -> dict:
    return message(
        event="party_update", capabilities=["heartbeat", "game_identity", "party_size", "party_level", "party_hp", "party_species"],
        memory_profile="fixture-only", party_size=1,
        party=[{"slot": 1, "level": 5, "species_id": 495, "hp": 0, "max_hp": 22}],
    ) | changes


def test_complete_hello_and_unknown_identity_are_distinct() -> None:
    hello = parse_message(encoded())
    assert hello.game_id == "black"
    assert hello.capabilities == ("heartbeat", "game_identity")
    assert hello.party_size is None
    unknown = parse_message(encoded(game_id=None, game_code=None, game_region=None, rom_revision=None))
    assert unknown.game_id is None
    assert unknown.party is None


def test_complete_party_and_count_only_messages() -> None:
    result = parse_message(json.dumps(party_message()).encode())
    assert result.party[0] == {"slot": 1, "level": 5, "species_id": 495, "hp": 0, "max_hp": 22}
    count = parse_message(encoded(party_size=0, memory_profile="fixture-only", capabilities=["game_identity", "party_size"]))
    assert count.party_size == 0
    assert count.party is None
    empty = parse_message(encoded(party_size=0, party=[], memory_profile="fixture-only", capabilities=["game_identity", "party_size"]))
    assert empty.party == []


def test_order_of_fields_is_irrelevant() -> None:
    payload = dict(reversed(list(message().items())))
    assert parse_message(json.dumps(payload).encode()) == parse_message(encoded())


@pytest.mark.parametrize("event", ["hello", "heartbeat", "party_update", "bridge_error", "emulator_closing"])
def test_every_event_is_a_complete_snapshot(event: str) -> None:
    result = parse_message(encoded(event=event, error="Émulateur fermé" if event == "bridge_error" else None))
    assert result.event == event


@pytest.mark.parametrize("payload", [
    b"", b"{", b"[]", b"null", b"\xff", b"{}", b" " * (MAX_MESSAGE_BYTES + 1),
    b'{"protocol_version":1,"protocol_version":1}',
    b'{"value":NaN}', b'{"value":Infinity}', b'{"value":-Infinity}', b"[" * 2000,
], ids=["empty", "incomplete", "array", "null", "utf8", "missing", "oversized", "duplicate", "nan", "infinity", "negative-infinity", "deep"])
def test_malformed_messages_are_rejected(payload: bytes) -> None:
    with pytest.raises(ProtocolError):
        parse_message(payload)


@pytest.mark.parametrize("field,value", [
    ("protocol_version", True), ("protocol_version", 2), ("protocol_version", 1.0),
    ("session_id", "../escape"), ("session_id", "A" * 32), ("session_id", 123),
    ("sequence", False), ("sequence", 0), ("sequence", 1.1),
    ("timestamp", -1), ("timestamp", True), ("timestamp", "now"),
    ("event", "read_memory"), ("event", []), ("emulator", "melonds"), ("script_version", "0.1.0"),
    ("game_id", "platinum"), ("game_id", {}), ("game_code", "IRBé"), ("game_code", "irbf"),
    ("game_code", "IRBFF"), ("game_code", []), ("game_region", "US"),
    ("rom_revision", -1), ("rom_revision", 256), ("rom_revision", True),
    ("capabilities", "heartbeat"), ("capabilities", ["heartbeat", "heartbeat"]),
    ("capabilities", ["write_memory"]), ("capabilities", [[]]),
    ("party_size", True), ("party_size", -1), ("party_size", 7), ("party", {}),
    ("memory_profile", 1), ("memory_profile", "a" * 121),
    ("error", "a" * 501), ("error", 5), ("error", "nul\x00byte"), ("error", "\ud800"),
])
def test_invalid_fields_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ProtocolError):
        parse_message(json.dumps(message(**{field: value})).encode())


def test_missing_extra_and_nested_duplicate_keys_are_rejected() -> None:
    missing = message()
    del missing["party"]
    with pytest.raises(ProtocolError):
        parse_message(json.dumps(missing).encode())
    with pytest.raises(ProtocolError):
        parse_message(encoded(extra="value"))
    duplicate = json.dumps(party_message()).replace('"slot": 1', '"slot": 1, "slot": 1')
    with pytest.raises(ProtocolError, match="dupliquée"):
        parse_message(duplicate.encode())


@pytest.mark.parametrize("field,value", [
    ("slot", 0), ("slot", 2), ("slot", True), ("level", 0), ("level", 101),
    ("level", True), ("species_id", 0), ("species_id", 650), ("species_id", True),
    ("hp", -1), ("hp", 10000), ("hp", 23), ("max_hp", 0), ("max_hp", 10000),
])
def test_invalid_party_values_are_rejected(field: str, value: object) -> None:
    data = party_message()
    data["party"][0][field] = value
    with pytest.raises(ProtocolError):
        parse_message(json.dumps(data).encode())


@pytest.mark.parametrize("changes", [
    {"game_id": None}, {"game_code": None}, {"game_region": None}, {"rom_revision": None},
    {"memory_profile": None}, {"memory_profile": ""}, {"party_size": 2},
    {"capabilities": ["heartbeat"]}, {"party": [{"slot": 1}]},
    {"party": [{"slot": 1, "level": 5, "species_id": 495, "hp": 1, "max_hp": 2, "secret": 1}]},
])
def test_inconsistent_party_snapshots_are_rejected(changes: dict) -> None:
    with pytest.raises(ProtocolError):
        parse_message(json.dumps(party_message(**changes)).encode())


@pytest.mark.parametrize("missing", ["party_size", "party_level", "party_species", "party_hp", "game_identity"])
def test_non_null_fields_require_their_capability(missing: str) -> None:
    data = party_message()
    data["capabilities"].remove(missing)
    with pytest.raises(ProtocolError, match="capacité"):
        parse_message(json.dumps(data).encode())


def test_unavailable_fields_remain_null() -> None:
    data = party_message(capabilities=["game_identity", "party_size"])
    data["party"][0] = {"slot": 1, "level": None, "species_id": None, "hp": None, "max_hp": None}
    assert parse_message(json.dumps(data).encode()).party[0]["level"] is None


GEN_V = (("black", "IRBF"), ("white", "IRAF"), ("black2", "IREF"), ("white2", "IRDF"))


@pytest.mark.parametrize("game,code", GEN_V)
def test_four_games_keep_protocol_v1_compatible(game, code):
    data = party_message(game_id=game, game_code=code, memory_profile=f"{game}_fr_rev0")
    parsed = parse_message(json.dumps(data).encode())
    assert parsed.protocol_version == 1 and parsed.script_version == "0.2.0"
    assert parsed.game_id == game and parsed.party[0]["hp"] == 0


@pytest.mark.parametrize("game,other_code", [(game, other_code) for game, _ in GEN_V for other, other_code in GEN_V if game != other])
def test_identifier_cannot_impersonate_other_version(game, other_code):
    with pytest.raises(ProtocolError, match="ne correspondent pas"):
        parse_message(encoded(game_id=game, game_code=other_code))
