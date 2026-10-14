"""Create a dedicated derived Gen V ROM with the pinned, external ZX tool."""

import argparse
import json
from pathlib import Path

from app.services.rom_transformation_service import CATEGORIES, RandomizerOptions, RomTransformationService, SUPPORTED_CODES


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path, help="New directory; existing directories are refused")
    parser.add_argument("--game", required=True, choices=SUPPORTED_CODES)
    parser.add_argument("--java", required=True, type=Path, help="Installed JDK 11+ java executable")
    parser.add_argument("--jar", required=True, type=Path, help="Official ZX 4.6.1 PokeRandoZX.jar")
    parser.add_argument("--seed", required=True, type=int, help="PCE adapter seed, passed to ZX's Java API")
    parser.add_argument("--categories", nargs="+", choices=CATEGORIES, default=["wild", "starters", "trainers"])
    parser.add_argument("--balanced", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = RomTransformationService(args.java, args.jar).transform(
            args.source, args.destination, game_id=args.game, seed=args.seed,
            options=RandomizerOptions(tuple(args.categories), args.balanced))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Transformation refusée : {exc}\n")
    print(json.dumps({"rom": str(result.rom_path), "manifest": str(result.manifest_path),
                      "validation": result.manifest["validation"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
