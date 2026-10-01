"""Validation stricte des instantanés JSON publiés par le script Lua."""

from dataclasses import dataclass
import json
import re
from typing import Any

from app.core.game_detector import GAME_CODE_PREFIXES

PROTOCOL_VERSION = 2
SCRIPT_VERSION = "0.3.0"
MAX_MESSAGE_BYTES = 65_536
GAME_IDS = frozenset(GAME_CODE_PREFIXES.values())
GAME_REGIONS = frozenset({"FR", "EN", "DE", "IT", "ES", "JP", "KO"})
CAPABILITIES = frozenset({"heartbeat", "game_identity", "party_size", "party_level", "party_hp", "party_species", "tracking"})
EVENTS = frozenset({"hello", "heartbeat", "party_update", "bridge_error", "emulator_closing"})
MESSAGE_FIELDS = frozenset({
    "protocol_version", "session_id", "sequence", "event", "timestamp", "emulator",
    "script_version", "game_id", "game_code", "game_region", "rom_revision", "capabilities",
    "memory_profile", "party_size", "party", "error",
})
PARTY_FIELDS = frozenset({"slot", "level", "species_id", "hp", "max_hp"})
OBSERVATION_FIELDS = frozenset({
    "map_id", "capture_zone_id", "zone_name", "battle_active", "battle_type",
    "encounter_kind", "battle_id", "species_id", "level", "hp", "max_hp",
    "encounter_slot", "outcome", "wild_encounter", "encounter_started",
    "encounter_ended", "capture_detected", "capture_success", "fainted_wild", "fled",
})


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
    observation: dict[str, Any] | None = None


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


def validate_observation(value: Any) -> None:
    """Les inconnues restent null ; aucune conclusion n'est inférée ici."""
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != OBSERVATION_FIELDS:
        raise ProtocolError("Champs invalides dans l'observation de jeu.")
    for key, maximum in (("map_id", 65535), ("species_id", 649), ("level", 100),
                         ("hp", 9999), ("max_hp", 9999), ("encounter_slot", 5)):
        _integer(value[key], key, 1 if key in {"species_id", "level", "max_hp"} else 0,
                 maximum, nullable=True)
    for key in ("capture_zone_id", "zone_name", "battle_id"):
        _text(value[key], key, 160, nullable=True)
        if value[key] == "":
            raise ProtocolError(f"Identifiant vide pour {key}.")
    for key in ("battle_active", "wild_encounter", "encounter_started", "encounter_ended",
                "capture_detected", "capture_success", "fainted_wild"):
        if value[key] is not None and type(value[key]) is not bool:
            raise ProtocolError(f"Booléen invalide pour {key}.")
    _choice(value["battle_type"], "battle_type", frozenset({"wild", "trainer", "double", "scripted", "unknown"}), nullable=True)
    _choice(value["encounter_kind"], "encounter_kind", frozenset({"wild_standard", "wild_special", "static", "gift", "egg", "fossil", "scripted", "unknown"}), nullable=True)
    _choice(value["outcome"], "outcome", frozenset({"captured", "fainted", "escaped", "player_fled", "battle_ended_unknown"}), nullable=True)
    _choice(value["fled"], "fled", frozenset({"player", "wild", "unknown"}), nullable=True)
    if value["hp"] is not None and value["max_hp"] is not None and value["hp"] > value["max_hp"]:
        raise ProtocolError("Les PV sauvages dépassent leur maximum.")
    if value["capture_success"] is True and value["capture_detected"] is not True:
        raise ProtocolError("Capture réussie sans capture détectée.")
    if value["outcome"] == "captured" and value["capture_success"] is not True:
        raise ProtocolError("Résultat de capture sans preuve de réussite.")
    if value["battle_type"] in {"trainer", "double", "scripted"} and value["wild_encounter"] is True:
        raise ProtocolError("Classification de combat contradictoire.")


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
    if not isinstance(data, dict):
        raise ProtocolError("Le message doit être un objet JSON.")
    version = data.get("protocol_version")
    _integer(version, "protocol_version", 1, PROTOCOL_VERSION)
    expected_fields = MESSAGE_FIELDS | {"observation"} if version == 2 else MESSAGE_FIELDS
    if set(data) != expected_fields:
        raise ProtocolError(f"Les champs du message ne correspondent pas au protocole v{version}.")
    _integer(data["sequence"], "sequence", 1)
    _integer(data["timestamp"], "timestamp", 0)
    if not isinstance(data["session_id"], str) or re.fullmatch(r"[0-9a-f]{32}", data["session_id"]) is None:
        raise ProtocolError("Identifiant de session invalide.")
    _choice(data["event"], "event", EVENTS)
    expected_script = "0.2.0" if version == 1 else SCRIPT_VERSION
    if data["emulator"] != "desmume" or data["script_version"] != expected_script:
        raise ProtocolError("Émulateur ou version du script incompatible.")
    _choice(data["game_id"], "game_id", GAME_IDS, nullable=True)
    _choice(data["game_region"], "game_region", GAME_REGIONS, nullable=True)
    code = data["game_code"]
    if code is not None and (not isinstance(code, str) or re.fullmatch(r"[A-Z0-9]{4}", code) is None):
        raise ProtocolError("Code du jeu invalide.")
    if code is not None and data["game_id"] is not None and GAME_CODE_PREFIXES.get(code[:3]) != data["game_id"]:
        raise ProtocolError("Le code ROM et l'identifiant du jeu ne correspondent pas.")
    _integer(data["rom_revision"], "rom_revision", 0, 255, nullable=True)
    capabilities = data["capabilities"]
    if not isinstance(capabilities, list) or len(capabilities) > len(CAPABILITIES):
        raise ProtocolError("Liste des capacités invalide.")
    for capability in capabilities:
        _choice(capability, "capabilities", CAPABILITIES)
    if len(set(capabilities)) != len(capabilities):
        raise ProtocolError("Une capacité est présente plusieurs fois.")
    capabilities = tuple(capabilities)
    if version == 1 and "tracking" in capabilities:
        raise ProtocolError("Le suivi nécessite le protocole v2.")
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
    observation = data.get("observation")
    validate_observation(observation)
    if observation is not None:
        _requires(capabilities, "tracking", True)
        if any(data[key] is None for key in ("game_id", "game_code", "game_region", "rom_revision")):
            raise ProtocolError("Une observation nécessite l'identité complète du jeu.")
    return BridgeMessage(**(data | {"capabilities": capabilities}))
