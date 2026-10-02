"""Format sérialisable du challenge, validé avant toute utilisation."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
import math

from app.core.monotype import MONOTYPE_MODES, validate_allowed_types
from app.models.rule import RuleState


def _validate_json(value: object, location: str, depth: int = 0) -> None:
    """Interdit les objets Python arbitraires et les nombres JSON non finis."""
    if depth > 100:
        raise ValueError(f"{location} contient une structure trop profondément imbriquée.")
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError(f"{location} contient un texte Unicode invalide.") from exc
        return
    if value is None or type(value) in (int, bool):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item, location, depth + 1)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for key, item in value.items():
            _validate_json(key, location, depth + 1)
            _validate_json(item, location, depth + 1)
        return
    raise ValueError(f"{location} contient une valeur JSON invalide.")


@dataclass(slots=True)
class Challenge:
    game_id: str
    mode: str
    active_rules: list[str]
    rule_states: dict[str, str]
    settings: dict
    monotype: dict | None
    seed: int
    version: str = "0.1.0"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        # Valider avant toute copie récursive, y compris les références cycliques.
        raw = {item.name: getattr(self, item.name) for item in fields(self)}
        return asdict(self.from_dict(raw))

    @classmethod
    def from_dict(cls, data: object) -> "Challenge":
        _validate_json(data, "Le challenge")
        fields = {"game_id", "mode", "active_rules", "rule_states", "settings", "monotype", "seed", "version", "created_at"}
        if not isinstance(data, dict) or set(data) != fields:
            raise ValueError("Le challenge doit contenir exactement les champs attendus (format V0.1).")
        if not isinstance(data["game_id"], str) or not data["game_id"].strip():
            raise ValueError("Le jeu du challenge est invalide.")
        if data["mode"] not in ("normal", "custom", "random"):
            raise ValueError("Le mode du challenge est inconnu.")
        rules = data["active_rules"]
        if not isinstance(rules, list) or any(not isinstance(item, str) or not item for item in rules):
            raise ValueError("La liste des règles actives est invalide.")
        if len(rules) != len(set(rules)):
            raise ValueError("La liste des règles actives contient des doublons.")
        states = data["rule_states"]
        if not isinstance(states, dict) or any(
            not isinstance(key, str) or not key or value not in tuple(state.value for state in RuleState)
            for key, value in states.items()
        ):
            raise ValueError("Les états des règles sont invalides.")
        settings = data["settings"]
        if not isinstance(settings, dict) or settings.get("enforcement") not in ("soft", "strict"):
            raise ValueError("Le suivi global doit être souple ou strict (prévu).")
        if not isinstance(settings.get("rule_parameters"), dict):
            raise ValueError("Les paramètres des règles doivent être un objet JSON.")
        _validate_json(settings, "Les réglages")
        if type(data["seed"]) is not int or data["seed"] < 0:
            raise ValueError("La seed doit être un entier positif ou nul.")
        if data["version"] != "0.1.0":
            raise ValueError("Cette version de profil n'est pas prise en charge (attendu : 0.1.0).")
        try:
            if not isinstance(data["created_at"], str):
                raise ValueError
            created = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
            if created.tzinfo is None:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("La date de création doit être une date ISO avec fuseau horaire.") from None
        config = data["monotype"]
        if config is not None:
            expected = {"type_id", "mode", "allowed_types", "allow_reroll", "roll_index"}
            if not isinstance(config, dict) or set(config) != expected:
                raise ValueError("La configuration Monotype est incomplète ou inconnue.")
            validate_allowed_types(config["allowed_types"])
            if not isinstance(config["type_id"], str) or config["type_id"] not in config["allowed_types"]:
                raise ValueError("Le résultat Monotype doit appartenir aux types autorisés.")
            if config["mode"] not in MONOTYPE_MODES or type(config["allow_reroll"]) is not bool:
                raise ValueError("Le mode Monotype ou l'option de relance est invalide.")
            if type(config["roll_index"]) is not int or config["roll_index"] < 0:
                raise ValueError("L'index de relance Monotype est invalide.")
        normalized = deepcopy(data)
        # Compatibilité des profils historiques : leurs champs d'éditeur inactifs
        # ne deviennent pas des contraintes. La lecture ne réécrit aucun fichier.
        normalized["settings"]["rule_parameters"] = {
            rule_id: values for rule_id, values in normalized["settings"]["rule_parameters"].items()
            if rule_id in rules
        }
        if "monotype" not in rules:
            normalized["monotype"] = None
        return cls(**normalized)
