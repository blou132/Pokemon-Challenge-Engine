"""Coordination des règles, paramètres et choix Monotype d'un challenge."""

from collections.abc import Mapping
from copy import deepcopy
import logging

from app.core.catalog import Catalog
from app.core.monotype import GEN5_TYPE_IDS, select_type
from app.core.random_selector import RandomSelector
from app.core.rule_engine import RuleEngine
from app.models.challenge import Challenge
from app.models.rule import RuleState

logger = logging.getLogger(__name__)


class ChallengeEngine:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self.rule_engine = RuleEngine(catalog.rules.values())
        self.random_selector = RandomSelector(self.rule_engine)

    def generate(self, game_id: str, mode: str, states: Mapping[str, RuleState | str], count: int,
                 seed: int, settings: dict | None = None, monotype: dict | None = None) -> Challenge:
        game = self.catalog.games.get(game_id)
        if game is None:
            raise ValueError("Ce jeu est inconnu du catalogue.")
        if game.status != "supported":
            raise ValueError(f"{game.name} est prévu pour une version ultérieure.")
        if type(seed) is not int or seed < 0:
            raise ValueError("La seed doit être un entier positif ou nul.")
        normalized = self.random_selector.normalize_states(states)
        if mode == "normal":
            active: list[str] = []
        elif mode == "custom":
            active = sorted(self.rule_engine.dependency_closure(
                rule_id for rule_id, state in normalized.items() if state == RuleState.REQUIRED.value
            ))
            for rule_id in active:
                if normalized[rule_id] == RuleState.FORBIDDEN.value:
                    raise ValueError(f"Une règle obligatoire exige {self.catalog.rules[rule_id].name}, qui est interdite.")
        elif mode == "random":
            active = self.random_selector.select(game_id, normalized, count, seed)
        else:
            raise ValueError("Le mode de challenge est inconnu.")
        if settings is not None and not isinstance(settings, dict):
            raise ValueError("Les réglages doivent être un objet JSON.")
        final_settings = {"enforcement": "soft", "rule_parameters": {}}
        if settings is not None:
            final_settings.update(deepcopy(settings))
        if not isinstance(final_settings["rule_parameters"], dict):
            raise ValueError("Les paramètres des règles doivent être un objet JSON.")
        unknown = set(final_settings["rule_parameters"]) - self.catalog.rules.keys()
        if unknown:
            raise ValueError("Paramètres associés à une règle inconnue : " + ", ".join(sorted(unknown)))
        # Les valeurs de l'éditeur sont des brouillons. Seules les règles du
        # résultat final portent des contraintes (Possible ne signifie pas Active).
        final_settings["rule_parameters"] = {
            rule_id: values for rule_id, values in final_settings["rule_parameters"].items() if rule_id in active
        }
        for rule_id in active:
            specs = self.catalog.rules[rule_id].parameters
            if specs:
                params = final_settings["rule_parameters"].setdefault(rule_id, {})
                if not isinstance(params, dict):
                    raise ValueError(f"Paramètres invalides pour {self.catalog.rules[rule_id].name}.")
                for key, spec in specs.items():
                    params.setdefault(key, spec["default"])
        config = None
        if "monotype" in active:
            config = deepcopy(monotype) if monotype is not None else {
                "type_id": select_type(list(GEN5_TYPE_IDS), seed), "mode": "soft",
                "allowed_types": list(GEN5_TYPE_IDS), "allow_reroll": True, "roll_index": 0,
            }
        result = Challenge(game_id, mode, active, normalized, final_settings, config, seed)
        errors = self.validate(result)
        if errors:
            raise ValueError(" ".join(errors))
        logger.info("Challenge généré : jeu=%s, mode=%s, règles=%d, seed=%d", game_id, mode, len(active), seed)
        return result

    def validate(self, challenge: Challenge) -> list[str]:
        if not isinstance(challenge, Challenge):
            return ["Le challenge n'a pas le format attendu."]
        try:
            challenge.to_dict()
        except (ValueError, TypeError) as error:
            return [str(error)]
        errors: list[str] = []
        game = self.catalog.games.get(challenge.game_id)
        if game is None or game.status != "supported":
            errors.append("Le jeu du challenge n'est pas pris en charge dans cette version.")
        errors.extend(self.rule_engine.validate(challenge.active_rules, challenge.game_id))
        active = set(challenge.active_rules)
        if challenge.mode == "normal" and active:
            errors.append("Une partie normale ne peut pas contenir de règles actives.")
        for rule_id, state in challenge.rule_states.items():
            if rule_id not in self.catalog.rules:
                errors.append(f"État associé à une règle inconnue : {rule_id}.")
            elif challenge.mode != "normal":
                if state == RuleState.REQUIRED.value and rule_id not in active:
                    errors.append(f"La règle obligatoire {self.catalog.rules[rule_id].name} est absente.")
                if state == RuleState.FORBIDDEN.value and rule_id in active:
                    errors.append(f"La règle interdite {self.catalog.rules[rule_id].name} est active.")
        if challenge.mode == "custom":
            required = [rule_id for rule_id, state in challenge.rule_states.items()
                        if state == RuleState.REQUIRED.value and rule_id in self.catalog.rules]
            expected = self.rule_engine.dependency_closure(required)
            if active != expected:
                errors.append("Un challenge personnalisé doit contenir les règles obligatoires et leurs dépendances uniquement.")
        if "monotype" in active:
            if challenge.monotype is None:
                errors.append("La règle Monotype exige un type sélectionné.")
            if game is not None and not game.supports_monotype:
                errors.append("Ce jeu ne permet pas de préparer un challenge Monotype.")
        elif challenge.monotype is not None:
            errors.append("Une configuration Monotype exige la règle Monotype active.")
        for rule_id, params in challenge.settings["rule_parameters"].items():
            rule = self.catalog.rules.get(rule_id)
            if rule is None or not isinstance(params, dict):
                errors.append(f"Paramètres invalides pour la règle {rule_id}.")
                continue
            if rule_id not in active:
                continue  # Ancien brouillon inactif : supprimé à la sérialisation.
            for key, value in params.items():
                spec = rule.parameters.get(key)
                if spec is None:
                    errors.append(f"Paramètre inconnu : {rule.name}.{key}.")
                elif type(value) is not int or not spec["min"] <= value <= spec["max"]:
                    errors.append(f"{spec['label']} doit être un entier entre {spec['min']} et {spec['max']}.")
        for rule_id in active & self.catalog.rules.keys():
            if challenge.settings["enforcement"] == "soft" and not self.catalog.rules[rule_id].supports_soft_mode:
                errors.append(f"{self.catalog.rules[rule_id].name} n'est pas disponible en mode souple.")
        # Le mode strict reste une intention enregistrée, sans promettre son application.
        return errors
