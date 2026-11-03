"""Exercise the Windows GUI executable without developer environment variables."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def check(executable: Path, output: Path):
    executable = executable.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=False)
    output = output.resolve()
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH"}}
    environment["PATH"] = str(Path(environment["SYSTEMROOT"]) / "System32")
    environment["LOCALAPPDATA"] = str(output / "local-app-data")
    environment["APPDATA"] = str(output / "app-data")
    data = output / "données de contrôle"
    reports = []
    with tempfile.TemporaryDirectory(prefix="PCE-isolated-cwd-") as directory:
        for name in ("first", "reopened"):
            report = output / (name + ".json")
            result = subprocess.run([str(executable), "--data-dir", str(data), "--self-test", str(report)],
                                    cwd=directory, env=environment, timeout=90)
            if result.returncode or not report.is_file():
                raise ValueError(f"Packaged check failed ({result.returncode}), inspect {data / 'logs'}")
            content = json.loads(report.read_text(encoding="utf-8"))
            if content.get("ok") is not True or content.get("frozen") is not True or content.get("reopened") != (name == "reopened"):
                raise ValueError("Executable validation did not match the required checks")
            reports.append(content)
        if reports[0]["run_id"] != reports[1]["run_id"]:
            raise ValueError("Run identity changed across executable restarts")
    with executable.open("rb") as handle:
        sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
    summary = {"exe": str(executable), "sha256": sha256, "ok": True, "launches": 2,
               "pythonpath_present": False, "developer_path_present": False,
               "working_directory": "new Windows TEMP directory outside the checkout",
               "tested": ["real Qt window and navigation", "packaged catalogs and Lua and Java source",
                          "run creation and independent reread", "preferences", "same run and badges after restart"],
               "not_tested": ["fresh Windows OS installation", "game/emulator execution", "portable marker end-to-end"]}
    if all(report.get("bundled_randomizer", {}).get("verified") for report in reports):
        summary["tested"].append("bundled Java compiler and official ZX discovered without local configuration")
    if all(report.get("shiny_resources", {}).get("imported") for report in reports):
        summary["tested"].append("shiny patch modules and Java encoder/decoder available in the executable")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    check(args.exe, args.output)
