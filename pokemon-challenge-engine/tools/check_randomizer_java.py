"""Compile and execute synthetic adapter checks against an explicitly supplied ZX JAR.

This checks the actual Java selection algorithm and API linkage, not gameplay.
Usage: python -m tools.check_randomizer_java --java JAVA --jar JAR
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

from app.services.rom_transformation_service import ADAPTER, RomTransformationService


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java", required=True, type=Path)
    parser.add_argument("--jar", required=True, type=Path)
    args = parser.parse_args(argv)
    service = RomTransformationService(args.java, args.jar)
    service.validate_tool()
    compiler = service.java_path.with_name("javac.exe" if service.java_path.suffix == ".exe" else "javac")
    if not compiler.is_file():
        parser.error("Le JDK sélectionné ne contient pas javac à côté de java.")
    test = Path(__file__).resolve().parents[1] / "tests/java/PceRandomizerChecks.java"
    with tempfile.TemporaryDirectory(prefix="pce-java-check-") as directory:
        subprocess.run([str(compiler), "-cp", str(service.jar_path), "-d", directory, str(ADAPTER), str(test)],
                       timeout=120, check=True)
        import os
        subprocess.run([str(service.java_path), "-cp", directory + os.pathsep + str(service.jar_path),
                        "PceRandomizerChecks"], timeout=30, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
