"""Assemble the locally compiled melonDS, DLL closure, notices and source archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

PROJECT = Path(__file__).resolve().parents[1]
COMMIT = "b86390e4428bf38ce4c1ce0e9ca446d6d25955e8"


def sha256(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def fields(path):
    result = {}
    for block in path.read_text(encoding="utf-8").strip().split("\n\n"):
        lines = block.splitlines()
        if lines and lines[0].startswith("%"):
            result[lines[0].strip("%")] = lines[1:]
    return result


def package(source: Path, msys: Path, output: Path) -> dict:
    source, msys, output = source.resolve(), msys.resolve(), output.resolve()
    if output.exists():
        raise ValueError("Le dossier de sortie doit être nouveau pour éviter d'écraser un composant.")
    cache = (source / "build-pce/CMakeCache.txt").read_text(encoding="utf-8")
    if "ENABLE_GDBSTUB:BOOL=OFF" not in cache:
        raise ValueError("Le serveur GDB doit être désactivé dans le build à distribuer.")
    source_info = json.loads((source / "pce-source.json").read_text(encoding="utf-8"))
    if source_info["upstream_revision"] != COMMIT:
        raise ValueError("Source melonDS incompatible.")
    tools = msys / "ucrt64/bin"
    plugins = msys / "ucrt64/share/qt5/plugins"
    if not (plugins / "platforms/qwindows.dll").is_file() or not (tools / "objdump.exe").is_file():
        raise ValueError("Les plugins Qt5 et binutils UCRT64 sont requis.")
    environment = os.environ | {"PATH": str(tools) + os.pathsep + os.environ.get("PATH", "")}
    output.mkdir(parents=True)
    shutil.copy2(source / "build-pce/melonDS.exe", output / "melonDS.exe")
    (output / "platforms").mkdir()
    shutil.copy2(plugins / "platforms/qwindows.dll", output / "platforms/qwindows.dll")
    # These are the installed Windows desktop plugins used by the upstream
    # Widgets/Multimedia/Network frontend. Their imports are resolved below too.
    for category in ("styles", "iconengines", "imageformats", "audio", "mediaservice", "bearer", "playlistformats"):
        if not (plugins / category).is_dir():
            raise ValueError(f"Plugins Qt5 absents : {category}")
        for plugin in (plugins / category).glob("*.dll"):
            (output / category).mkdir(exist_ok=True)
            shutil.copy2(plugin, output / category / plugin.name)
    # Enumerate PE imports, copying only DLLs found in this exact toolchain.
    pending = list(output.rglob("*.dll")) + [output / "melonDS.exe"]
    scanned = set()
    while pending:
        binary = pending.pop()
        if binary in scanned:
            continue
        scanned.add(binary)
        listing = subprocess.check_output([str(tools / "objdump.exe"), "-p", str(binary)],
                                          env=environment, text=True, errors="replace", timeout=30)
        for name in re.findall(r"DLL Name:\s*(\S+)", listing):
            dependency = tools / name
            if dependency.is_file():
                target = output / name
                if not target.exists():
                    shutil.copy2(dependency, target)
                    pending.append(target)
            elif not ((Path(os.environ["SystemRoot"]) / "System32" / name).is_file()
                      or name.lower().startswith(("api-ms-win-", "ext-ms-win-"))):
                raise ValueError(f"Dépendance DLL non résolue : {name}")
    # Identify the exact packages owning all copied DLLs, including Qt plugins.
    copied_hashes = {sha256(path) for path in output.rglob("*.dll")}
    packages = []
    notices = output / "licenses"
    notices.mkdir()
    for folder in sorted((msys / "var/lib/pacman/local").iterdir()):
        if not (folder / "desc").is_file() or not (folder / "files").is_file():
            continue
        description = fields(folder / "desc")
        entries = fields(folder / "files").get("FILES", [])
        owns_binary = False
        for entry in entries:
            if not entry.lower().endswith(".dll"):
                continue
            candidate = msys / entry
            if candidate.is_file() and sha256(candidate) in copied_hashes:
                owns_binary = True
                break
        if not owns_binary:
            continue
        name = description["NAME"][0]
        base = description.get("BASE", [name])[0]
        version = description["VERSION"][0]
        for entry in entries:
            if "/share/licenses/" in entry and (msys / entry).is_file():
                target = notices / name / Path(entry).relative_to("ucrt64/share/licenses")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(msys / entry, target)
        source_url = f"https://repo.msys2.org/mingw/sources/{base}-{version}.src.tar.zst"
        packages.append({"name": name, "base": base, "version": version,
                         "licenses": description.get("LICENSE", []), "source_url": source_url,
                         "upstream_url": description.get("URL", [""])[0]})
    shutil.copy2(source / "LICENSE", output / "LICENSE-melonDS.txt")
    sources = output / "sources"
    sources.mkdir()
    with tarfile.open(sources / "melonDS-1.1-pce.2.tar.gz", "w:gz", compresslevel=6) as archive:
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            if relative.parts[0] == ".git" or relative.parts[0].startswith("build") or not path.is_file():
                continue
            archive.add(path, arcname="melonDS-1.1-pce.2/" + relative.as_posix(), recursive=False)
        for name in ("tools/prepare_melonds_source.py", "tools/build_melonds.ps1", "tools/package_melonds.py",
                     "native/melonds/PCEBridge.h", "native/melonds/PCECommands.h", "native/melonds/PCEWindowCommands.h", "native/melonds/PCEInputPulse.h", "data/memory_profiles.json", "data/tracking_profiles.json",
                     "docs/melonds-bridge.md"):
            archive.add(PROJECT / name, arcname="pce-build/" + name, recursive=False)
    (output / "dependency-sources.json").write_text(json.dumps(packages, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(source / "pce-source.json", output / "pce-source.json")
    shutil.copy2(source / "pce-build.json", output / "pce-build.json")
    (output / "qt.conf").write_text("[Paths]\nPlugins = .\n", encoding="utf-8")
    (output / "BUILD-NOTICE.txt").write_text(
        "melonDS 1.1-pce.2; upstream commit " + COMMIT + "\n"
        "PCE modification: read-only frame snapshots, session-scoped native commands; GDB disabled.\n"
        "GPL-3.0-or-later. Corresponding modified emulator source is in sources/.\n"
        "DLLs are dynamically linked and may be replaced with compatible rebuilt versions.\n"
        "dependency-sources.json lists the exact MSYS2 source packages and license identifiers.\n"
        "Distribute the corresponding dependency source archives alongside this component.\n"
        "No Nintendo ROM, BIOS, firmware or user save is included.\n", encoding="utf-8")
    binaries = {path.relative_to(output).as_posix(): sha256(path) for path in sorted(output.rglob("*"))
                if path.is_file()}
    # Per-run isolation copies this smaller set. Corresponding source archives
    # remain in the component's distribution manifest, not in every user run.
    runtime_files = {name: digest for name, digest in binaries.items() if not name.startswith("sources/")}
    bridge = {"schema_version": 1, "bridge_version": "1.1-pce.2", "upstream_commit": COMMIT,
              "executable": "melonDS.exe", "files": runtime_files}
    (output / "pce-bridge.json").write_text(json.dumps(bridge, indent=2) + "\n", encoding="utf-8")
    component = {"name": "melonDS", "version": "1.1-pce.2",
                 "source_url": "https://github.com/melonDS-emu/melonDS/releases/tag/1.1",
                 "license_file": "LICENSE-melonDS.txt", "files": binaries | {"pce-bridge.json": sha256(output / "pce-bridge.json")}}
    (output / "component-manifest.json").write_text(json.dumps(component, indent=2) + "\n", encoding="utf-8")
    return component


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("msys", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = package(args.source, args.msys, args.output)
    print(json.dumps({"name": result["name"], "version": result["version"], "files": len(result["files"])}))
