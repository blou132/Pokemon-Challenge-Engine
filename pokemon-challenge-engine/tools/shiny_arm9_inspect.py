"""Read-only Gen V FR ARM9 diagnostic; this does not identify a safe shiny patch.

Usage: python -m tools.shiny_arm9_inspect --rom COPY.nds --java JAVA --jar ZX_JAR
Only metadata is printed. ROM and decompressed ARM9 bytes are never written.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import zlib

from app.services.rom_transformation_service import ZX_JAR_SHA256, ZX_VERSION


MAX_ARM9 = 0xFFFFFF  # Same decompression ceiling as ZX's BLZCoder.
FR_CODES = frozenset({"IRAF", "IRBF", "IREF", "IRDF"})
DECODER = Path(__file__).with_name("randomizer") / "PceBlzDecode.java"

# Thumb instructions, not a patch: load the high-half mask, split r0/r1 into
# four halfwords, XOR them, compare with 8, return 1 or 0. The literal is checked
# separately using the actual aligned PC. Matching data alone proves no caller.
PREDICATE = struct.pack("<18H",
                       0x4B08, 0x040A, 0x4019, 0x4003, 0x0400, 0x0C1B,
                       0x0C00, 0x0C09, 0x4058, 0x0C12, 0x4048, 0x4050,
                       0x2808, 0xD201, 0x2001, 0x4770, 0x2000, 0x4770)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_arm9(path):
    """Bound all reads using the NDS header; never open a file for writing."""
    with Path(path).open("rb") as stream:
        size = stream.seek(0, 2)
        stream.seek(0)
        header = stream.read(0x200)
        if len(header) != 0x200:
            raise ValueError("En-tête NDS incomplet.")
        code = header[12:16].decode("ascii", errors="replace")
        revision = header[0x1E]
        if code not in FR_CODES or revision != 0:
            raise ValueError("Le diagnostic est limité aux quatre jeux Gen V FR révision 0.")
        offset, _, ram_address, length = struct.unpack_from("<4I", header, 0x20)
        if offset < 0x200 or length < 40 or length > MAX_ARM9 or offset + length > size:
            raise ValueError("Limites ARM9 invalides dans l'en-tête NDS.")
        if ram_address % 4 or ram_address + length > 0x100000000:
            raise ValueError("Adresse de chargement ARM9 invalide.")
        stream.seek(offset)
        arm9 = stream.read(length)
        if len(arm9) != length:
            raise ValueError("Lecture ARM9 incomplète.")
    return arm9, {"game_code": code, "revision": revision, "rom_size": size,
                  "arm9_rom_offset": offset, "arm9_load_address": ram_address}


def prepare_arm9(data):
    """Apply ZX's footer/compression identification, with strict length checks."""
    original_length = len(data)
    while len(data) >= 12 and (data[-12:] == bytes(12) or
                              struct.unpack_from("<I", data, len(data) - 12)[0] == 0xDEC00621):
        data = data[:-12]
    if len(data) < 40:
        raise ValueError("ARM9 vide ou tronqué après retrait des pieds Nitro.")
    header_length = data[-5]
    compressed = 8 <= header_length <= 11
    expected_length = len(data)
    if compressed:
        encoded_length = int.from_bytes(data[-8:-5], "little")
        growth = int.from_bytes(data[-4:], "little")
        if not (len(data) * 9 // 10 < encoded_length <= len(data)) or \
                encoded_length <= header_length or growth == 0:
            raise ValueError("Pied BLZ ambigu ou invalide ; analyse refusée.")
        expected_length += growth
        if expected_length > MAX_ARM9:
            raise ValueError("Décompression ARM9 hors limite.")
    return data, compressed, expected_length, original_length - len(data)


def find_predicates(arm9, ram_address):
    matches = []
    offset = arm9.find(PREDICATE)
    while offset != -1:
        literal = ((ram_address + offset + 4) & ~3) + 8 * 4 - ram_address
        if offset % 2 == 0 and literal >= 0 and literal + 4 <= len(arm9) and \
                struct.unpack_from("<I", arm9, literal)[0] == 0xFFFF0000:
            matches.append({"arm9_offset": offset, "compare_arm9_offset": offset + 24,
                            "load_address": ram_address + offset,
                            "routine_sha256": hashlib.sha256(arm9[offset:literal + 4]).hexdigest()})
        offset = arm9.find(PREDICATE, offset + 1)
    return matches


def decode_blz(data, java, jar, expected_length):
    result = subprocess.run([str(java), "-Xmx128m", "-cp", str(jar), str(DECODER)],
                            input=data, capture_output=True, timeout=60, check=False)
    # The upstream codec can print warnings or exit(0) on malformed data.
    # Neither a zero exit status nor partial output constitutes success.
    if result.returncode or result.stderr or len(result.stdout) != expected_length:
        raise ValueError("La décompression BLZ n'a pas produit un résultat complet sans avertissement.")
    return result.stdout


def inspect_rom(rom, java, jar):
    rom, java, jar = (Path(path).resolve(strict=True) for path in (rom, java, jar))
    if not all(path.is_file() for path in (rom, java, jar)) or not DECODER.is_file():
        raise ValueError("ROM, Java, JAR ou décompresseur absent.")
    if sha256(jar) != ZX_JAR_SHA256:
        raise ValueError("Le JAR doit être l'archive officielle ZX 4.6.1 vérifiée.")
    before = sha256(rom)
    raw, metadata = read_arm9(rom)
    packed, compressed, expected_length, footer_length = prepare_arm9(raw)
    arm9 = decode_blz(packed, java, jar, expected_length) if compressed else packed
    matches = find_predicates(arm9, metadata["arm9_load_address"])
    after = sha256(rom)
    if before != after:
        raise ValueError("La ROM a changé pendant l'analyse ; résultat refusé.")
    return {"schema_version": 1, "analysis": "gen5-fr-arm9-xor-predicate",
            **metadata, "rom_sha256_before": before, "rom_sha256_after": after,
            "source_unchanged": True, "zx_version": ZX_VERSION, "zx_jar_sha256": ZX_JAR_SHA256,
            "arm9_raw_size": len(raw), "arm9_raw_crc32": f"{zlib.crc32(raw):08X}",
            "arm9_raw_sha256": hashlib.sha256(raw).hexdigest(), "footer_bytes_removed": footer_length,
            "compression": "blz" if compressed else "none", "arm9_decoded_size": len(arm9),
            "arm9_decoded_crc32": f"{zlib.crc32(arm9):08X}",
            "arm9_decoded_sha256": hashlib.sha256(arm9).hexdigest(),
            "predicate_status": "unique" if len(matches) == 1 else "absent" if not matches else "ambiguous",
            "predicate_matches": matches, "predicate_threshold": 8 if matches else None,
            "callers_verified": False, "generation_paths_verified": [],
            "custom_shiny_rate_validated": False, "patch_eligible": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--java", required=True, type=Path)
    parser.add_argument("--jar", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = inspect_rom(args.rom, args.java, args.jar)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Analyse refusée : {error}\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
