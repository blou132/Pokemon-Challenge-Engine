"""Nullable observations: unavailable readings never become inferred facts."""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any

OUTCOMES = {"captured", "fainted", "escaped", "player_fled", "battle_ended_unknown"}
KINDS = {"wild_standard", "wild_special", "static", "gift", "egg", "fossil", "scripted", "unknown"}


@dataclass(frozen=True)
class GameObservation:
    map_id: int | None = None
    capture_zone_id: str | None = None
    zone_name: str | None = None
    battle_active: bool | None = None
    battle_type: str | None = None
    encounter_kind: str | None = None
    battle_id: str | None = None
    species_id: int | None = None
    level: int | None = None
    hp: int | None = None
    max_hp: int | None = None
    encounter_slot: int | None = None
    outcome: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GameObservation":
        if not isinstance(data, dict):
            raise ValueError("Observation de jeu invalide.")
        values = {key: data.get(key) for key in cls.__dataclass_fields__}
        for key, low, high in (("map_id", 0, 65535), ("species_id", 1, 649),
                               ("level", 1, 100), ("hp", 0, 9999),
                               ("max_hp", 1, 9999), ("encounter_slot", 0, 5)):
            value = values[key]
            if value is not None and (type(value) is not int or not low <= value <= high):
                raise ValueError(f"Observation : {key} invalide.")
        for key in ("capture_zone_id", "zone_name", "battle_id"):
            value = values[key]
            if value is not None and (not isinstance(value, str) or not value or len(value) > 200):
                raise ValueError(f"Observation : {key} invalide.")
        if values["battle_active"] is not None and type(values["battle_active"]) is not bool:
            raise ValueError("Observation : battle_active invalide.")
        for key, allowed in (("battle_type", {"wild", "trainer", "double", "scripted", "unknown"}),
                             ("encounter_kind", KINDS), ("outcome", OUTCOMES)):
            if values[key] is not None and (not isinstance(values[key], str) or values[key] not in allowed):
                raise ValueError(f"Observation : {key} invalide.")
        if values["hp"] is not None and values["max_hp"] is not None and values["hp"] > values["max_hp"]:
            raise ValueError("Observation : PV supérieurs au maximum.")
        return cls(**values)


def stable_id(*parts: object) -> str:
    return sha256(json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class GameEvent:
    id: str
    event: str
    timestamp: int | None
    zone_id: str | None = None
    map_id: int | None = None
    battle_id: str | None = None
    species_id: int | None = None
    level: int | None = None
    result: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
