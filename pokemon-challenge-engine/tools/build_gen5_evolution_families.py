"""Rebuild factual Gen V evolution families from the pinned PKHeX resource.

Input is an explicit local copy of evos_g5.pkl, never a ROM or save. No network
access is performed. The exact source digest is checked before decoding.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

SOURCE_COMMIT = "09e7f18fbb33635e35cf9ffcbfd3322403780f8e"
SOURCE_SHA256 = "40a415c1febd807cd6e82b1bece71d7dcd724c7a17f03d9117af67304023479f"
SOURCE_ROOT = f"https://github.com/kwsch/PKHeX/blob/{SOURCE_COMMIT}/PKHeX.Core"
RESOURCE_PATH = "Resources/byte/evolve/evos_g5.pkl"


def decode_edges(data: bytes) -> list[list[int]]:
    """Read the documented 16-bit index and 8-byte evolution entries."""
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("Source evolution resource SHA-256 does not match the pinned revision.")
    if data[:2] != b"g5" or len(data) < 4:
        raise ValueError("Invalid Gen V evolution resource.")
    count = struct.unpack_from("<H", data, 2)[0]
    if count != 650:
        raise ValueError("Expected indices 0 through 649.")
    offsets = struct.unpack_from(f"<{count + 1}H", data, 4)
    if offsets[0] != 4 + (count + 1) * 2 or offsets[-1] != len(data):
        raise ValueError("Invalid evolution table bounds.")
    edges: set[tuple[int, int]] = set()
    for species in range(count):
        start, end = offsets[species:species + 2]
        if start > end or (end - start) % 8:
            raise ValueError("Invalid evolution entry bounds.")
        for position in range(start, end, 8):
            target = struct.unpack_from("<H", data, position + 4)[0]
            if not 1 <= species <= 649 or not 1 <= target <= 649 or species == target:
                raise ValueError("Invalid Gen V evolution edge.")
            edges.add((species, target))
    return [list(edge) for edge in sorted(edges)]


def build_families(edges: list[list[int]]) -> list[list[int]]:
    """Connected components, including singleton species and split branches."""
    adjacency = {species: set() for species in range(1, 650)}
    for first, second in edges:
        adjacency[first].add(second)
        adjacency[second].add(first)
    unseen = set(adjacency)
    families = []
    while unseen:
        waiting = [min(unseen)]
        component: set[int] = set()
        while waiting:
            species = waiting.pop()
            if species not in component:
                component.add(species)
                waiting.extend(adjacency[species] - component)
        unseen.difference_update(component)
        families.append(sorted(component))
    return families


def build_document(data: bytes) -> dict:
    edges = decode_edges(data)
    # The source distinguishes creating Shedinja (15) from evolving Ninjask (14).
    # Creation links belong to a family, but do not establish individual identity.
    offsets = struct.unpack_from("<651H", data, 4)
    creation_edges = sorted({(species, struct.unpack_from("<H", data, position + 4)[0])
                             for species in range(650)
                             for position in range(offsets[species], offsets[species + 1], 8)
                             if data[position] == 15})
    return {
        "schema_version": 1,
        "generation": 5,
        "species_max": 649,
        "validation": "source_documented",
        "family_id_policy": "minimum_national_dex_id_in_connected_component",
        "source": {
            "project": "PKHeX", "commit": SOURCE_COMMIT,
            "resource_url": f"{SOURCE_ROOT}/{RESOURCE_PATH}",
            "resource_sha256": SOURCE_SHA256, "resource_bytes": len(data),
            "format_sources": [f"{SOURCE_ROOT}/Legality/Assets/BinLinkerAccessor16.cs",
                               f"{SOURCE_ROOT}/Legality/Evolutions/EvolutionSet.cs",
                               f"{SOURCE_ROOT}/Legality/Evolutions/EvolutionTree.cs",
                               f"{SOURCE_ROOT}/Legality/Evolutions/Methods/EvolutionType.cs"],
        },
        "evolution_edges": edges,
        "creation_edges": [list(edge) for edge in creation_edges],
        "families": build_families(edges),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Explicit local evos_g5.pkl from the pinned PKHeX revision")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data/gen5_evolution_families.json")
    args = parser.parse_args()
    result = build_document(args.source.read_bytes())
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
