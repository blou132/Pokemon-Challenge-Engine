"""Apply the small read-only bridge to an exact, clean upstream checkout.

Use the upstream GPL source and the shipped PCE files together as corresponding
source. Generated addresses come exclusively from the existing memory profiles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

UPSTREAM_REVISION = "b86390e4428bf38ce4c1ce0e9ca446d6d25955e8"
PROJECT = Path(__file__).resolve().parents[1]


def patch_qt5_metatypes(source: Path) -> None:
    """Qt5 needs explicit registration for the existing cheat-dialog pointers."""
    header = Path(source) / "src/frontend/qt_sdl/CheatImportDialog.h"
    original = header.read_bytes()
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    marker = b"namespace Ui { class CheatImportDialog; }"
    if original.count(marker) != 1 or b"Q_DECLARE_METATYPE(melonDS::ARCode*)" in original:
        raise ValueError("Point d'insertion des metatypes Qt5 inattendu.")
    addition = newline.join((
        b"// Qt5 requires these explicit pointer metatypes; Qt6 registers them automatically.",
        b"#if QT_VERSION < QT_VERSION_CHECK(6, 0, 0)",
        b"Q_DECLARE_METATYPE(melonDS::ARCode*)",
        b"Q_DECLARE_METATYPE(melonDS::ARCodeCat*)",
        b"Q_DECLARE_METATYPE(melonDS::ARDatabaseEntry*)",
        b"#endif", b"", marker,
    ))
    header.write_bytes(original.replace(marker, addition))


def patch_commands(source: Path, project: Path = PROJECT) -> None:
    """Add session commands through existing native UI/thread APIs."""
    target = Path(source) / "src/frontend/qt_sdl"

    def replace(name, before, after):
        path = target / name
        original = path.read_bytes()
        newline = b"\r\n" if b"\r\n" in original else b"\n"
        old = before.encode().replace(b"\n", newline)
        new = after.encode().replace(b"\n", newline)
        if original.count(old) != 1:
            raise ValueError(f"Point d'insertion des commandes melonDS inattendu : {name}")
        path.write_bytes(original.replace(old, new))

    replace("Window.h", "    void toggleFullscreen();", "    void toggleFullscreen();\n    void startPCECommands();")
    replace("Window.cpp", "    updateMPInterface(MPInterface::GetType());\n}",
            "    updateMPInterface(MPInterface::GetType());\n    startPCECommands();\n}")
    with (target / "Window.cpp").open("ab") as handle:
        handle.write(b'\n#include "PCEWindowCommands.h"\n')
    replace("EmuInstance.h", "    int getInstanceID() { return instanceID; }",
            "    QString pceRomHash;\n    unsigned long long pceCartGeneration = 0;\n    int getInstanceID() { return instanceID; }")
    replace("EmuInstance.cpp", '#include "EmuInstance.h"', '#include "EmuInstance.h"\n#include <QCryptographicHash>')
    replace("EmuInstance.cpp", "bool EmuInstance::loadROM(QStringList filepath, bool reset, QString& errorstr)\n{",
            "bool EmuInstance::loadROM(QStringList filepath, bool reset, QString& errorstr)\n{\n    ++pceCartGeneration;")
    replace("EmuInstance.cpp", "void EmuInstance::ejectCart()\n{", "void EmuInstance::ejectCart()\n{\n    ++pceCartGeneration;")
    replace("EmuInstance.cpp", "    auto cart = NDSCart::ParseROM(std::move(filedata), filelen, this, std::move(cartargs));",
            '    pceRomHash = QString::fromLatin1(QCryptographicHash::hash(QByteArray::fromRawData(reinterpret_cast<const char*>(filedata.get()), filelen), QCryptographicHash::Sha256).toHex());\n'
            "    auto cart = NDSCart::ParseROM(std::move(filedata), filelen, this, std::move(cartargs));")
    replace("EmuInstance.h", '#include "EmuThread.h"', '#include "EmuThread.h"\n#include "PCEInputPulse.h"')
    replace("EmuInstance.h", "    QString pceRomHash;", "    PCEInputPulse pceInputPulse;\n    QString pceRomHash;")
    replace("EmuThread.cpp", "            emuInstance->nds->SetKeyMask(emuInstance->inputMask);",
            "            emuInstance->nds->SetKeyMask(emuInstance->pceInputPulse.apply(emuInstance->inputMask, SDL_GetTicks64()));")
    replace("EmuThread.cpp", "                nlines = emuInstance->nds->RunFrame();",
            "                nlines = emuInstance->nds->RunFrame();\n                emuInstance->pceInputPulse.afterFrame();")
    for name in ("PCECommands.h", "PCEWindowCommands.h", "PCEInputPulse.h"):
        shutil.copy2(project / "native/melonds" / name, target / name)


def prepare(source: Path, project: Path = PROJECT) -> None:
    source = Path(source).resolve()
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != UPSTREAM_REVISION:
        raise ValueError("Le commit melonDS doit être exactement celui de la version 1.1 épinglée.")
    status = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True)
    if status:
        raise ValueError("Le code source melonDS contient déjà des modifications ; utiliser une copie propre.")
    target = source / "src/frontend/qt_sdl"
    thread = target / "EmuThread.cpp"
    original = thread.read_bytes()
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    include = b'#include "EmuInstance.h"'
    call = b"                nlines = emuInstance->nds->RunFrame();"
    if original.count(include) != 1 or original.count(call) != 1:
        raise ValueError("Points d'insertion melonDS inattendus.")
    profiles = json.loads((project / "data/memory_profiles.json").read_text(encoding="utf-8"))
    tracking = json.loads((project / "data/tracking_profiles.json").read_text(encoding="utf-8"))
    entries = []
    for profile in profiles:
        count, party = profile["party_count_address"], profile["party_address"]
        if (profile["pokemon_size"] != 220 or not 0x02000000 <= count < 0x02400000
                or not 0x02000000 <= party <= 0x02400000 - 6 * 220):
            raise ValueError("Profil mémoire hors des limites de la RAM DS.")
        tracked = next((item for item in tracking if (item["game_code"], item["revision"]) ==
                        (profile["game_code"], profile["revision"])), None)
        map_address = (tracked or {}).get("map_id_address") or 0
        if map_address and (tracked["map_id_size"] != 2 or not 0x02000000 <= map_address <= 0x023FFFFE):
            raise ValueError("Adresse de carte non prise en charge.")
        entries.append("    {" + ", ".join((json.dumps(profile["id"]), json.dumps(profile["game_code"]),
                       str(profile["revision"]), hex(count), hex(party), hex(map_address))) + "},")
    generated = ("// Generated by tools/prepare_melonds_source.py from PCE JSON profiles.\n#pragma once\n"
                 "namespace PCEBridge {\nstruct Profile { const char* id; const char* code; int revision; "
                 "unsigned countAddress; unsigned partyAddress; unsigned mapAddress; };\n"
                 "inline constexpr Profile Profiles[] = {\n" + "\n".join(entries) + "\n};\n}\n")
    (target / "PCEProfiles.h").write_text(generated, encoding="utf-8")
    shutil.copy2(project / "native/melonds/PCEBridge.h", target / "PCEBridge.h")
    patched = original.replace(include, include + newline + b'#include "PCEBridge.h"')
    patched = patched.replace(call, call + newline +
                             b"                PCEBridge::PublishFrame(*emuInstance->nds, emuInstance->getInstanceID());")
    thread.write_bytes(patched)
    patch_qt5_metatypes(source)
    patch_commands(source, project)
    manifest = {
        "bridge_version": "1.1-pce.2", "upstream_revision": UPSTREAM_REVISION,
        "upstream_release": "https://github.com/melonDS-emu/melonDS/releases/tag/1.1",
        "license": "GPL-3.0-or-later", "read_only": False, "memory_reader_read_only": True,
        "transport": "atomic-file-v1", "ram_writes": False, "gdb_enabled": False,
        "commands": "session-mailbox-v1", "state_api": "native-serialized",
        "source_files": {name: hashlib.sha256((project / name).read_bytes()).hexdigest() for name in (
            "native/melonds/PCEBridge.h", "native/melonds/PCECommands.h",
            "native/melonds/PCEWindowCommands.h", "native/melonds/PCEInputPulse.h", "tools/prepare_melonds_source.py",
            "data/memory_profiles.json", "data/tracking_profiles.json")},
    }
    (source / "pce-source.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    prepare(parser.parse_args().source)
