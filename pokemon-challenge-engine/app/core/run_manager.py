"""Atomic, optimistic persistence for runs, isolated from profiles and game saves."""

from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from uuid import uuid4

from app.core.profile_manager import _invalid_constant, _strict_pairs
from app.models.challenge import Challenge
from app.models.run import Run, history_event, utc_now, validate_run_id
from app.services.discovery_safety import local_path


MAX_RUN_BYTES = 32 * 1024 * 1024
_locks: dict[Path, RLock] = {}
_locks_guard = RLock()
_IMMUTABLE = ("run_id", "schema_version", "game_id", "generation", "rules_snapshot",
              "profile_id", "preset", "seed", "created_at")


class RunManager:
    def __init__(self, root: Path):
        self.root = local_path(root)
        self.warnings: list[str] = []
        self._active_version: str | None = None
        self._active_loaded = False
        with _locks_guard:
            self._lock = _locks.setdefault(self.root, RLock())

    def _directory(self, run_id: str) -> Path:
        validate_run_id(run_id)
        return local_path(self.root / run_id)

    def _file(self, run_id: str) -> Path:
        return local_path(self._directory(run_id) / "run.json")

    @contextmanager
    def _writing(self):
        """The OS releases this lock on crash; its harmless local file may remain."""
        with self._lock:
            local_path(self.root).mkdir(parents=True, exist_ok=True)
            path = local_path(self.root / ".runs.lock")
            with path.open("a+b") as handle:
                if path.stat().st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                locked = False
                try:
                    try:
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                    except OSError as exc:
                        raise ValueError("Une autre instance écrit les parties ; réessayez après sa fermeture.") from exc
                    yield
                finally:
                    if locked:
                        handle.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _read(path: Path) -> tuple[object, bytes]:
        try:
            with path.open("rb") as handle:
                raw = handle.read(MAX_RUN_BYTES + 1)
            if len(raw) > MAX_RUN_BYTES:
                raise ValueError("La partie dépasse la limite de lecture locale.")
            return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_strict_pairs,
                              parse_constant=_invalid_constant), raw
        except (OSError, UnicodeError, ValueError, RecursionError) as exc:
            raise ValueError(f"Fichier de partie absent, inaccessible ou invalide : {path.name}.") from exc

    @staticmethod
    def _serialize(data: dict) -> bytes:
        raw = (json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
        if len(raw) > MAX_RUN_BYTES:
            raise ValueError("La partie dépasse la limite de stockage ; les données existantes sont conservées.")
        return raw

    @staticmethod
    def _replace(destination: Path, content: bytes) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=destination.parent, prefix=".run-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            local_path(destination)
            temporary.replace(destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def create(self, name: str, game_id: str, generation: int = 5, *, challenge: Challenge | dict | None = None,
               profile_id: str | None = None, preset: str | None = None, seed: int | None = None,
               game_code: str | None = None, region: str | None = None, revision: int | None = None,
               rom_fingerprint: str | None = None, save_path: str | None = None,
               launch_profile: dict | None = None) -> Run:
        if challenge is None:
            challenge = Challenge(game_id, "normal", [], {}, {"enforcement": "soft", "rule_parameters": {}},
                                  None, seed if seed is not None else 0)
        snapshot = challenge.to_dict() if isinstance(challenge, Challenge) else Challenge.from_dict(challenge).to_dict()
        if snapshot["game_id"] != game_id or seed is not None and snapshot["seed"] != seed:
            raise ValueError("Le profil et la partie doivent utiliser le même jeu et la même seed.")
        run = Run(str(uuid4()), name.strip() if isinstance(name, str) else name, game_id, generation, snapshot,
                  game_code=game_code, region=region, revision=revision, rom_fingerprint=rom_fingerprint,
                  profile_id=profile_id, preset=preset, seed=snapshot["seed"], save_path=save_path or None,
                  launch_profile=deepcopy(launch_profile))
        run.history.append(history_event("run_created", "system", {"profile_id": profile_id, "preset": preset}, run.created_at))
        payload = self._serialize(run.to_dict())
        with self._writing():
            directory = self._directory(run.run_id)
            directory.mkdir(exist_ok=False)
            self._replace(self._file(run.run_id), payload)
            run._storage_revision = sha256(payload).hexdigest()
        return deepcopy(run)

    def load(self, run_id: str) -> Run:
        with self._lock:
            data, raw = self._read(self._file(run_id))
            run = Run.from_dict(data)
            if run.run_id != run_id:
                raise ValueError("L'identifiant de partie ne correspond pas à son dossier.")
            run._storage_revision = sha256(raw).hexdigest()
            return run

    def list_runs(self) -> list[Run]:
        with self._lock:
            self.warnings.clear()
            if not self.root.exists():
                return []
            result = []
            try:
                directories = sorted(local_path(self.root).iterdir(), key=lambda item: item.name)
            except OSError as exc:
                self.warnings.append(f"Dossier des parties inaccessible : {exc}")
                return []
            for directory in directories:
                if directory.name.startswith(".") or directory.name == "active.json":
                    continue
                try:
                    if directory.is_dir():
                        result.append(self.load(directory.name))
                except (OSError, ValueError, TypeError, RecursionError) as exc:
                    self.warnings.append(f"Partie « {directory.name} » conservée mais non chargée : {exc}")
            return result

    def _save(self, run: Run) -> None:
        payload = self._serialize(run.to_dict())
        path = self._file(run.run_id)
        original_data, original_raw = self._read(path)
        original = Run.from_dict(original_data)
        if original.run_id != run.run_id:
            raise ValueError("L'identifiant existant de la partie est incohérent.")
        if run._storage_revision != sha256(original_raw).hexdigest():
            raise ValueError("La partie a changé dans une autre instance ; rechargez-la avant de modifier son suivi.")
        for key in _IMMUTABLE:
            if getattr(original, key) != getattr(run, key):
                raise ValueError(f"Le champ « {key} » est figé à la création de la partie.")
        # Check again immediately before publication, including user edits outside PCE.
        if path.read_bytes() != original_raw:
            raise ValueError("La partie a changé pendant la sauvegarde ; données existantes conservées.")
        self._replace(path, payload)
        run._storage_revision = sha256(payload).hexdigest()

    def save(self, run: Run) -> None:
        if not isinstance(run, Run):
            raise ValueError("Partie invalide.")
        with self._writing():
            self._save(run)

    def update(self, run_id: str, callback) -> Run:
        with self._writing():
            run = self.load(run_id)
            original = run.to_dict()
            callback(run)
            if run.to_dict() != original:
                self._save(run)
            return run

    @property
    def active_id(self) -> str | None:
        with self._lock:
            path = local_path(self.root / "active.json")
            if not path.exists():
                self._active_version, self._active_loaded = None, True
                return None
            data, raw = self._read(path)
            if not isinstance(data, dict) or set(data) != {"schema_version", "run_id"} or type(data["schema_version"]) is not int or data["schema_version"] != 1:
                raise ValueError("Référence de partie active invalide ; fichier conservé.")
            if data["run_id"] is not None:
                validate_run_id(data["run_id"])
            self._active_version, self._active_loaded = sha256(raw).hexdigest(), True
            return data["run_id"]

    def set_active_id(self, run_id: str | None) -> None:
        if run_id is not None:
            validate_run_id(run_id)
            if not self._file(run_id).is_file():
                raise ValueError("Cette partie n'existe pas.")
        with self._writing():
            if not self._active_loaded:
                self.active_id
            path = local_path(self.root / "active.json")
            actual = sha256(path.read_bytes()).hexdigest() if path.exists() else None
            if actual != self._active_version:
                raise ValueError("La partie active a été changée dans une autre instance ; rechargez la sélection.")
            raw = self._serialize({"schema_version": 1, "run_id": run_id})
            self._replace(path, raw)
            self._active_version = sha256(raw).hexdigest()
