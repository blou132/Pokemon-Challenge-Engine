"""Synthetic static-analysis checks; real ROM checks are run explicitly by CLI."""

import hashlib
import random
import struct
from types import SimpleNamespace

import pytest

from tools import shiny_arm9_inspect as inspect


def routine():
    return inspect.PREDICATE + struct.pack("<I", 0xFFFF0000)


def execute_thumb_predicate(first, second):
    """Independent instruction interpreter for the recognized leaf, not a DS emulator."""
    code = routine()
    registers = [first, second, 0, 0, 0, 0, 0, 0]
    pc, carry = 0, False
    for _ in range(30):
        op = struct.unpack_from("<H", code, pc)[0]
        following = pc + 2
        if op & 0xF800 == 0x4800:  # LDR literal
            registers[(op >> 8) & 7] = struct.unpack_from("<I", code, ((pc + 4) & ~3) + (op & 255) * 4)[0]
        elif op & 0xF800 == 0:  # LSL immediate
            registers[op & 7] = (registers[(op >> 3) & 7] << ((op >> 6) & 31)) & 0xFFFFFFFF
        elif op & 0xF800 == 0x0800:  # LSR immediate
            registers[op & 7] = registers[(op >> 3) & 7] >> (((op >> 6) & 31) or 32)
        elif op & 0xFFC0 == 0x4000:  # AND
            registers[op & 7] &= registers[(op >> 3) & 7]
        elif op & 0xFFC0 == 0x4040:  # EOR
            registers[op & 7] ^= registers[(op >> 3) & 7]
        elif op & 0xF800 == 0x2800:  # CMP immediate, unsigned carry
            carry = registers[(op >> 8) & 7] >= (op & 255)
        elif op & 0xFF00 == 0xD200:  # BCS
            displacement = op & 255
            if displacement >= 128:
                displacement -= 256
            if carry:
                following = pc + 4 + displacement * 2
        elif op & 0xF800 == 0x2000:  # MOV immediate
            registers[(op >> 8) & 7] = op & 255
        elif op == 0x4770:  # BX LR
            return registers[0]
        else:
            pytest.fail(f"Unexpected instruction at {pc}")
        pc = following
    pytest.fail("Predicate did not return")


def test_instruction_semantics_match_gen5_xor_for_every_reduced_value_and_each_input_bit():
    for value in range(65536):
        assert execute_thumb_predicate(0, value) == (value < 8)
    for bit in range(32):
        value = 1 << bit
        expected = ((value & 65535) ^ (value >> 16)) < 8
        assert execute_thumb_predicate(value, 0) == expected
        assert execute_thumb_predicate(0, value) == expected
        assert execute_thumb_predicate(value, value) == 1
    rng = random.Random(20261020)
    for _ in range(512):
        first, second = rng.getrandbits(32), rng.getrandbits(32)
        for result in (0, 7, 8, 65535):
            # Force the final XOR around both sides of the threshold while
            # retaining arbitrary trainer high/low and PID high halfwords.
            second = (second & 0xFFFF0000) | ((first & 65535) ^ (first >> 16) ^ (second >> 16) ^ result)
            assert execute_thumb_predicate(first, second) == (result < 8)


def nds(tmp_path, arm9=None, code=b"IRAF", revision=0):
    arm9 = routine() if arm9 is None else arm9
    header = bytearray(0x200)
    header[12:16] = code
    header[0x1E] = revision
    struct.pack_into("<4I", header, 0x20, len(header), 0x02000000, 0x02000000, len(arm9))
    path = tmp_path / "synthetic.nds"
    path.write_bytes(header + arm9)
    return path


def test_complete_predicate_requires_instruction_alignment_and_literal():
    assert len(inspect.find_predicates(routine(), 0x02000000)) == 1
    assert inspect.find_predicates(b"\0" + routine(), 0x02000000) == []
    assert inspect.find_predicates(routine()[:-4], 0x02000000) == []
    assert inspect.find_predicates(routine()[:-4] + bytes(4), 0x02000000) == []
    modified = bytearray(routine())
    modified[24] = 16
    assert inspect.find_predicates(modified, 0x02000000) == []
    assert inspect.find_predicates(inspect.PREDICATE[24:], 0x02000000) == []


