"""Rebuild factual species/form types from two pinned PKHeX personal tables.

Inputs are explicitly supplied local PKHeX resources, never a ROM or save. The
generator performs no network access and rejects any unverified source digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

SOURCE_COMMIT = "09e7f18fbb33635e35cf9ffcbfd3322403780f8e"
SOURCE_ROOT = f"https://github.com/kwsch/PKHeX/blob/{SOURCE_COMMIT}/PKHeX.Core"
SOURCES = {
    "bw": {"sha256": "3b2989703f07416162e61328186d2858cbe3082875c98c21eb40c2f7ce85ab7e",
           "bytes": 40080, "entry_size": 0x3C, "class_suffix": "5BW",
           "games": ["black", "white"]},
    "b2w2": {"sha256": "6df24e7f00dab32322d9d8f8b3209d30de1c89b0de88277081fe53434211830f",
             "bytes": 53884, "entry_size": 0x4C, "class_suffix": "5B2W2",
             "games": ["black2", "white2"]},
}
# MoveType.cs assigns these numeric values in Gen V; Fairy (17) is excluded.
TYPE_IDS = ("normal", "fighting", "flying", "poison", "ground", "rock", "bug",
            "ghost", "steel", "fire", "water", "grass", "electric", "psychic",
            "ice", "dragon", "dark")
# PersonalTable5BW/B2W2.IsPresentInGame lists forms without separate stats rows.
SHARED_STATS_FORM_COUNTS = {
    201: 28, 412: 3, 414: 3, 421: 2, 422: 2, 423: 2,
    493: 17, 585: 4, 586: 4, 649: 5,
}


def decode_table(data: bytes, family: str) -> list[dict]:
    """Resolve only forms explicitly admitted by the pinned personal table."""
    if family not in SOURCES:
        raise ValueError("Unknown Gen V game family.")
    source = SOURCES[family]
    if hashlib.sha256(data).hexdigest() != source["sha256"]:
        raise ValueError("Source personal resource SHA-256 does not match the pinned revision.")
    size = source["entry_size"]
    if len(data) != source["bytes"] or len(data) % size:
        raise ValueError("Invalid personal table bounds.")
    result = []
    for species in range(1, 650):
        base = data[species * size:(species + 1) * size]
        index = struct.unpack_from("<H", base, 0x1C)[0]
        count = max(base[0x20] if index > 0 else 1,
                    SHARED_STATS_FORM_COUNTS.get(species, 1))
        if not 1 <= count <= 32:
            raise ValueError("Invalid Gen V form count.")
        forms = []
        for form in range(count):
            personal_index = index + form - 1 if form and index and form < base[0x20] else species
            row = data[personal_index * size:(personal_index + 1) * size]
            if len(row) != size or any(value >= len(TYPE_IDS) for value in row[6:8]):
                raise ValueError("Invalid personal form entry or Gen V type.")
            # Arceus reuses one personal row; GetFormsArceus(Gen5) maps each
            # stored form to its type. It must never inherit Normal for all forms.
            types = [TYPE_IDS[form]] if species == 493 else list(dict.fromkeys(TYPE_IDS[value] for value in row[6:8]))
            forms.append(types)
        result.append({"species_id": species, "forms": forms})
    return result


def build_document(bw: bytes, b2w2: bytes) -> dict:
    families = {}
    for family, data in (("bw", bw), ("b2w2", b2w2)):
        source = SOURCES[family]
        suffix = source["class_suffix"]
        families[family] = {
            "games": source["games"],
            "source": {
                "resource_url": f"{SOURCE_ROOT}/Resources/byte/personal/personal_{family}",
                "resource_sha256": source["sha256"],
                "resource_bytes": len(data), "entry_size": source["entry_size"],
                "format_sources": [f"{SOURCE_ROOT}/PersonalInfo/Info/PersonalInfo{suffix}.cs",
                                   f"{SOURCE_ROOT}/PersonalInfo/Table/PersonalTable{suffix}.cs"],
            },
            "species": decode_table(data, family),
        }
    return {
        "schema_version": 1, "generation": 5, "species_max": 649,
        "validation": "source_documented",
        "source": {
            "project": "PKHeX", "commit": SOURCE_COMMIT,
            "format_sources": [f"{SOURCE_ROOT}/PersonalInfo/PersonalInfo.cs",
                               f"{SOURCE_ROOT}/Game/Enums/MoveType.cs",
                               f"{SOURCE_ROOT}/PKM/Util/Conversion/FormConverter.cs"],
        },
        "type_ids": list(TYPE_IDS),
        "form_policy": "zero_based_explicit_form_id; duplicate_types_collapsed; original_species_types_not_battle_effects",
        "families": families,
        "starter_candidates": {
            "bw": {"species": [495, 498, 501],
                   "source_url": f"{SOURCE_ROOT}/Legality/Encounters/Data/Gen5/Encounters5BW.cs"},
            "b2w2": {"species": [495, 498, 501],
                     "source_url": f"{SOURCE_ROOT}/Legality/Encounters/Data/Gen5/Encounters5B2W2.cs"},
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bw", type=Path, help="Local personal_bw from the pinned PKHeX revision")
    parser.add_argument("b2w2", type=Path, help="Local personal_b2w2 from the pinned PKHeX revision")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data/gen5_species_types.json")
    args = parser.parse_args()
    result = build_document(args.bw.read_bytes(), args.b2w2.read_bytes())
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
