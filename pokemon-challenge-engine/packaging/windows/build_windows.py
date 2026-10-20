"""Build only in a local venv; package allowlisted resources, never a user's installation."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile


PROJECT = Path(__file__).resolve().parents[2]
NAME = "Pokemon-Challenge-Engine"


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def component_files(component: Path) -> tuple[dict, list[Path]]:
    from app.services.discovery_safety import local_path
    component = local_path(component)
    manifest = json.loads(local_path(component / "component-manifest.json").read_text(encoding="utf-8"))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", manifest.get("name", "")) or not manifest.get("version"):
        raise ValueError("Component identity is missing")
    if not str(manifest.get("source_url", "")).startswith("https://") or not isinstance(manifest.get("files"), dict):
        raise ValueError("Component source URL and SHA256 inventory are mandatory")
    if manifest.get("license_file") not in manifest["files"]:
        raise ValueError("The component license must be included and hashed")
    files = []
    for name, expected in manifest["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or ":" in name or "\\" in name:
            raise ValueError("Unsafe component path")
        path = local_path(component / relative)
        if not path.is_file() or not re.fullmatch(r"[a-f0-9]{64}", expected) or digest(path) != expected:
            raise ValueError(f"Component file failed verification: {name}")
        if path.suffix.lower() in {".nds", ".gba", ".sav", ".dsv", ".dst", ".bin", ".rom"}:
            raise ValueError("ROM, firmware and save files cannot be distributed")
        files.append(path)
    return manifest, files


def build(output: Path, components: list[Path], qt_sources: Path):
    if sys.platform != "win32" or sys.prefix == sys.base_prefix:
        raise ValueError("Build on Windows using a project-local virtual environment")
    if importlib.metadata.version("pyinstaller") != "6.22.3":
        raise ValueError("Install the pinned packaging/windows/requirements-build.txt first")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    work = output / "build"
    work.mkdir()
    from app import __version__
    from app.main import application_icon
    from PySide6.QtWidgets import QApplication
    application = QApplication.instance() or QApplication([])
    icon = work / "pce.ico"
    if not application_icon().pixmap(256, 256).save(str(icon), "ICO"):
        raise ValueError("Could not create original application icon")
    version = tuple(int(part) for part in __version__.split("."))
    version = (version + (0, 0, 0, 0))[:4]
    version_file = work / "version.txt"
    version_file.write_text(
        "VSVersionInfo(ffi=FixedFileInfo(filevers=" + repr(version) + ", prodvers=" + repr(version) + "), "
        "kids=[StringFileInfo([StringTable('040904B0', ["
        f"StringStruct('FileDescription', '{NAME}'), StringStruct('ProductName', '{NAME}'), "
        f"StringStruct('FileVersion', '{__version__}'), StringStruct('ProductVersion', '{__version__}'), "
        f"StringStruct('OriginalFilename', '{NAME}.exe')])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])",
        encoding="utf-8")
    # Strict resource suffixes avoid copying local ROMs, DLLs, JARs, configs or caches.
    resources = []
    for folder, suffixes in (("data", {".json", ".md"}), ("lua", {".lua", ".md"}),
                             ("tools/randomizer", {".java", ".md"})):
        for path in sorted((PROJECT / folder).rglob("*")):
            if path.is_file() and (path.suffix in suffixes or path.name == "COPYING"):
                resources.extend(["--add-data", str(path) + ":" + str(path.parent.relative_to(PROJECT))])
    command = [sys.executable, "-m", "PyInstaller", "--onedir", "--windowed", "--noupx", "--clean",
               "--name", NAME, "--paths", str(PROJECT), "--distpath", str(output / "dist"),
               "--workpath", str(work / "pyinstaller"), "--specpath", str(work),
               "--icon", str(icon), "--version-file", str(version_file), *resources,
               "--additional-hooks-dir", str(PROJECT / "packaging/windows/hooks"),
               str(PROJECT / "packaging/windows/entrypoint.py")]
    subprocess.run(command, cwd=PROJECT, check=True)
    bundle = output / "dist" / NAME
    covered_qt = {"Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "Qt6Network.dll", "Qt6OpenGL.dll", "Qt6Svg.dll"}
    uncovered = {path.name for path in (bundle / "_internal").rglob("Qt6*.dll")} - covered_qt
    if uncovered:
        raise ValueError(f"Additional Qt modules need corresponding sources and licensing review: {sorted(uncovered)}")
    for name in ("Create-Desktop-Shortcut.vbs", "Enable-Portable-Mode.vbs", "LISEZ-MOI.txt", "THIRD-PARTY-NOTICES.txt"):
        shutil.copy2(PROJECT / "packaging/windows" / name, bundle / name)
    (bundle / "licenses").mkdir()
    source_manifest = json.loads((qt_sources / "sources.json").read_text(encoding="utf-8"))
    if source_manifest.get("version") != importlib.metadata.version("PySide6"):
        raise ValueError("Qt source version does not match the runtime")
    version = source_manifest["version"]
    expected_sources = {f"{name}-everywhere-src-{version}.tar.xz"
                        for name in ("qtbase", "qtsvg", "qtimageformats", "qttranslations", "pyside-setup")}
    if {source["name"] for source in source_manifest["sources"]} != expected_sources:
        raise ValueError("The required corresponding Qt sources are incomplete")
    source_destination = bundle / "third-party-sources"
    source_destination.mkdir()
    shutil.copy2(qt_sources / "sources.json", source_destination / "sources.json")
    for source in source_manifest["sources"]:
        name = source["name"]
        if Path(name).name != name or not name.endswith(".tar.xz"):
            raise ValueError("Invalid Qt source archive name")
        path = qt_sources / name
        if digest(path) != source["sha256"]:
            raise ValueError("Qt source archive checksum mismatch")
        shutil.copy2(path, source_destination / name)
        # Copy notices only; never extract executable or arbitrary archive paths.
        with tarfile.open(path, "r:xz") as archive:
            for member in archive:
                relative = Path(member.name)
                if member.isfile() and ("LICENSES" in relative.parts or relative.name.upper().startswith(("LICENSE", "COPYING"))):
                    if relative.is_absolute() or ".." in relative.parts or member.size > 2_000_000:
                        raise ValueError("Unsafe license entry")
                    target = bundle / "licenses" / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as reader, target.open("xb") as writer:
                        shutil.copyfileobj(reader, writer)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise ValueError("Python runtime license is missing")
    shutil.copy2(python_license, bundle / "licenses/Python-LICENSE.txt")
    packages = ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "pyinstaller")
    for package in packages:
        distribution = importlib.metadata.distribution(package)
        for item in distribution.files or ():
            if ".dist-info/licenses/" in str(item):
                target = bundle / "licenses" / package / Path(str(item).split("/licenses/", 1)[1])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(distribution.locate_file(item), target)
    # Ship editable application source and exact build recipe for LGPL relinking.
    for folder, suffixes in (("app", {".py"}), ("data", {".json", ".md"}), ("lua", {".lua", ".md"}),
                             ("packaging/windows", {".py", ".txt", ".vbs"}), ("tools/randomizer", {".java", ".md"})):
        for path in sorted((PROJECT / folder).rglob("*")):
            if path.is_file() and (path.suffix in suffixes or path.name == "COPYING"):
                target = bundle / "application-source" / path.relative_to(PROJECT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    (bundle / "application-source/docs").mkdir(exist_ok=True)
    shutil.copy2(PROJECT / "docs/windows-distribution.md", bundle / "application-source/docs/windows-distribution.md")
    bundled_components = []
    for component in components:
        component = component.resolve()
        manifest, files = component_files(component)
        target_root = bundle / "third-party" / manifest["name"]
        target_root.mkdir(parents=True, exist_ok=False)
        for source in files:
            target = target_root / source.relative_to(component)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        shutil.copy2(component / "component-manifest.json", target_root / "component-manifest.json")
        bundled_components.append({key: manifest[key] for key in ("name", "version", "source_url", "license_file")})
    forbidden = {".nds", ".gba", ".sav", ".dsv", ".dst", ".rom"}
    if any(path.suffix.lower() in forbidden or path.name in {"config.json", "run.json", "progress.json"}
           for path in bundle.rglob("*") if path.is_file()):
        raise ValueError("Personal game data detected in bundle")
    manifest = {"name": NAME, "version": __version__, "python": sys.version,
                "build_packages": {name: importlib.metadata.version(name) for name in packages},
                "components": bundled_components,
                "files": {path.relative_to(bundle).as_posix(): digest(path) for path in sorted(bundle.rglob("*")) if path.is_file()}}
    (bundle / "distribution-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    archive = output / f"{NAME}-{__version__}-windows-x64.zip"
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as handle:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                handle.write(path, path.relative_to(bundle.parent))
    (archive.with_suffix(".zip.sha256")).write_text(digest(archive) + "  " + archive.name + "\n", encoding="ascii")
    print(json.dumps({"exe": str(bundle / (NAME + ".exe")), "zip": str(archive), "sha256": digest(archive)}, indent=2))


if __name__ == "__main__":
    sys.path.insert(0, str(PROJECT))
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True, help="New output directory; existing output is never removed")
    parser.add_argument("--component", type=Path, action="append", default=[])
    parser.add_argument("--qt-sources", type=Path, required=True)
    args = parser.parse_args()
    build(args.output, args.component, args.qt_sources)
