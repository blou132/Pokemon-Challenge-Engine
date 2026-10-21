"""Collect corresponding MSYS2 source packages, with signature status and hashes."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request


def fetch(name, msys_root, output, server, curl):
    url = server.rstrip("/") + "/" + name
    target = output / name
    def download(address, path, *, missing_ok=False):
        if curl:
            temporary = path.with_name(path.name + ".partial")
            result = subprocess.run([str(curl), "--fail", "--location", "--silent", "--show-error",
                "--proto", "=https", "--connect-timeout", "30", "--max-time", "1200",
                "--write-out", "%{http_code}", "--output", str(temporary), address],
                capture_output=True, text=True, timeout=1220)
            if result.returncode:
                if missing_ok and result.stdout == "404":
                    return False
                raise ValueError(f"HTTPS source download failed ({result.returncode}): {address}: {result.stderr}")
            temporary.rename(path)
        else:
            with urllib.request.urlopen(address, timeout=120) as response, path.open("xb") as handle:
                while block := response.read(1024 * 1024):
                    handle.write(block)
        return True
    if not target.exists():
        download(url, target)
    signature = target.with_name(target.name + ".sig")
    try:
        if not signature.exists():
            if not download(url + ".sig", signature, missing_ok=True):
                raise urllib.error.HTTPError(url + ".sig", 404, "Not found", {}, None)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        status = "No detached source signature published (HTTP 404)"
    else:
        def msys_path(path):
            path = path.resolve()
            return "/" + path.drive[0].lower() + path.as_posix()[2:] if path.drive else str(path)
        verification = subprocess.run([str(msys_root / "usr/bin/gpgv.exe"), "--keyring",
            msys_path(msys_root / "etc/pacman.d/gnupg/pubring.gpg"), msys_path(signature), msys_path(target)],
            capture_output=True, text=True, timeout=120)
        status = "verified" if verification.returncode == 0 else "unverified"
        (output / (name + ".verification.txt")).write_text(verification.stderr, encoding="utf-8")
        if verification.returncode:
            raise ValueError(f"Source signature verification failed for {name}")
    with target.open("rb") as handle:
        sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"name": name, "url": url, "sha256": sha256, "size": target.stat().st_size, "signature": status}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--msys-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--server", default="https://repo.msys2.org/mingw/sources/")
    parser.add_argument("--curl", type=Path, help="Use an existing TLS-validating curl when Python's certificate store fails")
    parser.add_argument("packages", nargs="+")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as executor:
        sources = list(executor.map(lambda name: fetch(name, args.msys_root, args.output, args.server, args.curl), args.packages))
    (args.output / "sources.json").write_text(json.dumps({"sources": sources}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(sources, indent=2))
