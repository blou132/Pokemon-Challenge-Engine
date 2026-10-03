"""Local individual keys and sourced Gen V families, without game writes.

A PID/OT pair is a tracking key, not a uniqueness proof: clones and split
evolutions can collide. Callers must reject ambiguous observations themselves.
"""
from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
import json
from pathlib import Path
from typing import Any


def pokemon_identity(pokemon: Mapping[str, Any], generation: int = 5) -> str | None:
    """Return a stable technical key only for the documented Gen V pair."""
    if type(generation) is not int or generation != 5 or not isinstance(pokemon, Mapping):
        return None
    pid, trainer = pokemon.get("personality_id"), pokemon.get("original_trainer_id")
    if any(type(value) is not int or not 0 <= value <= 0xFFFFFFFF for value in (pid, trainer)):
        return None
    return f"gen5:{pid:08x}:{trainer:08x}"


@lru_cache(maxsize=1)
def _family_map() -> tuple[int | None, ...]:
    path = Path(__file__).resolve().parents[2] / "data/gen5_evolution_families.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("generation") != 5 or data.get("species_max") != 649:
        raise ValueError("Table de familles Gen V incompatible.")
    result: list[int | None] = [None] * 650
    for family in data["families"]:
        if not isinstance(family, list) or not family:
            raise ValueError("Famille évolutive vide ou invalide.")
        if any(type(species) is not int or not 1 <= species <= 649 for species in family):
            raise ValueError("Espèce inconnue dans une famille Gen V.")
        identifier = min(family)
        for species in family:
            if result[species] is not None:
                raise ValueError("Espèce présente dans plusieurs familles.")
            result[species] = identifier
    if any(value is None for value in result[1:]):
        raise ValueError("Table de familles Gen V incomplète.")
    return tuple(result)


def evolution_family(species_id: int, generation: int = 5) -> int | None:
    """Unknown species/generation stays unknown, never guessed from its number."""
    if type(generation) is not int or generation != 5 or type(species_id) is not int or not 1 <= species_id <= 649:
        return None
    return _family_map()[species_id]


def same_evolution_family(first: int, second: int, generation: int = 5) -> bool:
    family = evolution_family(first, generation)
    return family is not None and family == evolution_family(second, generation)


@lru_cache(maxsize=1)
def _evolution_graph() -> dict[int, frozenset[int]]:
    path = Path(__file__).resolve().parents[2] / "data/gen5_evolution_families.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    graph: dict[int, set[int]] = {}
    creation = {tuple(edge) for edge in data["creation_edges"]}
    for first, second in data["evolution_edges"]:
        if not same_evolution_family(first, second):
            raise ValueError("Lien évolutif incohérent avec la table des familles.")
        if (first, second) not in creation:
            graph.setdefault(first, set()).add(second)
    return {species: frozenset(targets) for species, targets in graph.items()}


def documented_evolution(first: int, second: int, generation: int = 5) -> bool:
    """A forward evolution path may preserve identity; family siblings do not.

    This is no proof that the game's level/item conditions were fulfilled.
    Shedinja creation is deliberately excluded from same-individual tracking.
    """
    if first == second or not same_evolution_family(first, second, generation):
        return False
    graph = _evolution_graph()
    waiting, visited = [first], set()
    while waiting:
        species = waiting.pop()
        if species in visited:
            continue
        visited.add(species)
        targets = graph.get(species, ())
        if second in targets:
            return True
        waiting.extend(targets)
    return False
