"""Prepare pinned, redistributable Temurin/ZX tools without global installation."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import zipfile


RELEASE = "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/"
DOWNLOADS = (
    ("OpenJDK21U-jdk_x64_windows_hotspot_21.0.12.1_1.zip",
     RELEASE + "OpenJDK21U-jdk_x64_windows_hotspot_21.0.12.1_1.zip",
     "f9d6e191ab098c0d416e7d588a24420a8621cd2f4720dab2459b8b7b2d2d8b4e"),
    ("OpenJDK21U-jdk-sources_21.0.12.1_1.tar.gz",
     RELEASE + "OpenJDK21U-jdk-sources_21.0.12.1_1.tar.gz",
     "573057d03584ae793fb7ec9a14c76d826d9187a53efeefd99da47403a5308234"),
    ("zx-7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c.zip",
     "https://codeload.github.com/Ajarmar/universal-pokemon-randomizer-zx/zip/7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c",
     "7ec3214e6ca7b89dfb8d6a988021f11afc5326e32ce950503c42b9fc40a50ff1"),
)
ZX_SHA256 = "380dc1e6c704a9a4ed8433e8b7892a149390f8912b9107a2a0e7263cfd71c7d8"


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def download(item, cache, curl):
    name, url, expected = item
    target = cache / name
    if not target.exists():
        temporary = target.with_suffix(target.suffix + ".partial")
        subprocess.run([str(curl), "--fail", "--location", "--silent", "--show-error", "--proto", "=https",
                        "--connect-timeout", "30", "--max-time", "1800", "--output", str(temporary), url],
                       check=True, timeout=1820)
        if digest(temporary) != expected:
            raise ValueError(f"Downloaded checksum mismatch: {name}")
        temporary.rename(target)
    if digest(target) != expected:
        raise ValueError(f"Cached checksum mismatch: {name}")
    return target


def prepare(output, cache, curl, zx_jar):
    if not curl.is_file() or not zx_jar.is_file() or digest(zx_jar) != ZX_SHA256:
        raise ValueError("Select an existing TLS-validating curl and the official ZX 4.6.1 JAR")
    cache.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as executor:
        downloads = list(executor.map(lambda item: download(item, cache, curl), DOWNLOADS))
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(downloads[0]) as archive:
        prefixes = {Path(item.filename).parts[0] for item in archive.infolist() if item.filename}
        if len(prefixes) != 1:
            raise ValueError("Unexpected JDK archive layout")
        for item in archive.infolist():
            relative = Path(item.filename)
            if relative.is_absolute() or ".." in relative.parts or ":" in item.filename or "\\" in item.filename:
                raise ValueError("Unsafe JDK archive entry")
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("JDK archive links are not accepted")
            target = output / "jdk" / Path(*relative.parts[1:])
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as reader, target.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
    shutil.copy2(zx_jar, output / "PokeRandoZX.jar")
    (output / "sources").mkdir()
    for source in downloads[1:]:
        shutil.copy2(source, output / "sources" / source.name)
    (output / "licenses").mkdir()
    with zipfile.ZipFile(downloads[2]) as archive:
        license_entries = [item for item in archive.infolist()
                           if item.filename == "universal-pokemon-randomizer-zx-7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c/LICENSE.txt"]
        if len(license_entries) != 1:
            raise ValueError("ZX license source missing or ambiguous")
        (output / "licenses/ZX-COPYING.txt").write_bytes(archive.read(license_entries[0]))
    notice = (
        "PCE portable Randomizer tools\n\n"
        "Eclipse Temurin OpenJDK 21.0.12.1+1, Windows x64 HotSpot.\n"
        "GPL version 2 with Classpath Exception; all original JDK notices remain in jdk/legal.\n"
        "The full corresponding Temurin source archive is included in sources.\n"
        "Binary and source SHA256 were checked against the official Adoptium release metadata.\n"
        "https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.12.1%2B1\n\n"
        "Universal Pokemon Randomizer ZX 4.6.1, GPL-3.0. Source commit:\n"
        "7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c. Full source and LICENSE.txt are included.\n"
        "https://github.com/Ajarmar/universal-pokemon-randomizer-zx/releases/tag/v4.6.1\n"
        "ZX JAR and source archive hashes are pinned observations from official HTTPS assets, not author signatures.\n\n"
        "No Oracle JDK, game ROM, Nintendo firmware or user save is included.\n"
        "These tools are installed only inside this portable application directory.\n"
        "PCE discovers third-party/randomizer/jdk/bin/java.exe and PokeRandoZX.jar.\n"
    )
    (output / "NOTICE.txt").write_text(notice, encoding="utf-8")
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE"}}
    environment["PATH"] = str(Path(environment["SYSTEMROOT"]) / "System32")
    java = output / "jdk/bin/java.exe"
    verification = []
    for arguments in (["-version"], ["--describe-module", "jdk.compiler"]):
        result = subprocess.run([str(java.resolve()), *arguments], cwd=output, env=environment,
                                check=True, capture_output=True, text=True, timeout=30)
        verification.append({"arguments": arguments, "stdout": result.stdout, "stderr": result.stderr})
    if "21.0.12.1" not in verification[0]["stderr"] or not verification[1]["stdout"].startswith("jdk.compiler@21.0.12.1"):
        raise ValueError("The portable Java version or compiler module did not match the expected distribution")
    (output / "verification.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    (output / "download-provenance.json").write_text(json.dumps({"downloads": [
        {"name": name, "url": url, "sha256": sha} for name, url, sha in DOWNLOADS],
        "zx_jar_sha256": ZX_SHA256}, indent=2) + "\n", encoding="utf-8")
    manifest = {"name": "randomizer", "version": "temurin-21.0.12.1+1-zx-4.6.1",
                "source_url": "https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.12.1%2B1",
                "license_file": "licenses/ZX-COPYING.txt",
                "files": {path.relative_to(output).as_posix(): digest(path)
                          for path in sorted(output.rglob("*")) if path.is_file()}}
    (output / "component-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"component": str(output.resolve()), "files": len(manifest["files"]),
                      "version": manifest["version"], "compiler_verified": True}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--curl", type=Path, required=True)
    parser.add_argument("--zx-jar", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.output.resolve(), args.cache.resolve(), args.curl.resolve(), args.zx_jar.resolve())
