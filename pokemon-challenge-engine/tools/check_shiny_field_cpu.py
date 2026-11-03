"""Execute the experimental field patch against original White FR code in Unicorn.

This is a CPU test, not a gameplay or measured-encounter-rate validation. Requires
the optional developer package unicorn, a user-supplied ROM and the pinned ZX JAR.
No ROM, save or live emulator memory is written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

from tools import shiny_field_trial as trial


def verify_native_rng(cpu, arm9, base):
    """Check the original bounded RNG arithmetic at every power-of-two boundary.

    Initial LCG states/constants are supplied explicitly; the original ARM/Thumb
    RNG executes without hooks. This verifies the arithmetic, not how the game
    initializes its live RNG or the frequency of an in-game encounter category.
    """
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP, UC_ARM_REG_LR
    global_pointer = struct.unpack_from("<I", arm9, 0x02005724 - base)[0]
    state, stack, return_to = 0x02302000, 0x023F0000, 0x02002000
    cpu.mem_write(global_pointer + 0x10, struct.pack("<I", state))
    multiplier, increment = 0x5D588B656C078965, 0x269EC3
    inverse = pow(multiplier, -1, 1 << 64)
    results = []
    for denominator in trial.DENOMINATORS:
        width = (1 << 32) // denominator
        boundaries = {value for bucket in range(denominator)
                      for value in (bucket * width, (bucket + 1) * width - 1)}
        for high in sorted(boundaries):
            expected_state = (high << 32) | 0x12345678
            previous = ((expected_state - increment) * inverse) % (1 << 64)
            cpu.mem_write(state, struct.pack("<QQQ", previous, multiplier, increment))
            for register, value in ((UC_ARM_REG_R0, denominator), (UC_ARM_REG_SP, stack),
                                    (UC_ARM_REG_LR, return_to | 1)):
                cpu.reg_write(register, value)
            cpu.emu_start(trial.RNG | 1, return_to, count=1000)
            if (cpu.reg_read(UC_ARM_REG_R0) != (high * denominator) >> 32 or
                    bytes(cpu.mem_read(state, 8)) != struct.pack("<Q", expected_state) or
                    cpu.reg_read(UC_ARM_REG_SP) != stack):
                raise ValueError("Native bounded RNG arithmetic verification failed.")
        results.append({"denominator": denominator, "bucket_boundaries_checked": len(boundaries), "passed": True})
    return {"rng_stubbed": False, "initial_states_supplied": True,
            "formula": "high32(next_state) * denominator >> 32",
            "equal_power_of_two_bucket_widths": True, "results": results}


def verify(rom: Path, java: Path, jar: Path, *, quick=False):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R4, UC_ARM_REG_R5,
                                  UC_ARM_REG_R6, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)

    if trial.sha256(jar) != trial.ZX_JAR_SHA256:
        raise ValueError("Unrecognized ZX codec.")
    before = trial.sha256(rom)
    packed, _ = trial.read_field(rom)
    field = trial.decode_blz(packed, java, jar, trial.FIELD_SIZE)
    signature = field[trial.FUNCTION_START - trial.FIELD_BASE:trial.FUNCTION_END - trial.FIELD_BASE]
    if hashlib.sha256(signature).hexdigest() != trial.FIELD_FUNCTION_SHA256:
        raise ValueError("Unrecognized original field function.")
    raw, metadata = trial.read_arm9(rom)
    raw, compressed, expected, _ = trial.prepare_arm9(raw)
    arm9 = trial.decode_blz(raw, java, jar, expected) if compressed else raw
    if hashlib.sha256(arm9).hexdigest() not in trial.ARM9_SHA256 or metadata["arm9_load_address"] != 0x02004000:
        raise ValueError("Unrecognized ARM9 build.")
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    cpu.mem_map(0x02000000, 0x400000)
    cpu.mem_write(metadata["arm9_load_address"], arm9)
    cpu.mem_write(trial.FIELD_BASE, field)
    native_rng = verify_native_rng(cpu, arm9, metadata["arm9_load_address"])
    trainer, parameters, manager, stack, return_to = 0xEB140DAF, 0x02300000, 0x02301000, 0x023F0000, 0x02002000
    cpu.mem_write(parameters, struct.pack("<H", 246) + bytes(32))
    cpu.mem_write(manager + 0x20, struct.pack("<I", trainer))
    context = {}

    def rng(uc, address, size, user):
        argument = uc.reg_read(UC_ARM_REG_R0)
        context["arguments"].append(argument)
        value = context["roll"] if argument and len(context["arguments"]) == 1 and not context["locked"] else context["raw"]
        uc.reg_write(UC_ARM_REG_R0, value)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    cpu.hook_add(UC_HOOK_CODE, rng, begin=trial.RNG, end=trial.RNG)
    # Recompile the earlier native RNG block with the newly installed hook.
    cpu.ctl_remove_cache(trial.RNG, 0x02005724)
    results = []
    for denominator in trial.DENOMINATORS:
        body = trial.patch_body(denominator)
        cpu.mem_write(trial.ENTRY, body)
        cpu.ctl_remove_cache(trial.ENTRY, trial.END)
        count = 0
        for locked in (False, True):
            for roll in sorted({0, denominator - 1}) if quick else range(denominator):
                for raw_pid in (0, 0xFFFFFFFF, 0x12345678, 0xABCDEF01):
                    context.update(roll=roll, raw=raw_pid, locked=locked, arguments=[])
                    cpu.mem_write(parameters + 6, bytes([2 if locked else 0]))
                    cpu.mem_write(stack + 8, struct.pack("<4I", 0x11111111, 0x22222222, 0x33333333, return_to | 1))
                    for register, value in ((UC_ARM_REG_R4, parameters), (UC_ARM_REG_R5, manager),
                            (UC_ARM_REG_R6, 2), (UC_ARM_REG_SP, stack), (UC_ARM_REG_LR, return_to | 1)):
                        cpu.reg_write(register, value)
                    cpu.emu_start(trial.ENTRY | 1, return_to, count=500)
                    pid = cpu.reg_read(UC_ARM_REG_R0)
                    shiny = ((pid >> 16) ^ (pid & 0xFFFF) ^ (trainer >> 16) ^ (trainer & 0xFFFF)) < 8
                    checks = (
                        shiny == (not locked and roll == 0), pid & 255 == raw_pid & 255,
                        cpu.reg_read(UC_ARM_REG_SP) == stack + 24,
                        cpu.reg_read(UC_ARM_REG_R4) == 0x11111111,
                        cpu.reg_read(UC_ARM_REG_R5) == 0x22222222,
                        cpu.reg_read(UC_ARM_REG_R6) == 0x33333333,
                        context["arguments"] == ([0] if locked else [denominator, 0]),
                    )
                    if not all(checks):
                        raise ValueError(f"CPU verification failed: denominator={denominator}, lock={locked}, roll={roll}.")
                    count += 1
        results.append({"denominator": denominator, "cases": count, "passed": True,
                        "thumb_sha256": hashlib.sha256(body).hexdigest()})
    if trial.sha256(rom) != before:
        raise ValueError("Source changed during CPU verification.")
    return {"schema_version": 1, "kind": "synthetic CPU execution of original White FR functions",
            "source_sha256": before, "source_unchanged": True, "exhaustive_selector": not quick,
            "rng_stubbed": True, "native_rng_arithmetic": native_rng,
            "gameplay_validated": False, "categories_validated": [], "results": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("rom", "java", "jar"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--quick", action="store_true", help="Only selector endpoints; default is exhaustive")
    args = parser.parse_args(argv)
    print(json.dumps(verify(args.rom, args.java, args.jar, quick=args.quick), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