def test_duplicate_predicates_are_retained_as_ambiguous():
    matches = inspect.find_predicates(routine() * 2, 0x02000000)
    assert [match["arm9_offset"] for match in matches] == [0, 40]
    assert [match["compare_arm9_offset"] for match in matches] == [24, 64]


@pytest.mark.parametrize("code,revision", [(b"IRAO", 0), (b"IRAF", 1), (b"????", 0)])
def test_header_rejects_unverified_game_builds(tmp_path, code, revision):
    with pytest.raises(ValueError, match="Gen V FR"):
        inspect.read_arm9(nds(tmp_path, code=code, revision=revision))


@pytest.mark.parametrize("offset,length", [(0, 40), (0x200, 0xFFFFFF + 1), (0x200, 41), (0x200, 39)])
def test_header_rejects_out_of_bounds_ranges(tmp_path, offset, length):
    path = nds(tmp_path)
    data = bytearray(path.read_bytes())
    struct.pack_into("<I", data, 0x20, offset)
    struct.pack_into("<I", data, 0x2C, length)
    path.write_bytes(data)
    with pytest.raises(ValueError, match="Limites ARM9"):
        inspect.read_arm9(path)


def test_footer_and_blz_size_checks():
    raw = routine()
    assert inspect.prepare_arm9(raw) == (raw, False, len(raw), 0)
    assert inspect.prepare_arm9(raw + struct.pack("<3I", 0xDEC00621, 1, 2)) == (raw, False, len(raw), 12)
    packed = bytes(40) + struct.pack("<II", (8 << 24) | 48, 100)
    assert inspect.prepare_arm9(packed) == (packed, True, 148, 0)
    for encoded, growth in [(60, 100), (8, 100), (48, 0), (48, 0xFFFFFF)]:
        with pytest.raises(ValueError):
            inspect.prepare_arm9(bytes(40) + struct.pack("<II", (8 << 24) | encoded, growth))


@pytest.mark.parametrize("stdout,stderr,returncode", [(b"x", b"", 0), (b"xx", b"warning", 0), (b"xx", b"", 1)])
def test_codec_must_return_complete_output_without_warnings(monkeypatch, stdout, stderr, returncode):
    monkeypatch.setattr(inspect.subprocess, "run", lambda *a, **k: SimpleNamespace(
        stdout=stdout, stderr=stderr, returncode=returncode))
    with pytest.raises(ValueError, match="décompression BLZ"):
        inspect.decode_blz(b"synthetic", "java", "jar", 2)


def test_report_never_validates_a_patch_and_preserves_source(tmp_path, monkeypatch):
    path = nds(tmp_path)
    java, jar = tmp_path / "java", tmp_path / "jar"
    java.write_bytes(b"synthetic")
    jar.write_bytes(b"synthetic jar")
    monkeypatch.setattr(inspect, "ZX_JAR_SHA256", hashlib.sha256(jar.read_bytes()).hexdigest())
    before = path.read_bytes()
    report = inspect.inspect_rom(path, java, jar)
    assert report["predicate_status"] == "unique"
    assert report["predicate_threshold"] == 8
    assert report["source_unchanged"]
    assert not report["custom_shiny_rate_validated"]
    assert not report["patch_eligible"]
    assert not report["callers_verified"]
    assert report["generation_paths_verified"] == []
    assert path.read_bytes() == before
    assert report["rom_sha256_before"] == report["rom_sha256_after"]


def test_changed_source_during_analysis_is_refused(tmp_path, monkeypatch):
    path = nds(tmp_path)
    java, jar = tmp_path / "java", tmp_path / "jar"
    java.touch()
    jar.touch()
    calls = iter([inspect.ZX_JAR_SHA256, "before", "after"])
    monkeypatch.setattr(inspect, "sha256", lambda path: next(calls))
    with pytest.raises(ValueError, match="changé pendant"):
        inspect.inspect_rom(path, java, jar)


def test_unpinned_jar_is_rejected_before_rom_read(tmp_path, monkeypatch):
    path = nds(tmp_path)
    java, jar = tmp_path / "java", tmp_path / "jar"
    java.touch()
    jar.touch()
    monkeypatch.setattr(inspect, "read_arm9", lambda path: pytest.fail("ROM opened before JAR validation"))
    with pytest.raises(ValueError, match="officielle ZX"):
        inspect.inspect_rom(path, java, jar)
