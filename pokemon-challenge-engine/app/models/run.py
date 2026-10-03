"""Persistent playthrough data. A rules snapshot never refers to a live profile."""

from copy import deepcopy
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
import math
import re
from uuid import UUID, uuid4

from app.models.challenge import Challenge
from app.models.profile import validate_json_data


RUN_SCHEMA_VERSION = 1
RUN_STATUSES = frozenset({"preparing", "active", "finished", "abandoned", "archived"})
EVENT_TYPES = frozenset({
    "run_created", "run_started", "run_resumed", "session_started", "session_ended",
    "zone_changed", "party_changed", "pokemon_fainted", "pokemon_marked_dead",
    "manual_capture", "manual_badge", "manual_death", "note_added", "status_changed",
    "backup_created", "death_corrected",
})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_run_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("L'identifiant de partie doit être un UUID.")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise ValueError("L'identifiant de partie doit être un UUID.") from None
    if str(parsed) != value:
        raise ValueError("L'identifiant de partie doit être un UUID canonique.")
    return value


def validate_timestamp(value: object, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    try:
        if not isinstance(value, str) or datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Date de partie invalide : format ISO avec fuseau attendu.") from None


def history_event(kind: str, source: str, payload: dict, timestamp: str | None = None) -> dict:
    return {"event_id": str(uuid4()), "timestamp": timestamp or utc_now(), "type": kind,
            "source": source, "payload": deepcopy(payload)}


def _text(value: object, *, nullable: bool = False, empty: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError("Texte de suivi invalide.")


def _pokemon(value: object, *, observed: bool = False, generation: int | None = None) -> None:
    if not isinstance(value, dict):
        raise ValueError("Pokémon de partie invalide.")
    species = value.get("species_id")
    if species is not None and (type(species) is not int or not 1 <= species <= (649 if generation == 5 else 65535)):
        raise ValueError("Espèce de partie invalide.")
    for key in ("name", "species_name"):
        if key in value:
            _text(value[key])
    if species is None and not (value.get("name") or value.get("species_name")):
        raise ValueError("Espèce ou nom du Pokémon manquant.")
    if observed:
        for key, lower, upper in (("species_id", 1, 65535), ("slot", 1, 6 if generation == 5 else 24), ("level", 1, 100),
                                  ("hp", 0, 65535), ("current_hp", 0, 65535), ("max_hp", 1, 65535)):
            if type(value.get(key)) is not int or not lower <= value[key] <= upper:
                raise ValueError("Pokémon observé incomplet ou invalide.")
        if value["hp"] != value["current_hp"] or value["hp"] > value["max_hp"]:
            raise ValueError("PV du Pokémon observé incohérents.")
        _text(value.get("pokemon_key"), nullable=True)
        if value.get("identity_confidence") not in ("strong", "weak") or value.get("life_status") not in ("alive", "dead", "unknown"):
            raise ValueError("Identité ou statut du Pokémon invalide.")
        if value["identity_confidence"] == "strong" and value["pokemon_key"] is None:
            raise ValueError("Identité forte sans identifiant.")
        if value["identity_confidence"] == "strong":
            from app.core.pokemon_identity import pokemon_identity
            if pokemon_identity(value, generation) != value["pokemon_key"]:
                raise ValueError("L'identité forte ne correspond pas aux identifiants documentés.")
    for key in ("personality_id", "original_trainer_id"):
        if value.get(key) is not None and (type(value[key]) is not int or not 0 <= value[key] <= 0xffffffff):
            raise ValueError("Identifiant technique Pokémon invalide.")


def _zone(value: object) -> None:
    if value is not None and not isinstance(value, (str, dict)):
        raise ValueError("Zone de partie invalide.")


@dataclass(slots=True)
class Run:
    run_id: str
    name: str
    game_id: str
    generation: int
    rules_snapshot: dict
    schema_version: int = RUN_SCHEMA_VERSION
    game_code: str | None = None
    region: str | None = None
    revision: int | None = None
    rom_fingerprint: str | None = None
    profile_id: str | None = None
    preset: str | None = None
    seed: int = 0
    created_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    last_played_at: str | None = None
    finished_at: str | None = None
    status: str = "preparing"
    save_path: str | None = None
    launch_profile: dict | None = None
    total_play_seconds: float = 0.0
    current_zone: dict | str | None = None
    current_party: list[dict] = field(default_factory=list)
    known_pokemon: dict[str, dict] = field(default_factory=dict)
    badges: int | None = None
    captures: list[dict] | None = None
    deaths: list[dict] | None = None
    pending_deaths: list[dict] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    sessions: list[dict] = field(default_factory=list)
    _storage_revision: str | None = field(default=None, init=False, repr=False, compare=False,
                                          metadata={"persist": False})

    def to_dict(self) -> dict:
        raw = {item.name: getattr(self, item.name) for item in fields(self) if item.metadata.get("persist", True)}
        validated = self.from_dict(raw)
        return {item.name: deepcopy(getattr(validated, item.name)) for item in fields(self)
                if item.metadata.get("persist", True)}

    @classmethod
    def from_dict(cls, data: object) -> "Run":
        validate_json_data(data)
        if not isinstance(data, dict) or set(data) != {item.name for item in fields(cls) if item.metadata.get("persist", True)}:
            raise ValueError("La partie contient des champs absents ou inconnus.")
        if type(data["schema_version"]) is not int or data["schema_version"] != RUN_SCHEMA_VERSION:
            raise ValueError("Version du schéma de partie non prise en charge.")
        validate_run_id(data["run_id"])
        if not isinstance(data["name"], str) or not data["name"].strip() or len(data["name"]) > 120:
            raise ValueError("Le nom de partie doit contenir entre 1 et 120 caractères.")
        if not isinstance(data["game_id"], str) or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", data["game_id"]) is None:
            raise ValueError("Jeu de partie invalide.")
        if type(data["generation"]) is not int or not 1 <= data["generation"] <= 100:
            raise ValueError("Génération de partie invalide.")
        if not isinstance(data["status"], str) or data["status"] not in RUN_STATUSES:
            raise ValueError("Statut de partie inconnu.")
        for key in ("game_code", "region", "rom_fingerprint", "profile_id", "preset", "save_path"):
            value = data[key]
            if value is not None and (not isinstance(value, str) or not value or len(value) > 32768 or "\0" in value):
                raise ValueError(f"Champ de partie invalide : {key}.")
        if data["revision"] is not None and (type(data["revision"]) is not int or not 0 <= data["revision"] <= 255):
            raise ValueError("Révision du jeu invalide.")
        if type(data["seed"]) is not int or data["seed"] < 0:
            raise ValueError("Seed de partie invalide.")
        snapshot = Challenge.from_dict(data["rules_snapshot"]).to_dict()
        if snapshot != data["rules_snapshot"] or snapshot["game_id"] != data["game_id"] or snapshot["seed"] != data["seed"]:
            raise ValueError("Le snapshot des règles ne correspond pas à la partie.")
        for key in ("created_at", "started_at", "last_played_at", "finished_at"):
            validate_timestamp(data[key], optional=key != "created_at")
        duration = data["total_play_seconds"]
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
            raise ValueError("Temps de partie invalide.")
        if data["launch_profile"] is not None and not isinstance(data["launch_profile"], dict):
            raise ValueError("Référence de lancement invalide.")
        _zone(data["current_zone"])
        if data["badges"] is not None and (type(data["badges"]) is not int or not 0 <= data["badges"] <= 99):
            raise ValueError("Nombre de badges invalide.")
        for key in ("current_party", "captures", "deaths", "notes", "history", "sessions", "pending_deaths"):
            values = data[key]
            if key in {"captures", "deaths"} and values is None:
                continue
            if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
                raise ValueError(f"Collection de partie invalide : {key}.")
        known = data["known_pokemon"]
        if not isinstance(known, dict) or any(not isinstance(key, str) or not key or not isinstance(value, dict)
                                              for key, value in known.items()):
            raise ValueError("Individus suivis invalides.")
        for pokemon in data["current_party"]:
            _pokemon(pokemon, observed=True, generation=data["generation"])
        slots = [pokemon["slot"] for pokemon in data["current_party"]]
        if len(slots) != len(set(slots)) or len(slots) > (6 if data["generation"] == 5 else 24):
            raise ValueError("Emplacements d'équipe invalides ou dupliqués.")
        for key, pokemon in known.items():
            _pokemon(pokemon, observed=True, generation=data["generation"])
            if pokemon["pokemon_key"] != key:
                raise ValueError("L'identité connue ne correspond pas à sa clé.")
            validate_timestamp(pokemon.get("first_seen_at"))
            validate_timestamp(pokemon.get("last_seen_at"))
            history = pokemon.get("species_history")
            if not isinstance(history, list) or not history:
                raise ValueError("Historique individuel d'espèces manquant.")
            for item in history:
                if not isinstance(item, dict):
                    raise ValueError("Historique individuel d'espèces invalide.")
                _pokemon(item, generation=data["generation"])
                validate_timestamp(item.get("timestamp"))
            if "identity_ambiguous" in pokemon and type(pokemon["identity_ambiguous"]) is not bool:
                raise ValueError("Statut d'ambiguïté d'identité invalide.")
            if "identity_ambiguity_reason" in pokemon:
                _text(pokemon["identity_ambiguity_reason"])
        event_ids, previous = set(), None
        for event in data["history"]:
            if set(event) != {"event_id", "timestamp", "type", "source", "payload"}:
                raise ValueError("Événement de partie incomplet.")
            validate_run_id(event["event_id"])
            validate_timestamp(event["timestamp"])
            if (event["event_id"] in event_ids or not isinstance(event["type"], str) or event["type"] not in EVENT_TYPES
                    or not isinstance(event["source"], str) or event["source"] not in {"automatic", "manual", "system"}
                    or not isinstance(event["payload"], dict)):
                raise ValueError("Événement de partie invalide ou dupliqué.")
            current = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            if previous is not None and current < previous:
                raise ValueError("L'historique de partie doit rester chronologique.")
            previous = current
            event_ids.add(event["event_id"])
        session_ids, active_count, total = set(), 0, 0.0
        for session in data["sessions"]:
            if set(session) != {"session_id", "started_at", "last_heartbeat", "ended_at", "duration"}:
                raise ValueError("Session de partie incomplète.")
            validate_run_id(session["session_id"])
            for key in ("started_at", "last_heartbeat", "ended_at"):
                validate_timestamp(session[key], optional=key == "ended_at")
            dates = [datetime.fromisoformat(session[key].replace("Z", "+00:00")) for key in
                     ("started_at", "last_heartbeat", "ended_at") if session[key] is not None]
            if dates != sorted(dates):
                raise ValueError("Chronologie de session invalide.")
            value = session["duration"]
            if session["session_id"] in session_ids or type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("Session de partie invalide.")
            session_ids.add(session["session_id"])
            total += value
            active_count += session["ended_at"] is None
        if active_count > 1 or not math.isclose(total, duration, abs_tol=0.001):
            raise ValueError("Le temps total ou le nombre de sessions actives est incohérent.")
        death_ids = set()
        for death in data["deaths"] or []:
            required = {"death_id", "pokemon_key", "pokemon", "zone", "date", "note", "source", "corrected"}
            if not required <= set(death) or not isinstance(death["pokemon"], dict) or type(death["corrected"]) is not bool:
                raise ValueError("Mort enregistrée invalide.")
            validate_run_id(death["death_id"])
            validate_timestamp(death["date"])
            _pokemon(death["pokemon"], generation=data["generation"])
            _text(death["pokemon_key"], nullable=True)
            _text(death["note"], empty=True)
            _zone(death["zone"])
            if death["death_id"] in death_ids or death["source"] not in ("automatic", "manual"):
                raise ValueError("Mort enregistrée invalide ou dupliquée.")
            death_ids.add(death["death_id"])
            if death["corrected"]:
                validate_timestamp(death.get("corrected_at"))
                _text(death.get("correction_note"), empty=True)
        review_ids = set()
        for review in data["pending_deaths"]:
            required = {"review_id", "marker", "pokemon", "reason", "zone", "timestamp"}
            if not required <= set(review):
                raise ValueError("Observation de mort à confirmer incomplète.")
            validate_run_id(review["review_id"])
            if review["review_id"] in review_ids:
                raise ValueError("Observation à confirmer dupliquée.")
            review_ids.add(review["review_id"])
            _text(review["marker"])
            _text(review["reason"])
            _pokemon(review["pokemon"], observed=True, generation=data["generation"])
            _zone(review["zone"])
            validate_timestamp(review["timestamp"])
            if "resolved" in review and type(review["resolved"]) is not bool:
                raise ValueError("Résolution de confirmation invalide.")
            if review.get("resolved", False):
                validate_run_id(review.get("death_id"))
                if review["death_id"] not in death_ids:
                    raise ValueError("La confirmation ne référence aucune mort enregistrée.")
        for capture in data["captures"] or []:
            required = {"capture_id", "pokemon", "zone", "date", "note", "source"}
            if not required <= set(capture) or capture["source"] != "manual":
                raise ValueError("Capture manuelle invalide.")
            validate_run_id(capture["capture_id"])
            _pokemon(capture["pokemon"], generation=data["generation"])
            _zone(capture["zone"])
            validate_timestamp(capture["date"])
            _text(capture["note"], empty=True)
        for note in data["notes"]:
            if not {"note_id", "text", "timestamp"} <= set(note):
                raise ValueError("Note incomplète.")
            validate_run_id(note["note_id"])
            _text(note["text"])
            validate_timestamp(note["timestamp"])
        return cls(**deepcopy(data))

    @property
    def death_count(self) -> int | None:
        return None if self.deaths is None else sum(not item["corrected"] for item in self.deaths)

    @property
    def active_rules(self) -> tuple[str, ...]:
        return tuple(self.rules_snapshot["active_rules"])
