"""Validation stricte des instantanés JSON publiés par le script Lua."""

from dataclasses import dataclass
import json
import re
from typing import Any

PROTOCOL_VERSION = 1
SCRIPT_VERSION = "0.2.0"
MAX_MESSAGE_BYTES = 65_536
GAME_IDS = frozenset({"black", "black2"})
GAME_REGIONS = frozenset({"FR", "EN", "DE", "IT", "ES", "JP", "KO"})
CAPABILITIES = frozenset({"heartbeat", "game_identity", "party_size", "party_level", "party_hp", "party_species"})
EVENTS = frozenset({"hello", "heartbeat", "party_update", "bridge_error", "emulator_closing"})
MESSAGE_FIELDS = frozenset({
    "protocol_version", "session_id", "sequence", "event", "timestamp", "emulator",
    "script_version", "game_id", "game_code", "game_region", "rom_revision", "capabilities",
    "memory_profile", "party_size", "party", "error",
})
PARTY_FIELDS = frozenset({"slot", "level", "species_id", "hp", "max_hp"})


class ProtocolError(ValueError):
    """Message reçu, mais inutilisable sans deviner ses données."""


@dataclass(frozen=True)
class BridgeMessage:
    protocol_version: int
    session_id: str
    sequence: int
    event: str
    timestamp: int
    emulator: str
    script_version: str
    game_id: str | None
    game_code: str | None
    game_region: str | None
    rom_revision: int | None
    capabilities: tuple[str, ...]
    memory_profile: str | None
    party_size: int | None
    party: list[dict[str, int | None]] | None
    error: str | None


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"Clé JSON dupliquée : {key}.")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ProtocolError(f"Constante JSON interdite : {value}.")


def _integer(value: Any, name: str, minimum: int, maximum: int | None = None, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ProtocolError(f"Valeur entière invalide pour {name}.")


def _text(value: Any, name: str, maximum: int, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ProtocolError(f"Texte invalide pour {name}.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ProtocolError(f"Texte Unicode invalide pour {name}.") from exc


def _choice(value: Any, name: str, choices: frozenset[str], *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or value not in choices:
        raise ProtocolError(f"Valeur inconnue pour {name}.")


def _requires(capabilities: tuple[str, ...], capability: str, available: bool) -> None:
    if available and capability not in capabilities:
        raise ProtocolError(f"Donnée reçue sans la capacité {capability}.")


def parse_message(payload: bytes) -> BridgeMessage:
    """Décode au plus 64 Kio ; rejette types approximatifs et données ambiguës."""
    if not isinstance(payload, bytes):
        raise ProtocolError("Le message doit être fourni en octets UTF-8.")
    if not payload or len(payload) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Taille du message invalide (maximum : 65 536 octets).")
    try:
        data = json.loads(payload.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
    except ProtocolError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ProtocolError("Message JSON incomplet ou invalide.") from exc
    if not isinstance(data, dict) or set(data) != MESSAGE_FIELDS:
        raise ProtocolError("Les champs du message ne correspondent pas au protocole v1.")
    _integer(data["protocol_version"], "protocol_version", PROTOCOL_VERSION, PROTOCOL_VERSION)
    _integer(data["sequence"], "sequence", 1)
    _integer(data["timestamp"], "timestamp", 0)
    if not isinstance(data["session_id"], str) or re.fullmatch(r"[0-9a-f]{32}", data["session_id"]) is None:
        raise ProtocolError("Identifiant de session invalide.")
    _choice(data["event"], "event", EVENTS)
    if data["emulator"] != "desmume" or data["script_version"] != SCRIPT_VERSION:
        raise ProtocolError("Émulateur ou version du script incompatible.")
    _choice(data["game_id"], "game_id", GAME_IDS, nullable=True)
    _choice(data["game_region"], "game_region", GAME_REGIONS, nullable=True)
    code = data["game_code"]
    if code is not None and (not isinstance(code, str) or re.fullmatch(r"[A-Z0-9]{4}", code) is None):
        raise ProtocolError("Code du jeu invalide.")
    _integer(data["rom_revision"], "rom_revision", 0, 255, nullable=True)
    capabilities = data["capabilities"]
    if not isinstance(capabilities, list) or len(capabilities) > len(CAPABILITIES):
        raise ProtocolError("Liste des capacités invalide.")
    for capability in capabilities:
        _choice(capability, "capabilities", CAPABILITIES)
    if len(set(capabilities)) != len(capabilities):
        raise ProtocolError("Une capacité est présente plusieurs fois.")
    capabilities = tuple(capabilities)
    _text(data["memory_profile"], "memory_profile", 120, nullable=True)
    _text(data["error"], "error", 500, nullable=True)
    _integer(data["party_size"], "party_size", 0, 6, nullable=True)
    has_identity = any(data[key] is not None for key in ("game_id", "game_code", "game_region", "rom_revision"))
    _requires(capabilities, "game_identity", has_identity)
    _requires(capabilities, "party_size", data["party_size"] is not None)
    if data["party_size"] is not None or data["party"] is not None:
        if any(data[key] is None for key in ("game_id", "game_code", "game_region", "rom_revision")):
            raise ProtocolError("Une lecture d'équipe nécessite l'identité et la révision du jeu.")
        if not data["memory_profile"]:
            raise ProtocolError("Une lecture d'équipe nécessite un profil mémoire identifié.")
    party = data["party"]
    if party is not None:
        if not isinstance(party, list) or len(party) > 6 or len(party) != data["party_size"]:
            raise ProtocolError("La liste d'équipe ne correspond pas à party_size.")
        for index, pokemon in enumerate(party, start=1):
            if not isinstance(pokemon, dict) or set(pokemon) != PARTY_FIELDS:
                raise ProtocolError("Champs invalides dans un Pokémon de l'équipe.")
            _integer(pokemon["slot"], "slot", index, index)
            _integer(pokemon["level"], "level", 1, 100, nullable=True)
            _integer(pokemon["species_id"], "species_id", 1, 649, nullable=True)
            _integer(pokemon["hp"], "hp", 0, 9999, nullable=True)
            _integer(pokemon["max_hp"], "max_hp", 1, 9999, nullable=True)
            if pokemon["hp"] is not None and pokemon["max_hp"] is not None and pokemon["hp"] > pokemon["max_hp"]:
                raise ProtocolError("Les PV actuels dépassent les PV maximum.")
            _requires(capabilities, "party_level", pokemon["level"] is not None)
            _requires(capabilities, "party_species", pokemon["species_id"] is not None)
            _requires(capabilities, "party_hp", pokemon["hp"] is not None or pokemon["max_hp"] is not None)
    return BridgeMessage(**(data | {"capabilities": capabilities}))
