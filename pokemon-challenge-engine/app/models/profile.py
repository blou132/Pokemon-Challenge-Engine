"""Modèle d'un profil local et validation de son suivi manuel."""

from dataclasses import dataclass, field
from copy import deepcopy
import math
import re
from typing import Any

from app.models.challenge import Challenge

PROGRESS_SCHEMA_VERSION = 2


def default_nuzlocke() -> dict[str, Any]:
    return {"zones": {}, "current_zone_id": None, "current_map_id": None,
            "active_encounter": None, "seen_battles": {}, "captured_species": [], "source_cursors": {}}


def default_progress() -> dict[str, Any]:
    """Retourne un suivi vierge ; aucune valeur ne provient de l'émulateur."""
    return {"badges": [], "captures": [], "deaths": [], "zones": [], "current_level_cap": None,
            "schema_version": PROGRESS_SCHEMA_VERSION, "nuzlocke": default_nuzlocke()}


def validate_profile_id(profile_id: str) -> None:
    """Interdit les chemins absolus, séparateurs et traversées de dossiers."""
    if not isinstance(profile_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,95}", profile_id):
        raise ValueError("L'identifiant du profil est invalide.")


def validate_progress(progress: Any) -> dict[str, Any]:
    """Valide le format du suivi en complétant les champs encore absents."""
    if not isinstance(progress, dict):
        raise ValueError("La progression doit être un objet JSON.")
    version = progress.get("schema_version", 1)
    if type(version) is not int or version not in (1, PROGRESS_SCHEMA_VERSION):
        raise ValueError("Version du schéma de progression non prise en charge.")
    if version == PROGRESS_SCHEMA_VERSION and "nuzlocke" not in progress:
        raise ValueError("Le schéma de progression 2 exige le suivi Nuzlocke.")
    validate_json_data(progress)
    result = default_progress() | deepcopy(progress)
    result["schema_version"] = PROGRESS_SCHEMA_VERSION
    for key in ("badges", "zones"):
        if not isinstance(result[key], list) or any(not isinstance(item, str) for item in result[key]):
            raise ValueError(f"Le champ « {key} » doit être une liste de textes.")
    for key in ("captures", "deaths"):
        if not isinstance(result[key], list) or any(not isinstance(item, dict) for item in result[key]):
            raise ValueError(f"Le champ « {key} » doit être une liste d'objets.")
    cap = result["current_level_cap"]
    if cap is not None and (type(cap) is not int or not 1 <= cap <= 100):
        raise ValueError("Le level cap courant doit être compris entre 1 et 100, ou vide.")
    _validate_nuzlocke(result["nuzlocke"])
    validate_json_data(result)
    return result


def _validate_nuzlocke(data: Any) -> None:
    if not isinstance(data, dict) or set(data) != set(default_nuzlocke()):
        raise ValueError("Le suivi Nuzlocke est incomplet ou invalide.")
    if data["current_zone_id"] is not None and (not isinstance(data["current_zone_id"], str) or not data["current_zone_id"]):
        raise ValueError("Zone Nuzlocke invalide.")
    value = data["current_map_id"]
    if value is not None and (type(value) is not int or not 0 <= value <= 65535):
        raise ValueError("Carte Nuzlocke invalide.")
    if not isinstance(data["zones"], dict) or not isinstance(data["seen_battles"], dict):
        raise ValueError("Zones ou rencontres Nuzlocke invalides.")
    outcomes = {"captured", "fainted", "escaped", "player_fled", "battle_ended_unknown",
                "duplicate_ignored", "invalid_encounter", "special_encounter_ignored", "zone_already_used"}
    for key, result in data["seen_battles"].items():
        if not isinstance(key, str) or not key or not isinstance(result, str) or result not in outcomes:
            raise ValueError("Résultat Nuzlocke invalide.")
    for zone_id, zone in data["zones"].items():
        if not isinstance(zone_id, str) or not zone_id or not isinstance(zone, dict):
            raise ValueError("Zone Nuzlocke invalide.")
        if set(zone) != {"name", "used", "status", "first_encounter", "last_ignored"}:
            raise ValueError("État de zone Nuzlocke incomplet.")
        if zone["name"] is not None and not isinstance(zone["name"], str):
            raise ValueError("Nom de zone Nuzlocke invalide.")
        if type(zone["used"]) is not bool or not isinstance(zone["status"], str) or zone["status"] not in {"unused", "encounter_started", "captured", "failed", "ignored_by_clause"}:
            raise ValueError("Statut de zone Nuzlocke invalide.")
        _validate_encounter(zone["first_encounter"], outcomes)
        _validate_encounter(zone["last_ignored"], outcomes)
        encounter = zone["first_encounter"]
        if zone["used"] != (zone["status"] in {"captured", "failed"}):
            raise ValueError("Statut et consommation de zone incohérents.")
        if zone["status"] in {"captured", "failed", "encounter_started"} and encounter is None:
            raise ValueError("Première rencontre manquante.")
        if encounter is not None and encounter["zone_id"] != zone_id:
            raise ValueError("Zone de rencontre incohérente.")
        if encounter is not None:
            result = encounter["result"]
            if ((zone["status"] == "captured" and result != "captured")
                    or (zone["status"] == "failed" and result not in {"fainted", "escaped", "player_fled", "battle_ended_unknown"})
                    or (zone["status"] == "encounter_started" and result is not None)
                    or zone["status"] in {"unused", "ignored_by_clause"}):
                raise ValueError("Résultat et statut de zone incohérents.")
    _validate_encounter(data["active_encounter"], outcomes)
    active = data["active_encounter"]
    if active is not None:
        zone = data["zones"].get(active["zone_id"])
        if zone is None or zone["status"] != "encounter_started" or zone["first_encounter"] != active:
            raise ValueError("Rencontre active incohérente.")
    started = [zone for zone in data["zones"].values() if zone["status"] == "encounter_started"]
    if len(started) != (1 if active is not None else 0):
        raise ValueError("Nombre de rencontres actives incohérent.")
    species = data["captured_species"]
    if not isinstance(species, list) or any(type(item) is not int or not 1 <= item <= 649 for item in species):
        raise ValueError("Espèces capturées invalides.")
    cursors = data["source_cursors"]
    if not isinstance(cursors, dict) or any(not key or type(value) is not int or value < 0 for key, value in cursors.items()):
        raise ValueError("Curseurs Nuzlocke invalides.")


