"""Chargement strict du catalogue JSON et contrôle de ses références."""

from dataclasses import dataclass
import json
from pathlib import Path
import re

from app.core.monotype import GEN5_TYPE_IDS
from app.core.rule_engine import RuleEngine
from app.models.game import Game
from app.models.rule import Rule


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Clé JSON dupliquée : {key}.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Nombre JSON invalide : {value}.")


def _read_list(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
        # Refuser aussi les séquences Unicode isolées, impropres à Qt et UTF-8.
        json.dumps(data, ensure_ascii=False).encode("utf-8")
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise ValueError(f"Impossible de charger {path.name} : {error}") from error
    if not isinstance(data, list) or not data or any(not isinstance(row, dict) for row in data):
        raise ValueError(f"{path.name} doit contenir une liste non vide d'objets.")
    return data


def _fields(row: dict, required: set[str], context: str) -> None:
    if set(row) != required:
        missing = ", ".join(sorted(required - set(row)))
        extra = ", ".join(sorted(set(row) - required))
        raise ValueError(f"{context} : champs manquants [{missing}] ou inconnus [{extra}].")


def _text(value: object, context: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} doit être un texte non vide.")


def _identifier(value: object, context: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise ValueError(f"{context} doit être un identifiant en minuscules sans espaces.")


def _integer(value: object, low: int, high: int, context: str) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{context} doit être un entier entre {low} et {high}.")


def _strings(value: object, context: str, *, nonempty: bool = False) -> None:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{context} doit être une liste de textes{ ' non vide' if nonempty else ''}.")
    if any(not isinstance(item, str) or not item for item in value) or len(set(value)) != len(value):
        raise ValueError(f"{context} contient une valeur invalide ou un doublon.")


def _parameters(parameters: object, context: str) -> None:
    if not isinstance(parameters, dict):
        raise ValueError(f"{context} doit être un objet JSON.")
    for key, spec in parameters.items():
        _identifier(key, f"{context}.{key}")
        if not isinstance(spec, dict):
            raise ValueError(f"{context}.{key} : définition invalide.")
        _fields(spec, {"type", "label", "default", "min", "max"}, f"{context}.{key}")
        _text(spec["label"], f"{context}.{key}.label")
        if spec["type"] != "integer" or type(spec["min"]) is not int or type(spec["max"]) is not int:
            raise ValueError(f"{context}.{key} doit définir un paramètre entier borné.")
        _integer(spec["default"], spec["min"], spec["max"], f"{context}.{key}.default")


@dataclass(slots=True)
class Catalog:
    games: dict[str, Game]
    rules: dict[str, Rule]
    types: list[dict]
    presets: list[dict]

    @classmethod
    def load(cls, data_dir: Path) -> "Catalog":
        data_dir = Path(data_dir)
        games: dict[str, Game] = {}
        game_fields = {"id", "name", "generation", "platform", "type_count", "supports_monotype", "supports_desmume", "status"}
        for row in _read_list(data_dir / "games.json"):
            _fields(row, game_fields, "Jeu")
            _identifier(row["id"], "Identifiant de jeu")
            for key in ("name", "platform"):
                _text(row[key], f"Jeu {row['id']}.{key}")
            _integer(row["generation"], 1, 20, "Génération")
            _integer(row["type_count"], 1, 30, "Nombre de types")
            if any(type(row[key]) is not bool for key in ("supports_monotype", "supports_desmume")):
                raise ValueError(f"Jeu {row['id']} : les compatibilités doivent être des booléens.")
            if row["status"] not in ("supported", "planned"):
                raise ValueError(f"Jeu {row['id']} : statut inconnu.")
            if row["id"] in games:
                raise ValueError(f"Jeu dupliqué : {row['id']}.")
            games[row["id"]] = Game(**row)
        rules: dict[str, Rule] = {}
        rule_fields = {"id", "name", "description", "difficulty", "category", "requires", "conflicts_with", "supported_games", "supports_strict_mode", "supports_soft_mode", "implementation_status", "parameters"}
        for row in _read_list(data_dir / "rules.json"):
            _fields(row, rule_fields, "Règle")
            _identifier(row["id"], "Identifiant de règle")
            for key in ("name", "description", "category"):
                _text(row[key], f"Règle {row['id']}.{key}")
            _integer(row["difficulty"], 1, 5, "Difficulté")
            for key in ("requires", "conflicts_with", "supported_games"):
                _strings(row[key], f"Règle {row['id']}.{key}", nonempty=key == "supported_games")
            if any(type(row[key]) is not bool for key in ("supports_strict_mode", "supports_soft_mode")):
                raise ValueError(f"Règle {row['id']} : les modes doivent être des booléens.")
            if row["implementation_status"] not in ("ui_only", "planned", "partial", "future_strict"):
                raise ValueError(f"Règle {row['id']} : statut d'implémentation inconnu.")
            _parameters(row["parameters"], f"Paramètres de {row['id']}")
            if row["id"] in rules:
                raise ValueError(f"Règle dupliquée : {row['id']}.")
            rules[row["id"]] = Rule(**{**row, **{key: tuple(row[key]) for key in ("requires", "conflicts_with", "supported_games")}})
        cls._validate_references(games, rules)
        types = _read_list(data_dir / "types_gen5.json")
        found_types: set[str] = set()
        for row in types:
            _fields(row, {"id", "name", "color"}, "Type")
            _text(row["name"], "Nom de type")
            if not isinstance(row["id"], str) or row["id"] not in GEN5_TYPE_IDS or row["id"] in found_types:
                raise ValueError("Le catalogue des types Gen V contient un type inconnu ou dupliqué.")
            if not isinstance(row["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", row["color"]):
                raise ValueError(f"Couleur invalide pour le type {row['id']}.")
            found_types.add(row["id"])
        if found_types != set(GEN5_TYPE_IDS):
            raise ValueError("Le catalogue Gen V doit contenir exactement ses 17 types, sans Fée.")
        presets = _read_list(data_dir / "presets.json")
        preset_ids: set[str] = set()
        rule_engine = RuleEngine(rules.values())
        for row in presets:
            _fields(row, {"id", "name", "mode", "required", "count"}, "Preset")
            _identifier(row["id"], "Identifiant de preset")
            _text(row["name"], "Nom de preset")
            _strings(row["required"], "Règles de preset")
            _integer(row["count"], 0, len(rules), "Nombre de règles du preset")
            if row["mode"] not in ("normal", "custom", "random") or row["id"] in preset_ids:
                raise ValueError(f"Preset {row['id']} : mode invalide ou identifiant dupliqué.")
            if not set(row["required"]) <= rules.keys():
                raise ValueError(f"Preset {row['id']} : référence à une règle inconnue.")
            if row["count"] < len(row["required"]):
                raise ValueError(f"Preset {row['id']} : nombre inférieur aux règles obligatoires.")
            if row["mode"] == "normal" and (row["count"] or row["required"]):
                raise ValueError(f"Preset {row['id']} : une partie normale ne comporte aucune règle.")
            required_closure = rule_engine.dependency_closure(row["required"])
            if len(required_closure) > row["count"]:
                raise ValueError(f"Preset {row['id']} : le nombre ne couvre pas les dépendances obligatoires.")
            if not any(not rule_engine.validate(required_closure, game.id)
                       for game in games.values() if game.status == "supported"):
                raise ValueError(f"Preset {row['id']} : règles incompatibles avec les jeux pris en charge.")
            preset_ids.add(row["id"])
        return cls(games, rules, types, presets)

    @staticmethod
    def _validate_references(games: dict[str, Game], rules: dict[str, Rule]) -> None:
        for rule in rules.values():
            if not set(rule.supported_games) <= games.keys():
                raise ValueError(f"{rule.name} : référence à un jeu inconnu.")
            if not set(rule.requires + rule.conflicts_with) <= rules.keys():
                raise ValueError(f"{rule.name} : référence à une règle inconnue.")
            if rule.id in rule.requires or rule.id in rule.conflicts_with:
                raise ValueError(f"{rule.name} : une règle ne peut pas dépendre d'elle-même ou s'exclure.")
            if set(rule.requires) & set(rule.conflicts_with):
                raise ValueError(f"{rule.name} : une dépendance est aussi interdite.")
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(rule_id: str) -> None:
            if rule_id in visiting:
                raise ValueError(f"Cycle dans les dépendances autour de {rule_id}.")
            if rule_id in visited:
                return
            visiting.add(rule_id)
            for required in rules[rule_id].requires:
                visit(required)
            visiting.remove(rule_id)
            visited.add(rule_id)

        for rule_id in rules:
            visit(rule_id)
        engine = RuleEngine(rules.values())
        for rule in rules.values():
            closure = engine.dependency_closure([rule.id])
            for game_id in rule.supported_games:
                errors = engine.validate(closure, game_id)
                if errors:
                    raise ValueError(f"Définition incohérente de {rule.name} : {' '.join(errors)}")
