"""Documented vanilla Gen V species facts, not observations of battle effects.

Missing forms with differing types and modified ROM data remain unknown. These
lookups cannot identify which individual was the starter, or prove battle use.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

from app.core.monotype import GEN5_TYPE_IDS, MONOTYPE_MODES, matches_type

GAME_FAMILIES = {"black": "bw", "white": "bw", "black2": "b2w2", "white2": "b2w2"}


def _valid_species(species_id: int, game_id: str) -> bool:
    return (type(species_id) is int and 1 <= species_id <= 649
            and isinstance(game_id, str) and game_id in GAME_FAMILIES)


@lru_cache(maxsize=1)
def _catalog() -> dict:
    path = Path(__file__).resolve().parents[2] / "data/gen5_species_types.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("generation") != 5 or data.get("species_max") != 649:
        raise ValueError("Table des espèces Gen V incompatible.")
    if set(data["type_ids"]) != set(GEN5_TYPE_IDS) or len(data["type_ids"]) != 17:
        raise ValueError("La table doit décrire les 17 types Gen V.")
    for family in ("bw", "b2w2"):
        table = data["families"][family]
        if set(table["games"]) != {game for game, value in GAME_FAMILIES.items() if value == family}:
            raise ValueError("Jeux incohérents dans la table Gen V.")
        rows = table["species"]
        if [row["species_id"] for row in rows] != list(range(1, 650)):
            raise ValueError("Table des espèces Gen V incomplète.")
        for row in rows:
            forms = row["forms"]
            if not isinstance(forms, list) or not 1 <= len(forms) <= 32:
                raise ValueError("Formes Gen V invalides.")
            for types in forms:
                if (not isinstance(types, list) or not 1 <= len(types) <= 2
                        or any(value not in GEN5_TYPE_IDS for value in types)
                        or len(set(types)) != len(types)):
                    raise ValueError("Types Gen V invalides.")
        candidates = data["starter_candidates"][family]["species"]
        if not candidates or any(type(value) is not int or not 1 <= value <= 649 for value in candidates):
            raise ValueError("Candidats starters Gen V invalides.")
    return data


def species_types(species_id: int, game_id: str, form: int | None = None,
                  *, types_modified: bool = False) -> tuple[str, ...] | None:
    """Return ordered original types, or None when this lookup cannot prove them.

An omitted form is accepted only when every documented form has identical types.
Changing types in a ROM invalidates this vanilla table, including known form 0.
Transient effects such as Soak and Transform are not described by this function.
"""
    if not _valid_species(species_id, game_id) or types_modified is not False:
        return None
    forms = _catalog()["families"][GAME_FAMILIES[game_id]]["species"][species_id - 1]["forms"]
    if form is None:
        return tuple(forms[0]) if all(types == forms[0] for types in forms) else None
    if type(form) is not int or not 0 <= form < len(forms):
        return None
    return tuple(forms[form])


def monotype_compliance(species_id: int, game_id: str, target: str,
                        mode: str = "soft", form: int | None = None,
                        *, types_modified: bool = False) -> bool | None:
    """Three-state conformity; absence of evidence is never a violation."""
    if target not in GEN5_TYPE_IDS or mode not in MONOTYPE_MODES:
        raise ValueError("Type ou mode Monotype inconnu.")
    types = species_types(species_id, game_id, form, types_modified=types_modified)
    return None if types is None else matches_type(list(types), target, mode)


@lru_cache(maxsize=1)
def _evolution_stages() -> tuple[int, ...]:
    path = Path(__file__).resolve().parents[2] / "data/gen5_evolution_families.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("generation") != 5 or data.get("species_max") != 649:
        raise ValueError("Table des évolutions Gen V incompatible.")
    parents = {species: set() for species in range(1, 650)}
    for edge in data["evolution_edges"]:
        if (not isinstance(edge, list) or len(edge) != 2
                or any(type(value) is not int or not 1 <= value <= 649 for value in edge)):
            raise ValueError("Lien évolutif Gen V invalide.")
        parents[edge[1]].add(edge[0])
    resolved: dict[int, int] = {}

    def stage(species: int, visiting: frozenset[int]) -> int:
        if species in visiting:
            raise ValueError("Cycle dans les évolutions Gen V.")
        if species not in resolved:
            resolved[species] = max((stage(parent, visiting | {species}) + 1
                                     for parent in parents[species]), default=0)
        return resolved[species]

    # Shedinja creation is deliberately an evolved stage here; its exclusion
    # from same-individual evolution tracking serves a different purpose.
    return (0,) + tuple(stage(species, frozenset()) for species in range(1, 650))


def evolution_stage(species_id: int, game_id: str, *, evolutions_modified: bool = False) -> int | None:
    """Zero is an initial stage (including species without any evolution)."""
    if not _valid_species(species_id, game_id) or evolutions_modified is not False:
        return None
    return _evolution_stages()[species_id]


def is_unevolved(species_id: int, game_id: str, *, evolutions_modified: bool = False) -> bool | None:
    """Convention: no prior evolutionary stage, not 'can evolve further'."""
    stage = evolution_stage(species_id, game_id, evolutions_modified=evolutions_modified)
    return None if stage is None else stage == 0


def starter_species(game_id: str, *, starters_modified: bool = False) -> tuple[int, ...] | None:
    """Vanilla candidate species only; no claim about the observed individual."""
    if not isinstance(game_id, str) or game_id not in GAME_FAMILIES or starters_modified is not False:
        return None
    return tuple(_catalog()["starter_candidates"][GAME_FAMILIES[game_id]]["species"])