def _validate_encounter(value: Any, outcomes: set[str]) -> None:
    if value is None:
        return
    expected = {"id", "battle_id", "zone_id", "species_id", "level", "result", "timestamp"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("Rencontre Nuzlocke invalide.")
    for key in ("id", "battle_id", "zone_id"):
        if not isinstance(value[key], str) or not value[key]:
            raise ValueError("Identité de rencontre Nuzlocke invalide.")
    if type(value["species_id"]) is not int or not 1 <= value["species_id"] <= 649:
        raise ValueError("Espèce de rencontre Nuzlocke invalide.")
    if value["level"] is not None and (type(value["level"]) is not int or not 1 <= value["level"] <= 100):
        raise ValueError("Niveau de rencontre Nuzlocke invalide.")
    if value["result"] is not None and (not isinstance(value["result"], str) or value["result"] not in outcomes):
        raise ValueError("Résultat de rencontre Nuzlocke invalide.")
    if value["timestamp"] is not None and (type(value["timestamp"]) is not int or value["timestamp"] < 0):
        raise ValueError("Date de rencontre Nuzlocke invalide.")


def validate_history(history: Any) -> list[dict[str, Any]]:
    """Réserve une liste d'événements structurés pour les versions suivantes."""
    if not isinstance(history, list) or any(not isinstance(item, dict) for item in history):
        raise ValueError("L'historique doit être une liste d'objets JSON.")
    validate_json_data(history)
    return history


def validate_json_data(value: Any, depth: int = 0) -> None:
    """Borne l'imbrication et rejette les textes Unicode non encodables en UTF-8."""
    if depth > 100:
        raise ValueError("Le profil contient une structure JSON trop profondément imbriquée.")
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("Le profil contient un texte Unicode invalide.") from exc
        return
    if value is None or type(value) in (int, bool):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            validate_json_data(item, depth + 1)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for key, item in value.items():
            validate_json_data(key, depth + 1)
            validate_json_data(item, depth + 1)
        return
    raise ValueError("Le profil contient des données non sérialisables en JSON.")


@dataclass
class Profile:
    """Challenge sauvegardé et données de progression locales indépendantes."""

    id: str
    name: str
    challenge: Challenge
    progress: dict[str, Any] = field(default_factory=default_progress)
    history: list[dict[str, Any]] = field(default_factory=list)

    def validate(self) -> None:
        validate_profile_id(self.id)
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 100:
            raise ValueError("Le nom du profil doit contenir entre 1 et 100 caractères.")
        validate_json_data(self.name)
        if not isinstance(self.challenge, Challenge):
            raise ValueError("Le challenge du profil est invalide.")
        try:
            Challenge.from_dict(self.challenge.to_dict())
        except (TypeError, RecursionError) as exc:
            raise ValueError("Le challenge contient une structure invalide ou trop profondément imbriquée.") from exc
        validate_progress(self.progress)
        validate_history(self.history)
