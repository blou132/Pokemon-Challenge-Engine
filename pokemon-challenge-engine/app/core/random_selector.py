"""Sélection exacte parmi les combinaisons compatibles, sans boucle de relance."""

from collections.abc import Mapping
from functools import lru_cache
import random

from app.core.rule_engine import RuleEngine
from app.models.rule import RuleState


class RandomSelector:
    # Une erreur explicite remplace une attente indéfinie si le catalogue grandit trop.
    SEARCH_NODE_LIMIT = 250_000

    def __init__(self, engine: RuleEngine):
        self.engine = engine
        self._ids = tuple(sorted(engine.rules))
        self._index = {rule_id: index for index, rule_id in enumerate(self._ids)}
        self._closures = tuple(self._mask(engine.dependency_closure([rule_id])) for rule_id in self._ids)
        conflicts = [0] * len(self._ids)
        for rule_id, rule in engine.rules.items():
            for other in rule.conflicts_with:
                if other not in self._index:
                    raise ValueError(f"{rule.name} référence une règle inconnue : {other}.")
                conflicts[self._index[rule_id]] |= 1 << self._index[other]
                conflicts[self._index[other]] |= 1 << self._index[rule_id]
        self._conflicts = tuple(conflicts)
        # Le cache appartient à cette instance; il ne conserve pas d'anciens catalogues.
        self._cached_solutions = lru_cache(maxsize=16)(self._solve)

    def _mask(self, ids: set[str]) -> int:
        return sum(1 << self._index[rule_id] for rule_id in ids)

    def normalize_states(self, states: Mapping[str, RuleState | str]) -> dict[str, str]:
        if not isinstance(states, Mapping):
            raise ValueError("Les états des règles doivent former un dictionnaire.")
        for key in states:
            if key not in self.engine.rules:
                raise ValueError(f"État associé à une règle inconnue : {key}.")
        result: dict[str, str] = {}
        for rule_id in self._ids:
            try:
                result[rule_id] = RuleState(states.get(rule_id, RuleState.POSSIBLE)).value
            except (ValueError, TypeError):
                raise ValueError(f"État invalide pour la règle {rule_id}.") from None
        return result

    def _solutions(self, game_id: str, states: Mapping[str, RuleState | str]) -> tuple[tuple[int, tuple[int, ...]], ...]:
        normalized = self.normalize_states(states)
        return self._cached_solutions(game_id, tuple(normalized[rule_id] for rule_id in self._ids))

    def _solve(self, game_id: str, states: tuple[str, ...]) -> tuple[tuple[int, tuple[int, ...]], ...]:
        available = {rule.id for rule in self.engine.available(game_id)}
        if not available:
            raise ValueError(f"Aucune règle du catalogue n'est disponible pour le jeu {game_id}.")
        required = {rule_id for rule_id, state in zip(self._ids, states) if state == RuleState.REQUIRED.value}
        selected_ids = self.engine.dependency_closure(required)
        forbidden = {rule_id for rule_id, state in zip(self._ids, states) if state == RuleState.FORBIDDEN.value}
        blocked = selected_ids & forbidden
        if blocked:
            labels = ", ".join(self.engine.rules[rule_id].name for rule_id in sorted(blocked))
            raise ValueError(f"Une règle obligatoire exige une règle interdite : {labels}.")
        errors = self.engine.validate(selected_ids, game_id)
        if errors:
            raise ValueError(" ".join(errors))
        all_mask = (1 << len(self._ids)) - 1
        selected = self._mask(selected_ids)
        excluded = self._mask(forbidden | (set(self._ids) - available))
        solutions: dict[int, list[int]] = {}
        nodes = 0

        def incompatible(mask: int) -> int:
            conflict_mask = 0
            pending = mask
            while pending:
                bit = pending & -pending
                conflict_mask |= self._conflicts[bit.bit_length() - 1]
                pending ^= bit
            return conflict_mask

        def visit(chosen: int, removed: int) -> None:
            nonlocal nodes
            nodes += 1
            if nodes > self.SEARCH_NODE_LIMIT:
                raise ValueError("La configuration contient trop de combinaisons. Interdisez quelques règles pour réduire le tirage.")
            removed |= incompatible(chosen)
            if chosen & removed:
                return
            undecided = all_mask & ~(chosen | removed)
            if not undecided:
                solutions.setdefault(chosen.bit_count(), []).append(chosen)
                return
            bit = undecided & -undecided
            visit(chosen, removed | bit)
            additions = self._closures[bit.bit_length() - 1]
            if not additions & removed:
                visit(chosen | additions, removed)

        visit(selected, excluded)
        if not solutions:
            raise ValueError("Aucune combinaison ne respecte ces règles obligatoires et interdites.")
        return tuple((count, tuple(masks)) for count, masks in sorted(solutions.items()))

    def feasible_counts(self, game_id: str, states: Mapping[str, RuleState | str]) -> list[int]:
        return [count for count, _ in self._solutions(game_id, states)]

    def max_count(self, game_id: str, states: Mapping[str, RuleState | str]) -> int:
        return self.feasible_counts(game_id, states)[-1]

    def select(self, game_id: str, states: Mapping[str, RuleState | str], count: int, seed: int) -> list[str]:
        if type(count) is not int or count < 0:
            raise ValueError("Le nombre de règles doit être un entier positif ou nul.")
        if type(seed) is not int or seed < 0:
            raise ValueError("La seed doit être un entier positif ou nul.")
        solutions = dict(self._solutions(game_id, states))
        if count not in solutions:
            possible = ", ".join(str(value) for value in solutions)
            raise ValueError(f"Impossible de sélectionner exactement {count} règles. Nombres possibles : {possible}.")
        chosen = random.Random(seed).choice(solutions[count])
        return [rule_id for index, rule_id in enumerate(self._ids) if chosen & (1 << index)]
