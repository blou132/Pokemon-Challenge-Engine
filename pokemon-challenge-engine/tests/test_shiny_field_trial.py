"""Safety/encoding tests only; synthetic input does not establish playable rates."""
import hashlib
import struct

import pytest

from tools import shiny_field_trial as trial


@pytest.mark.parametrize("value", [True, False, 0, -1, 8, 8192, 1.0, "1"])
def test_unknown_trial_denominator_rejected(value):
    with pytest.raises(ValueError):
        trial.patch_body(value)


@pytest.mark.parametrize("denominator,digest", [
    (4096, "9bf12aef3e453593d6d95fb816375173a77cf349d524a6dfa81bfa2aff47b2ea"),
    (1024, "c9d8fe0171e5aa6cc2f391204d17955107c55924408afaf329b00f4f82fa02a3"),
    (512, "e4b9857c4620c37143efe2c4514ab44ff63b59e94f81aed0fc0f73d885518f96"),
    (128, "97b63d786e210438d9d83311a4532a11fbeee721e7554824e5d91f8556f4561d"),
    (1, "c18a135e71334b37d9aa0e27d423f309b69c307dc22552b4b04053aee672da54"),
])
def test_trial_is_the_cpu_verified_instruction_sequence(denominator, digest):
    code = trial.patch_body(denominator)
    assert len(code) == trial.END - trial.ENTRY
    assert hashlib.sha256(code).hexdigest() == digest


def field_fixture(tmp_path, *, flags=3):
    """Only a bounded filesystem fixture; its overlay bytes are not game code."""
    rom = tmp_path / "fixture.nds"
    data = bytearray(0x1000)
    data[12:16] = b"IRAF"
    table, fat, start, end = 0x200, 0x500, 0x600, 0x700
    struct.pack_into("<II", data, 0x50, table, 22 * 32)
    struct.pack_into("<II", data, 0x48, fat, 8)
    struct.pack_into("<8I", data, table + 21 * 32, 21, trial.FIELD_BASE, trial.FIELD_SIZE,
                     0, 0, 0, 0, (flags << 24) | (end - start))
    struct.pack_into("<II", data, fat, start, end)
    rom.write_bytes(data)
    return rom


@pytest.mark.parametrize("flags", [1, 3])
def test_field_compression_flags_and_bounded_layout(tmp_path, flags):
    rom = field_fixture(tmp_path, flags=flags)
    packed, layout = trial.read_field(rom)
    assert len(packed) == 0x100
    assert layout["flags"] >> 24 == flags


@pytest.mark.parametrize("corruption", ["game", "revision", "table", "fat", "overlay", "size"])
def test_unrecognized_build_and_invalid_allocations_rejected(tmp_path, corruption):
    rom = field_fixture(tmp_path)
    data = bytearray(rom.read_bytes())
    if corruption == "game": data[12:16] = b"IREF"
    elif corruption == "revision": data[30] = 1
    elif corruption == "table": struct.pack_into("<I", data, 0x50, 0xF00)
    elif corruption == "fat": struct.pack_into("<II", data, 0x500, 0x300, 0x400)
    elif corruption == "overlay": struct.pack_into("<I", data, 0x200 + 21 * 32, 22)
    elif corruption == "size": struct.pack_into("<I", data, 0x504, 0x1100)
    rom.write_bytes(data)
    with pytest.raises(ValueError):
        trial.read_field(rom)


def test_trial_never_overwrites_existing_rom_or_report(tmp_path):
    source = tmp_path / "source.nds"
    output = tmp_path / "output.nds"
    source.write_bytes(b"original")
    output.write_bytes(b"personal file")
    with pytest.raises(ValueError, match="new file"):
        trial.create_trial(source, output, source, source, 1)
    assert source.read_bytes() == b"original"
    assert output.read_bytes() == b"personal file"


def test_full_copy_comparison_rejects_changes_outside_declared_patch(tmp_path):
    source = tmp_path / "source.nds"
    output = tmp_path / "output.nds"
    source.write_bytes(bytes(200))
    changed = bytearray(200)
    changed[70:74] = b"test"
    output.write_bytes(changed)
    trial.verify_copy(source, output, [(70, b"test")])
    changed[155] = 1
    output.write_bytes(changed)
    with pytest.raises(ValueError, match="Unexpected bytes"):
        trial.verify_copy(source, output, [(70, b"test")])
