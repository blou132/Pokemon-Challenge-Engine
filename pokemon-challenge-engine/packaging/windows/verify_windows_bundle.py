"""Verify every portable ZIP entry before extracting into a new directory.

This checks artifact integrity and exclusions, not gameplay or publisher identity.
The manifest is produced by build_windows.py and must travel with the ZIP.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile


def _builder():
    spec = importlib.util.spec_from_file_location("pce_bundle_builder", Path(__file__).with_name("build_windows.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _relative(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or ".." in path.parts or ":" in name or "\\" in name
            or path.as_posix() != name or any(part.endswith((".", " ")) for part in path.parts)
            or any(re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
                   for part in path.parts)):
        raise ValueError(f"Unsafe archive path: {name}")
    return path


def verify(archive: Path, extract_to: Path | None = None) -> dict:
    archive = archive.resolve(strict=True)
    builder = _builder()
    prefix = builder.NAME + "/"
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        normalized = set()
        names = set()
        for entry in entries:
            path = _relative(entry.filename)
            folded = path.as_posix().casefold()
            if folded in normalized or not entry.filename.startswith(prefix):
                raise ValueError("Duplicate archive path or unexpected root")
            if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("Only regular file entries are supported")
            normalized.add(folded)
            names.add(entry.filename)
            if builder.forbidden_distribution_path(Path(*path.parts[1:])):
                raise ValueError(f"Personal game data in distribution: {entry.filename}")
        manifest_name = prefix + "distribution-manifest.json"
        if manifest_name not in names or zipped.getinfo(manifest_name).file_size > 20_000_000:
            raise ValueError("Distribution manifest missing or oversized")
        manifest = json.loads(zipped.read(manifest_name))
        files = manifest.get("files")
        if manifest.get("name") != builder.NAME or not isinstance(files, dict) or not files:
            raise ValueError("Invalid distribution manifest")
        for name, expected in files.items():
            _relative(name)
            if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
                raise ValueError("Invalid file checksum")
        if names != {prefix + name for name in files} | {manifest_name}:
            raise ValueError("ZIP entries differ from the manifest inventory")
        for name, expected in files.items():
            with zipped.open(prefix + name) as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != expected:
                raise ValueError(f"File checksum mismatch: {name}")
        components = {}
        for component in manifest.get("components", []):
            name = component["name"]
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", name) or name in components:
                raise ValueError("Invalid component identity")
            base = f"third-party/{name}/"
            component_manifest = json.loads(zipped.read(prefix + base + "component-manifest.json"))
            if component_manifest.get("name") != name or not isinstance(component_manifest.get("files"), dict):
                raise ValueError("Component manifest identity mismatch")
            if component_manifest.get("license_file") not in component_manifest["files"]:
                raise ValueError("Component license missing")
            for relative, expected in component_manifest["files"].items():
                _relative(relative)
                if files.get(base + relative) != expected:
                    raise ValueError(f"Component checksum mismatch: {name}/{relative}")
            components[name] = len(component_manifest["files"])
        if extract_to is not None:
            extract_to = extract_to.resolve()
            extract_to.mkdir(parents=True, exist_ok=False)
            for entry in entries:
                destination = extract_to.joinpath(*PurePosixPath(entry.filename).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(entry) as source, destination.open("xb") as target:
                    shutil.copyfileobj(source, target)
    return {
        "ok": True, "zip": str(archive), "zip_sha256": builder.digest(archive),
        "zip_bytes": archive.stat().st_size, "version": manifest.get("version"),
        "source_commit": manifest.get("source_commit"), "source_dirty": manifest.get("source_dirty"),
        "files_verified": len(files), "components_verified": components,
        "forbidden_files": [], "zip_crc_and_sha256_ok": True,
        "extracted_exe": str(extract_to / builder.NAME / (builder.NAME + ".exe")) if extract_to else None,
        "game_or_emulator_launched": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", dest="archive", required=True, type=Path)
    parser.add_argument("--extract-to", type=Path, help="A new directory; existing data are never replaced")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify(args.archive, args.extract_to)
    serialized = json.dumps(report, indent=2) + "\n"
    if args.report:
        with args.report.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    print(serialized)
