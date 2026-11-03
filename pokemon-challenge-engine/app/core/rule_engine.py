"""Explications des contraintes applicables à une sélection de règles."""

from collections.abc import Iterable

from app.models.rule import Rule


def combination_notes(selected: Iterable[str]) -> list[str]:
    """Conjunction semantics; compatibility never grants an implicit exception."""
    ids = set(selected)
    notes = []
    if {"nuzlocke", "shiny_only"} <= ids:
        notes.append("Nuzlocke + Shiny Only : seule la première rencontre admissible de la zone peut être capturée ; elle doit aussi être shiny pour combattre. Aucun droit de relance shiny ni exception implicite.")
    if {"nuzlocke", "catch_limit"} <= ids:
        notes.append("Nuzlocke + Catch Limit : les deux limites s'appliquent ; un plafond supérieur à un ne permet pas une deuxième rencontre Nuzlocke.")
    if "solo_run" in ids and ids.intersection({"nuzlocke", "catch_limit"}):
        notes.append("Solo Run + règles de capture : les captures restent possibles selon leurs limites ; seul l'individu désigné peut combattre.")
    if {"starter_only", "shiny_only"} <= ids:
        notes.append("Starter Only + Shiny Only : le starter désigné doit être shiny ; aucun remplacement ni exemption du starter n'est accordé.")
    if "monotype" in ids and ids.intersection({"shiny_only", "unevolved", "starter_only"}):
        notes.append("Monotype combiné : chaque Pokémon autorisé doit aussi respecter les autres restrictions actives ; aucune exception de type n'est ajoutée.")
    if "randomizer" in ids and ids.intersection({"monotype", "no_evolution", "unevolved"}):
        notes.append("Randomizer combiné : les contrôles utilisent les types et évolutions extraits de la ROM dérivée vérifiée ; sans ces données, le résultat reste inconnu.")
    return notes


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
