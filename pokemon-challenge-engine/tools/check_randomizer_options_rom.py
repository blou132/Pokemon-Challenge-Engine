"""Verify independent ZX options using a user-supplied clean ROM, without emulation.

Each case creates a new derived ROM and provenance; the input is read-only.
The combined cases also check reproducibility with effective Monotype types.
"""
import argparse
import json
from pathlib import Path
import time

from app.services.rom_transformation_service import (
    ADVANCED_DEFAULTS, CATEGORIES, SUPPORTED_CODES, RandomizerOptions, RomTransformationService,
)


def cases():
    def options(categories, **overrides):
        return RandomizerOptions(categories, advanced={**ADVANCED_DEFAULTS, **overrides})

    combined = RandomizerOptions(CATEGORIES, advanced=dict(
        ADVANCED_DEFAULTS, starter_similar_strength=True, starter_legendaries=False, starter_mythicals=False,
        wild_mode="global_mapping", wild_similar_strength=True, trainer_mode="distributed",
        trainer_similar_strength=True, evolution_similar_strength=True, evolution_same_type=True,
        evolution_three_stages=True, evolution_force_change=True, evolution_fix_impossible=True,
        types_follow_evolutions=True, movesets_same_type=True),
        monotype_starters={"type_id": "fire", "mode": "pure", "prefer_evolutions": True})
    return {
        "pickup_only": options(("pickup_items",)),
        "starter_power": options(("starters",), starter_similar_strength=True,
                                 starter_legendaries=False, starter_mythicals=False),
        "wild_area": options(("wild",), wild_mode="area_mapping"),
        "wild_global": options(("wild",), wild_mode="global_mapping", wild_similar_strength=True),
        "trainers_distributed": options(("trainers",), trainer_mode="distributed"),
        "trainers_main": options(("trainers",), trainer_mode="main_playthrough", trainer_similar_strength=True),
        "evolution_methods": options(("evolutions",), evolution_mode="unchanged", evolution_fix_impossible=True),
        "combined_a": combined,
        "combined_b": combined,
        **{f"monotype_{mode}": RandomizerOptions(("starters",),
               advanced=dict(ADVANCED_DEFAULTS, starter_legendaries=False, starter_mythicals=False,
                             starter_similar_strength=True),
               monotype_starters={"type_id": "fire", "mode": mode, "prefer_evolutions": True})
           for mode in ("soft", "strict", "pure")},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True, help="New validation directory")
    parser.add_argument("--game", choices=SUPPORTED_CODES, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--jar", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=5122026)
    parser.add_argument("--case", choices=tuple(cases()), action="append")
    args = parser.parse_args(argv)
    service = RomTransformationService(args.java, args.jar)
    service.validate_tool()
    args.destination.mkdir(exist_ok=False)
    selected = cases()
    summary = {"game_id": args.game, "seed": args.seed, "emulator": "not_tested", "cases": {}}
    for name in args.case or selected:
        started = time.monotonic()
        try:
            result = service.transform(args.source, args.destination / name, game_id=args.game,
                                       seed=args.seed, options=selected[name])
            row = {"status": "passed", "source_sha256": result.manifest["source_sha256"],
                   "output_sha256": result.manifest["output_sha256"],
                   "source_unchanged": result.manifest["validation"]["source_unchanged"],
                   "rom_reloaded_by_tool": result.manifest["validation"]["rom_reloaded_by_tool"]}
        except (OSError, ValueError) as exc:
            row = {"status": "failed", "error": str(exc)}
        row["seconds"] = round(time.monotonic() - started, 2)
        summary["cases"][name] = row
        (args.destination / "validation.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"case": name, **row}), flush=True)
    results = summary["cases"]
    if {"combined_a", "combined_b"} <= results.keys():
        summary["reproducible"] = (results["combined_a"]["status"] == results["combined_b"]["status"] == "passed"
                                   and results["combined_a"]["output_sha256"] == results["combined_b"]["output_sha256"])
    (args.destination / "validation.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return int(any(row["status"] != "passed" for row in results.values()) or not summary.get("reproducible", True))


if __name__ == "__main__":
    raise SystemExit(main())
