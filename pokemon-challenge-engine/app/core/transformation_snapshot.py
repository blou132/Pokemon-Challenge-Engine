"""Immutable in-memory ROM evidence; never a persisted run format."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.core.monotype import GEN5_TYPE_IDS


def pokemon_tables(rows, *, frozen=False):
    """Validate complete Gen V rows before sharing read-only lookup tables."""
    sequence = (list, tuple) if frozen else list
    mapping = Mapping if frozen else dict
    if not isinstance(rows, sequence):
        return None
    types_by_form, parents, graph = {}, set(), {}
    identity_complete = True
    for row in rows:
        if not isinstance(row, mapping):
            return None
        species, form, types = row.get("species_id"), row.get("form"), row.get("types")
        edges, identity_edges = row.get("evolutions"), row.get("identity_evolutions")
        if (type(species) is not int or not 1 <= species <= 649 or type(form) is not int or not 0 <= form <= 31
                or (species, form) in types_by_form or not isinstance(types, sequence) or not 1 <= len(types) <= 2
                or any(not isinstance(item, str) or item not in GEN5_TYPE_IDS for item in types)
                or len(set(types)) != len(types) or not isinstance(edges, sequence)
                or any(type(item) is not int or not 1 <= item <= 649 for item in edges)):
            return None
        types_by_form[species, form] = tuple(types)
        parents.update(edges)
        if (not isinstance(identity_edges, sequence)
                or any(type(item) is not int or item not in edges for item in identity_edges)):
            identity_complete = False
        elif form == 0:
            # Species-only history cannot prove an evolution tied to an
            # alternate form; do not merge those branches into the base.
            graph[species] = frozenset(identity_edges)
    if any((species, 0) not in types_by_form for species in range(1, 650)):
        return None
    return (MappingProxyType(types_by_form), frozenset(parents),
            MappingProxyType(graph) if identity_complete else None)


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if value is None or type(value) in (bool, int, float, str):
        return value
    raise ValueError("Unsupported transformation snapshot value.")


@dataclass(frozen=True, init=False, eq=False)
class TransformationSnapshot(Mapping):
    """Detached JSON evidence whose copies can safely share validated tables.

    Only the provider validates the artifact provenance. This object adds no
    trust: RunPokemonData still checks the run/game/ROM/configuration binding.
    """

    _values: Mapping
    tables: tuple | None

    def __init__(self, values):
        object.__setattr__(self, "_values", _freeze(values))
        object.__setattr__(self, "tables", pokemon_tables(self.get("pokemon"), frozen=True))

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self
