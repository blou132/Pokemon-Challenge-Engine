"""Limited experimental White FR rev0 field-generator patch used by PCE.

Creates a NEW ROM copy only; rejects unrecognized code and oversized overlays.
No RAM/save access. Normal grass has gameplay evidence; other categories are
not guaranteed. See docs/shiny-field-trial.md for scope and developer CLI usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

from app.services.discovery_safety import local_path
from tools.shiny_arm9_inspect import (ZX_JAR_SHA256, decode_blz, prepare_arm9, run_codec,
                                     read_arm9, sha256)

DENOMINATORS = (4096, 1024, 512, 128, 1)
OVERLAY = 21
FIELD_BASE = 0x02187EA0
FIELD_SIZE = 354272
FUNCTION_START, FUNCTION_END = 0x021A9CD0, 0x021A9D68
ENTRY, END = 0x021A9D16, 0x021A9D64
RNG, PID = 0x020056EC, 0x020186E4
FIELD_FUNCTION_SHA256 = "fe0f3345f923ca8831fe848b5d8008f06e2154a142e1b4f1afd42988ecb73daf"
# Exact decoded ARM9 builds observed in the original and ZX-derived White FR.
# No regional/revision extrapolation or signature-only scan authorizes a patch.
ARM9_SHA256 = frozenset({
    "6f85b5e6632506a4d85e8c92635bb6dc8fa360b8e120f47dbd8764e46c6fd06a",
    "2bb986423bd60e055cd1c35ba1eefa157744f29b665e112b6fd675c93b8ec34d",
})
ENCODER = Path(__file__).with_name("randomizer") / "PceBlzEncode.java"


def encode_bl(address, target):
    delta = target - address - 4
    if delta % 2 or not -(1 << 22) <= delta < (1 << 22):
        raise ValueError("Thumb call is outside the supported range.")
    return [0xF000 | ((delta >> 12) & 0x7FF), 0xF800 | ((delta >> 1) & 0x7FF)]


def patch_body(denominator):
    if type(denominator) is not int or denominator not in DENOMINATORS:
        raise ValueError("Unsupported trial denominator.")
    code, labels, fixups = [], {}, []

    def emit(*words):
        code.extend(words)

    def branch(label, condition=None):
        fixups.append((len(code), label, condition))
        emit(0)

    # Preserve the existing field shiny lock==2. Sex/species/form and trainer
    # are passed unchanged to the game's real generator (rare=0 or rare=1).
    emit(0x79A0, 0x2802)
    branch("locked", 0)
    emit(0x2001, (denominator.bit_length() - 1) << 6)
    emit(*encode_bl(ENTRY + 2 * len(code), RNG))
    emit(0x2800)
    branch("locked", 1)
    emit(0x2101)
    branch("generate")
    labels["locked"] = len(code)
    emit(0x2100)
    labels["generate"] = len(code)
    emit(0x2002, 0x9000, 0x9101, 0x8821, 0x7962, 0x6A28, 0x1C33)
    emit(*encode_bl(ENTRY + 2 * len(code), PID))
    emit(0xB002, 0xBD70)
    for index, label, condition in fixups:
        delta = (labels[label] - index) * 2 - 4
        if condition is None:
            if not -2048 <= delta <= 2046:
                raise ValueError("Unconditional branch out of range.")
            code[index] = 0xE000 | ((delta >> 1) & 0x7FF)
        else:
            if not -256 <= delta <= 254:
                raise ValueError("Conditional branch out of range.")
            code[index] = 0xD000 | (condition << 8) | ((delta >> 1) & 0xFF)
    if len(code) * 2 > END - ENTRY:
        raise ValueError("Trial exceeds the existing function footprint.")
    code.extend([0x46C0] * ((END - ENTRY) // 2 - len(code)))
    return struct.pack("<" + "H" * len(code), *code)


def read_field(rom):
    with rom.open("rb") as stream:
        size = stream.seek(0, 2)
        stream.seek(0)
        header = stream.read(0x200)
        if len(header) != 0x200 or header[12:16] != b"IRAF" or header[30] != 0:
            raise ValueError("Trial is limited to White FR revision 0.")
        table, table_size, fat, fat_size = (*struct.unpack_from("<II", header, 0x50),
                                          *struct.unpack_from("<II", header, 0x48))
        if (table < 0x200 or fat < 0x200 or table_size % 32 or fat_size % 8
                or table_size < (OVERLAY + 1) * 32 or table + table_size > size
                or fat + fat_size > size):
            raise ValueError("Invalid overlay/FAT bounds.")
        entry_offset = table + OVERLAY * 32
        stream.seek(entry_offset)
        entry = struct.unpack("<8I", stream.read(32))
        oid, base, length, _, _, _, file_id, flags = entry
        if (oid != OVERLAY or base != FIELD_BASE or length != FIELD_SIZE
                or (file_id + 1) * 8 > fat_size or flags >> 24 not in (1, 3)):
            raise ValueError("Unrecognized field overlay layout.")
        stream.seek(fat)
        allocations = list(struct.iter_unpack("<II", stream.read(fat_size)))
        start, end = allocations[file_id]
        if not 0x200 <= start < end <= size or end - start != flags & 0xFFFFFF:
            raise ValueError("Invalid compressed overlay bounds.")
        # Changing this allocation must not touch another file or a table.
        for index, (other_start, other_end) in enumerate(allocations):
            if index != file_id and other_start < end and other_end > start:
                raise ValueError("Overlapping file allocations.")
        for other_start, other_end in ((table, table + table_size), (fat, fat + fat_size)):
            if other_start < end and other_end > start:
                raise ValueError("Overlay overlaps filesystem metadata.")
        stream.seek(start)
        data = stream.read(end - start)
    return data, {"start": start, "end": end, "flags_offset": entry_offset + 28,
                  "fat_end_offset": fat + file_id * 8 + 4, "flags": flags}


def encode_field(data, java, jar):
    result = run_codec([str(java), "-Xmx128m", "-cp", str(jar), str(ENCODER)], data, 120)
    if result.returncode or result.stderr or not result.stdout:
        raise ValueError("BLZ encoding did not finish cleanly.")
    if decode_blz(result.stdout, java, jar, len(data)) != data:
        raise ValueError("Encoded field failed exact decompression roundtrip.")
    return result.stdout


def verify_copy(source, output, edits):
    """Check every byte: only explicitly declared spans may differ."""
    if source.stat().st_size != output.stat().st_size:
        raise ValueError("Copy size changed unexpectedly.")
    with source.open("rb") as original, output.open("rb") as derived:
        offset = 0
        while chunk := original.read(1024 * 1024):
            expected = bytearray(chunk)
            for start, data in edits:
                low, high = max(start, offset), min(start + len(data), offset + len(chunk))
                if low < high:
                    expected[low - offset:high - offset] = data[low - start:high - start]
            if derived.read(len(chunk)) != expected:
                raise ValueError("Unexpected bytes changed in the ROM copy.")
            offset += len(chunk)


def create_trial(rom, output, java, jar, denominator):
    body = patch_body(denominator)
    rom, output, java, jar = (local_path(path) for path in (rom, output, java, jar))
    if output.exists() or output == rom or not output.parent.is_dir():
        raise ValueError("Output must be a new file in an existing directory.")
    if not all(path.is_file() for path in (rom, java, jar, ENCODER)):
        raise ValueError("Missing ROM, Java, codec source or JAR.")
    if sha256(jar) != ZX_JAR_SHA256:
        raise ValueError("Only the pinned official ZX JAR is accepted.")
    before = sha256(rom)
    packed, layout = read_field(rom)
    arm9, metadata = read_arm9(rom)
    arm9, compressed, expected, _ = prepare_arm9(arm9)
    arm9 = decode_blz(arm9, java, jar, expected) if compressed else arm9
    if metadata["arm9_load_address"] != 0x02004000 or hashlib.sha256(arm9).hexdigest() not in ARM9_SHA256:
        raise ValueError("ARM9 does not match a verified White FR build.")
    field = decode_blz(packed, java, jar, FIELD_SIZE)
    signature = field[FUNCTION_START - FIELD_BASE:FUNCTION_END - FIELD_BASE]
    if hashlib.sha256(signature).hexdigest() != FIELD_FUNCTION_SHA256:
        raise ValueError("Field generator is modified or unrecognized.")
    modified = bytearray(field)
    modified[ENTRY - FIELD_BASE:END - FIELD_BASE] = body
    encoded = encode_field(modified, java, jar)
    if len(encoded) > len(packed):
        raise ValueError("Compressed trial exceeds the original allocation.")
    edits = [(layout["start"], encoded),
             (layout["fat_end_offset"], struct.pack("<I", layout["start"] + len(encoded))),
             (layout["flags_offset"], struct.pack("<I", (layout["flags"] & 0xFF000000) | len(encoded)))]
    # Exclusive creation: a pre-existing file, hard link, save or ROM is never
    # overwritten. On failure keep the incomplete output for diagnosis.
    with output.open("xb") as destination, rom.open("rb") as source:
        shutil.copyfileobj(source, destination, 1024 * 1024)
        for offset, data in edits:
            destination.seek(offset)
            destination.write(data)
    verify_copy(rom, output, edits)
    reread, _ = read_field(output)
    if decode_blz(reread, java, jar, FIELD_SIZE) != modified or sha256(rom) != before:
        raise ValueError("Final trial/source verification failed.")
    return {"schema_version": 1, "status": "experimental_not_gameplay_validated",
            "game_code": "IRAF", "revision": 0, "selector_denominator": denominator,
            "source_sha256": before, "output_sha256": sha256(output),
            "source_unchanged": True, "only_declared_spans_changed": True,
            "patch_sha256": hashlib.sha256(body).hexdigest(),
            "decoded_overlay_sha256": hashlib.sha256(modified).hexdigest(),
            "gameplay_validated": False, "categories_validated": [],
            "shiny_predicate_changed": False, "shiny_lock_preserved": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("rom", "output", "java", "jar"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--denominator", type=int, choices=DENOMINATORS, required=True)
    args = parser.parse_args(argv)
    try:
        report = create_trial(args.rom, args.output, args.java, args.jar, args.denominator)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Trial refused: {error}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
