"""Local structured setup events; never records ROM/save contents."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading

from app.services.config_service import _invalid_constant, _strict_pairs
from app.services.discovery_safety import local_path


class InstallationJournal:
    def __init__(self, base_dir: Path):
        self.path = local_path(Path(base_dir) / "runtime" / "installation" / "events.jsonl")
        self._lock = threading.RLock()
        self.warnings: list[str] = []

    def __call__(self, event: str, **details):
        if not isinstance(event, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,99}", event):
            raise ValueError("Nom d'événement d'installation invalide.")
        # Callers supply only diagnostic paths, identities, hashes and outcomes.
        record = {"time": datetime.now(timezone.utc).isoformat(), "event": event,
                  "details": details}
        payload = json.dumps(record, ensure_ascii=False, default=str, allow_nan=False)
        if len(payload.encode("utf-8")) > 65536:
            raise ValueError("Événement d'installation trop volumineux.")
        with self._lock:
            local_path(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > 5_000_000:
                # One previous local log, no growing unbounded installation history.
                self.path.replace(local_path(self.path.with_name("events.previous.jsonl")))
            separator = ""
            if self.path.exists() and self.path.stat().st_size:
                with self.path.open("rb") as handle:
                    handle.seek(-1, os.SEEK_END)
                    separator = "" if handle.read(1) == b"\n" else "\n"
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(separator + payload + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def recent(self, count=100):
        if type(count) is not int or not 1 <= count <= 1000:
            raise ValueError("Nombre d'événements demandé invalide.")
        self.warnings.clear()
        with self._lock:
            local_path(self.path)
            if not self.path.exists():
                return []
            with self.path.open("rb") as handle:
                length = self.path.stat().st_size
                start = max(0, length - 5_100_000)
                handle.seek(start)
                if start:
                    handle.readline(65537)  # Ne jamais traiter un fragment initial comme événement.
                lines = handle.read(5_100_000).splitlines()
        events = []
        for line in lines:
            try:
                if len(line) > 65536:
                    raise ValueError("Ligne trop volumineuse")
                record = json.loads(line.decode("utf-8"), object_pairs_hook=_strict_pairs, parse_constant=_invalid_constant)
                if not isinstance(record, dict) or set(record) != {"time", "event", "details"} or \
                        not isinstance(record["time"], str) or not isinstance(record["event"], str) or \
                        not isinstance(record["details"], dict):
                    raise ValueError("Événement invalide")
                events.append(record)
            except (ValueError, UnicodeError, RecursionError):
                self.warnings[:] = ["Certaines lignes du journal sont incomplètes ou illisibles ; elles ont été conservées."]
        if self.warnings:
            events.append({"time": datetime.now(timezone.utc).isoformat(), "event": "journal_warning",
                           "details": {"message": self.warnings[0]}})
        return events[-count:]
