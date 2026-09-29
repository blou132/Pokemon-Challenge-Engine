"""Explications des contraintes applicables à une sélection de règles."""

from collections.abc import Iterable

from app.models.rule import Rule


class RuleEngine:
    def __init__(self, rules: Iterable[Rule]):
        items = list(rules)
        self.rules = {rule.id: rule for rule in items}
        if len(self.rules) != len(items):
            raise ValueError("Le moteur a reçu des identifiants de règles dupliqués.")

    def available(self, game_id: str) -> list[Rule]:
        return [rule for rule in self.rules.values() if game_id in rule.supported_games]

    def validate(self, selected: Iterable[str], game_id: str) -> list[str]:
        selection = list(selected)
        if any(not isinstance(item, str) for item in selection):
            return ["La sélection contient un identifiant de règle invalide."]
        ids = set(selection)
        errors: list[str] = []
        if len(ids) != len(selection):
            errors.append("Une règle ne peut pas être sélectionnée plusieurs fois.")
        reported_conflicts: set[tuple[str, str]] = set()
        for rule_id in sorted(ids):
            rule = self.rules.get(rule_id)
            if rule is None:
                errors.append(f"Règle inconnue : {rule_id}.")
                continue
            if game_id not in rule.supported_games:
                errors.append(f"{rule.name} n'est pas disponible pour le jeu {game_id}.")
            for required in rule.requires:
                if required not in ids:
                    label = self.rules[required].name if required in self.rules else required
                    errors.append(f"{rule.name} exige la règle {label}.")
            for other in rule.conflicts_with:
                pair = tuple(sorted((rule_id, other)))
                if other in ids and pair not in reported_conflicts:
                    label = self.rules[other].name if other in self.rules else other
                    errors.append(f"{rule.name} est incompatible avec {label}.")
                    reported_conflicts.add(pair)
        return errors

    def dependency_closure(self, selected: Iterable[str]) -> set[str]:
        pending = list(selected)
        result: set[str] = set()
        while pending:
            rule_id = pending.pop()
            if rule_id in result:
                continue
            if rule_id not in self.rules:
                raise ValueError(f"Règle inconnue : {rule_id}.")
            result.add(rule_id)
            pending.extend(self.rules[rule_id].requires)
        return result
