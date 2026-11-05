"""Read-only melonDS 1.1 PCE frame adapter; no process-memory or debug access.

The native producer copies documented RAM ranges after RunFrame on the emulation
thread. This consumer validates identity and PK5 checksums before publishing the
existing PCE protocol. A heartbeat never grants party-reading capabilities.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
import re
import struct

from app.bridge.protocol import MAX_MESSAGE_BYTES, OBSERVATION_FIELDS, SCRIPT_VERSION, parse_message
from app.core.game_detector import GAME_CODE_PREFIXES

BRIDGE_VERSION = "1.1-pce.1"
UPSTREAM_REVISION = "b86390e4428bf38ce4c1ce0e9ca446d6d25955e8"
RESOURCE_DIR = Path(__file__).resolve().parents[2]
_PERMUTATIONS = tuple(itertools.permutations(range(4)))
_FRAME_FIELDS = frozenset({
    "bridge_version", "source_revision", "session_id", "sequence", "timestamp",
    "console_type", "rom_code", "rom_revision", "ram_code", "ram_revision",
    "memory_profile", "party_count", "party_hex", "map_id", "status",
})
_REGIONS = {"F": "FR", "O": "EN", "E": "EN", "P": "EN", "D": "DE", "I": "IT", "J": "JP", "K": "KO", "S": "ES"}


def _decrypt(raw: bytes, seed: int) -> bytes:
    words = []
    for (word,) in struct.iter_unpack("<H", raw):
        seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        words.append(word ^ (seed >> 16))
    return struct.pack(f"<{len(words)}H", *words)


def decode_pk5(raw: bytes, slot: int) -> dict[str, int]:
    """Decode one encrypted 220-byte party record, matching the audited Lua reader."""
    if len(raw) != 220 or type(slot) is not int or not 1 <= slot <= 6:
        raise ValueError("Structure Pokémon ou emplacement invalide.")
    pid, sanity, checksum = struct.unpack_from("<IHH", raw)
    if sanity:
        raise ValueError("Structure Pokémon transitoire ou invalide.")
    physical = _decrypt(raw[8:136], checksum)
    if sum(word for (word,) in struct.iter_unpack("<H", physical)) & 0xFFFF != checksum:
        raise ValueError("Checksum Pokémon invalide.")
    permutation = _PERMUTATIONS[((pid >> 13) & 31) % 24]
    growth = permutation.index(0) * 32
    attacks = permutation.index(1) * 32
    species = struct.unpack_from("<H", physical, growth)[0]
    trainer_id = struct.unpack_from("<I", physical, growth + 4)[0]
    form = physical[attacks + 0x18] >> 3
    stats = _decrypt(raw[136:], pid)
    level = stats[4]
    hp, maximum = struct.unpack_from("<HH", stats, 6)
    if not (1 <= species <= 649 and 1 <= level <= 100 and 1 <= maximum <= 9999 and hp <= maximum):
        raise ValueError("Valeurs Pokémon incohérentes.")
    return {"slot": slot, "species_id": species, "level": level, "hp": hp, "max_hp": maximum,
            "personality_id": pid, "original_trainer_id": trainer_id, "form": form}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Champ dupliqué dans l'instantané melonDS.")
        result[key] = value
    return result


def _integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


class MelonDSBridgeReader:
    """Consume one session's atomic native frames from the existing bridge worker."""

    def __init__(self, session_dir: Path, session_id: str, expected_code: str,
                 expected_revision: int, *, resource_dir: Path = RESOURCE_DIR) -> None:
        if not isinstance(session_id, str) or re.fullmatch(r"[0-9a-f]{32}", session_id) is None:
            raise ValueError("Identifiant de session melonDS invalide.")
        if not isinstance(expected_code, str) or re.fullmatch(r"[A-Z0-9]{4}", expected_code) is None:
            raise ValueError("Code de ROM melonDS invalide.")
        if not _integer(expected_revision, 0, 255):
            raise ValueError("Révision de ROM melonDS invalide.")
        self.session_dir = Path(session_dir)
        self.session_id = session_id
        self.expected_code = expected_code
        self.expected_revision = expected_revision
        self.sequence = 0
        self._last_snapshot: Path | None = None
        self._last_observation: dict | None = None
        resource_dir = Path(resource_dir)
        self.profiles = json.loads((resource_dir / "data/memory_profiles.json").read_text(encoding="utf-8"))
        self.tracking_profiles = json.loads((resource_dir / "data/tracking_profiles.json").read_text(encoding="utf-8"))
        self.zones = json.loads((resource_dir / "data/capture_zones.json").read_text(encoding="utf-8"))["tables"]

    def _message(self, frame: dict) -> dict:
        if not isinstance(frame, dict) or set(frame) != _FRAME_FIELDS:
            raise ValueError("Format d'instantané melonDS invalide.")
        if frame["bridge_version"] != BRIDGE_VERSION or frame["source_revision"] != UPSTREAM_REVISION:
            raise ValueError("Version de la passerelle melonDS incompatible.")
        if frame["session_id"] != self.session_id:
            raise ValueError("Instantané melonDS d'une autre session.")
        if not _integer(frame["sequence"], 1, 2**53 - 1) or not _integer(frame["timestamp"], 0, 2**53 - 1):
            raise ValueError("Séquence ou date melonDS invalide.")
        if type(frame["console_type"]) is not int or frame["console_type"] != 0:
            raise ValueError("Le suivi melonDS nécessite le mode Nintendo DS.")
        code, revision = frame["rom_code"], frame["rom_revision"]
        if code != self.expected_code or not _integer(revision, 0, 255) or revision != self.expected_revision:
            raise ValueError("La cartouche melonDS ne correspond pas à la ROM de cette partie.")
        if frame["ram_code"] != code or frame["ram_revision"] != revision or type(frame["ram_revision"]) is not int:
            raise ValueError("L'en-tête RAM melonDS ne correspond pas à la cartouche.")
        game_id = GAME_CODE_PREFIXES.get(code[:3])
        region = _REGIONS.get(code[3])
        if game_id is None or region is None:
            raise ValueError("Jeu ou région melonDS non pris en charge.")
        profile = next((item for item in self.profiles if
                        (item["game_code"], item["revision"], item["game_id"], item["region"]) ==
                        (code, revision, game_id, region)), None)
        if frame["memory_profile"] != (profile["id"] if profile else None):
            raise ValueError("Profil mémoire melonDS incompatible avec la cartouche.")
        if not isinstance(frame["status"], str) or frame["status"] not in {"ok", "not_ready", "unsupported", "invalid_data"}:
            raise ValueError("État de lecture melonDS invalide.")
        message = {
            "protocol_version": 2, "session_id": self.session_id, "sequence": frame["sequence"],
            "event": "heartbeat", "timestamp": frame["timestamp"], "emulator": "melonds",
            "script_version": SCRIPT_VERSION, "game_id": game_id, "game_code": code,
            "game_region": region, "rom_revision": revision, "capabilities": ["heartbeat", "game_identity"],
            "memory_profile": frame["memory_profile"], "party_size": None, "party": None,
            "observation": None, "error": None,
        }
        if frame["status"] != "ok":
            if frame["party_hex"] is not None or frame["map_id"] is not None:
                raise ValueError("Données présentes sans lecture melonDS validée.")
            count = frame["party_count"]
            valid_count = (frame["status"] == "unsupported" and count is None) or (
                frame["status"] == "not_ready" and type(count) is int and count == 0
            ) or (frame["status"] == "invalid_data" and _integer(count, 7, 255))
            if not valid_count:
                raise ValueError("État d'équipe melonDS incohérent.")
            if frame["status"] == "invalid_data":
                message.update(event="bridge_error", error="Données Pokémon transitoires ou incohérentes.")
            return message
        count, encoded = frame["party_count"], frame["party_hex"]
        if profile is None or profile["pokemon_size"] != 220 or not _integer(count, 1, 6):
            raise ValueError("Taille d'équipe melonDS incohérente.")
        if not isinstance(encoded, str) or len(encoded) != count * 440 or re.fullmatch(r"[0-9a-f]+", encoded) is None:
            raise ValueError("Données d'équipe melonDS incomplètes.")
        raw = bytes.fromhex(encoded)
        party = [decode_pk5(raw[index * 220:(index + 1) * 220], index + 1) for index in range(count)]
        message.update(event="party_update", party_size=count, party=party)
        message["capabilities"] += ["party_size", "party_level", "party_hp", "party_species", "party_identity", "party_form"]
        tracking = next((item for item in self.tracking_profiles if
                         (item["game_code"], item["revision"]) == (code, revision)), None)
        map_id = frame["map_id"]
        if map_id is not None:
            if (tracking is None or tracking["map_id_address"] is None or tracking["map_id_size"] != 2
                    or not _integer(map_id, 0, 65535)):
                raise ValueError("Carte melonDS fournie sans profil documenté.")
            observation = dict.fromkeys(OBSERVATION_FIELDS)
            observation["map_id"] = map_id
            zone = self.zones.get(tracking["capture_zone_table"], {}).get("entries", {}).get(str(map_id))
            if zone:
                observation.update(capture_zone_id=zone["capture_zone_id"], zone_name=zone["zone_name"])
            message["observation"] = observation
            message["capabilities"].append("tracking")
        return message

    def poll(self) -> bool:
        """Publish only fresh, validated frames; a stale producer times out normally.

        ValueError/OSError are intentionally surfaced to the controller. No corrupt
        sample is silently replaced with a previous party or fabricated heartbeat.
        """
        if (self.session_dir / "stop").exists():
            return False
        try:
            with (self.session_dir / "melonds-frame.json").open("rb") as handle:
                raw = handle.read(MAX_MESSAGE_BYTES + 1)
        except FileNotFoundError:
            return False
        if len(raw) > MAX_MESSAGE_BYTES:
            raise ValueError("Instantané melonDS trop volumineux.")
        frame = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        message = self._message(frame)
        if message["sequence"] <= self.sequence:
            return False
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        parse_message(payload)
        observation = message["observation"]
        if observation is not None and observation != self._last_observation:
            if sum(1 for _ in self.session_dir.glob("observation-*.json")) >= 256:
                raise ValueError("Journal d'observations plein ; suivi suspendu sans perte des événements.")
            self._atomic_write(self.session_dir / f"observation-{message['sequence']:010d}.json", payload)
        snapshot = self.session_dir / f"snapshot-{message['sequence']}.json"
        self._atomic_write(snapshot, payload)
        previous = self._last_snapshot
        self.sequence = message["sequence"]
        self._last_observation = observation
        self._last_snapshot = snapshot
        if previous is not None and previous != snapshot:
            previous.unlink(missing_ok=True)
        return True

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
