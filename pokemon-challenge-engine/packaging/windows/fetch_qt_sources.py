"""Download exact Qt sources from Qt's release server and verify published SHA256."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request


VERSION = "6.11.2"
BASE = f"https://download.qt.io/official_releases/qt/6.11/{VERSION}/submodules/"
URLS = [BASE + f"{name}-everywhere-src-{VERSION}.tar.xz"
        for name in ("qtbase", "qtsvg", "qtimageformats", "qttranslations")]
URLS.append(f"https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{VERSION}-src/"
            f"pyside-setup-everywhere-src-{VERSION}.tar.xz")


def fetch(url, destination):
    name = url.rsplit("/", 1)[1]
    checksum_url = url + ".sha256"
    with urllib.request.urlopen(checksum_url, timeout=60) as response:
        expected = response.read(4096).decode("ascii").split()[0]
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise ValueError("Invalid checksum from Qt server")
    path = destination / name
    if not path.exists():
        with urllib.request.urlopen(url, timeout=60) as response, path.open("xb") as handle:
            while block := response.read(1024 * 1024):
                handle.write(block)
    with path.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(f"Source checksum mismatch: {name}")
    return {"name": name, "url": url, "checksum_url": checksum_url, "sha256": actual}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as executor:
        sources = list(executor.map(lambda url: fetch(url, args.output), URLS))
    (args.output / "sources.json").write_text(json.dumps({"version": VERSION, "sources": sources}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(sources, indent=2))
