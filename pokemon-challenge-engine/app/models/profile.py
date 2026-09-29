"""Modèle d'un profil local et validation de son suivi manuel."""

from dataclasses import dataclass, field
import math
import re
from typing import Any

from app.models.challenge import Challenge


def default_progress() -> dict[str, Any]:
    """Retourne un suivi vierge ; aucune valeur ne provient de l'émulateur."""
    return {"badges": [], "captures": [], "deaths": [], "zones": [], "current_level_cap": None}


def validate_profile_id(profile_id: str) -> None:
    """Interdit les chemins absolus, séparateurs et traversées de dossiers."""
    if not isinstance(profile_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,95}", profile_id):
        raise ValueError("L'identifiant du profil est invalide.")


def validate_progress(progress: Any) -> dict[str, Any]:
    """Valide le format du suivi en complétant les champs encore absents."""
    if not isinstance(progress, dict):
        raise ValueError("La progression doit être un objet JSON.")
    result = default_progress() | progress
    for key in ("badges", "zones"):
        if not isinstance(result[key], list) or any(not isinstance(item, str) for item in result[key]):
            raise ValueError(f"Le champ « {key} » doit être une liste de textes.")
    for key in ("captures", "deaths"):
        if not isinstance(result[key], list) or any(not isinstance(item, dict) for item in result[key]):
            raise ValueError(f"Le champ « {key} » doit être une liste d'objets.")
    cap = result["current_level_cap"]
    if cap is not None and (type(cap) is not int or not 1 <= cap <= 100):
        raise ValueError("Le level cap courant doit être compris entre 1 et 100, ou vide.")
    validate_json_data(result)
    return result


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
