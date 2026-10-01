"""Copies vérifiées de sauvegardes choisies explicitement et inventaire des slots.

La rétention ne concerne que les fichiers du manifeste PCE. Aucun fichier de jeu
n'est écrit, sauf par ``restore`` après confirmation explicite et émulateur fermé.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Iterator

from app.core.game_detector import GAME_CODE_PREFIXES

GAME_IDS = frozenset(GAME_CODE_PREFIXES.values())
BACKUP_REASONS = frozenset({"manual", "launch", "close", "periodic", "pre_restore"})
SAVE_STATE_POLICIES = {
    "allowed": "Autorisé", "forbidden": "Interdit", "outside_battle": "Autorisé hors combat",
    "read_only": "Lecture seule", "unmanaged": "Non géré",
}
MANIFEST_NAME = "pce-backups.json"
MAX_SAVE_BYTES = 512 * 1024 * 1024


class SaveManagerError(ValueError):
    """Erreur présentable sans exposer les détails du système de fichiers."""


@dataclass(frozen=True, slots=True)
class SaveFileInfo:
    path: Path
    game_id: str
    exists: bool
    size: int | None = None
    modified_at: str | None = None
    slot: int | None = None


@dataclass(frozen=True, slots=True)
class BackupRecord:
    filename: str
    game_id: str
    created_at: str
    size: int
    sha256: str
    source_key: str
    reason: str


def _game(game_id: str) -> None:
    if game_id not in GAME_IDS:
        raise SaveManagerError("Jeu de sauvegarde inconnu.")


def _path(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip() or "\0" in str(value):
        raise SaveManagerError("Choisissez un chemin valide.")
    try:
        result = Path(os.path.abspath(value))
        # Refuser aussi les jonctions Windows et les liens dans les parents.
        for part in (result, *result.parents):
            if part.is_symlink() or part.is_junction():
                raise SaveManagerError("Les liens et jonctions ne sont pas acceptés pour les sauvegardes.")
        return result
    except (OSError, RuntimeError) as exc:
        raise SaveManagerError("Chemin inaccessible.") from exc


def _signature(path: Path) -> tuple[int, int, int, int, int]:
    value = path.stat()
    if not stat.S_ISREG(value.st_mode):
        raise SaveManagerError("Le chemin doit désigner un fichier normal.")
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _strict_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise SaveManagerError("Manifeste des backups invalide : clé dupliquée.")
        result[key] = value
    return result


class SaveManagerService:
    """Un dossier dédié, un manifeste atomique et des copies sans écrasement."""

    def __init__(self, backup_root: Path) -> None:
        self.root = _path(backup_root)

    @staticmethod
    def inspect_save(save_path: str | Path, game_id: str) -> SaveFileInfo:
        _game(game_id)
        path = _path(save_path)
        if path.suffix.lower() != ".dsv":
            raise SaveManagerError("Choisissez une sauvegarde normale DeSmuME .dsv.")
        return SaveManagerService._info(path, game_id)

    @staticmethod
    def _info(path: Path, game_id: str, slot: int | None = None) -> SaveFileInfo:
        try:
            value = path.stat()
            if not stat.S_ISREG(value.st_mode):
                raise SaveManagerError("Le chemin ne désigne pas un fichier normal.")
            modified = datetime.fromtimestamp(value.st_mtime, timezone.utc).isoformat()
            return SaveFileInfo(path, game_id, True, value.st_size, modified, slot)
        except FileNotFoundError:
            return SaveFileInfo(path, game_id, False, slot=slot)
        except OSError as exc:
            raise SaveManagerError("Impossible de lire les métadonnées du fichier.") from exc

    @staticmethod
    def inspect_slots(directory: str | Path, stem: str, game_id: str) -> tuple[SaveFileInfo, ...]:
        """Convention officielle StateSlots / nom.ds0…nom.ds9, sans lire le contenu."""
        _game(game_id)
        folder = _path(directory)
        if not isinstance(stem, str) or not stem.strip() or stem in {".", ".."} or \
                re.search(r'[\\/:*?"<>|\x00-\x1f]', stem) or stem.endswith((" ", ".")):
            raise SaveManagerError("Le nom des slots doit être un simple nom de fichier, sans extension .dsN.")
        if not folder.is_dir():
            raise SaveManagerError("Le dossier des slots est introuvable.")
        return tuple(SaveManagerService._info(_path(folder / f"{stem}.ds{slot}"), game_id, slot)
                     for slot in range(10))

    @contextmanager
    def _locked(self) -> Iterator[None]:
        lock: Path | None = None
        acquired = False
        try:
            _path(self.root)
            self.root.mkdir(parents=True, exist_ok=True)
            lock = self.root / ".pce-backup.lock"
            with lock.open("xb"):
                acquired = True
            yield
        except FileExistsError as exc:
            raise SaveManagerError("Une opération de backup est déjà en cours. Un verrou résiduel doit être vérifié manuellement.") from exc
        except OSError as exc:
            raise SaveManagerError("Opération impossible : fichier verrouillé ou permissions insuffisantes.") from exc
        finally:
            if acquired and lock is not None:
                lock.unlink(missing_ok=True)

    def _load(self) -> list[BackupRecord]:
        path = _path(self.root / MANIFEST_NAME)
        if not path.exists():
            return []
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("Manifeste trop volumineux")
            data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_pairs)
            if not isinstance(data, dict) or set(data) != {"schema_version", "owner", "backups"} or \
                    type(data["schema_version"]) is not int or data["schema_version"] != 1 or \
                    data["owner"] != "pokemon-challenge-engine" or not isinstance(data["backups"], list):
                raise ValueError("En-tête invalide")
            result = []
            names = set()
            for entry in data["backups"]:
                if not isinstance(entry, dict) or set(entry) != set(BackupRecord.__dataclass_fields__):
                    raise ValueError("Entrée invalide")
                record = BackupRecord(**entry)
                _game(record.game_id)
                pattern = rf"{record.game_id}_\d{{4}}-\d{{2}}-\d{{2}}_\d{{2}}-\d{{2}}-\d{{2}}(?:_\d+)?\.dsv"
                if not isinstance(record.filename, str) or not re.fullmatch(pattern, record.filename) or \
                        record.filename in names or type(record.size) is not int or not 0 <= record.size <= MAX_SAVE_BYTES or \
                        not isinstance(record.sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", record.sha256) or \
                        not isinstance(record.source_key, str) or not re.fullmatch(r"[a-f0-9]{64}", record.source_key) or \
                        record.reason not in BACKUP_REASONS or not isinstance(record.created_at, str):
                    raise ValueError("Entrée invalide")
                if datetime.fromisoformat(record.created_at).tzinfo is None:
                    raise ValueError("Date sans fuseau")
                names.add(record.filename)
                result.append(record)
            return result
        except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            raise SaveManagerError("Manifeste des backups inaccessible ou corrompu ; aucun fichier n'a été supprimé.") from exc

    def _write(self, records: list[BackupRecord]) -> None:
        data = {"schema_version": 1, "owner": "pokemon-challenge-engine", "backups": [asdict(record) for record in records]}
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root,
                                             prefix=".manifest_", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle, indent=2, ensure_ascii=False, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            _path(self.root / MANIFEST_NAME)
            temporary.replace(self.root / MANIFEST_NAME)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def list_backups(self, game_id: str | None = None) -> tuple[BackupRecord, ...]:
        if game_id is not None:
            _game(game_id)
        return tuple(record for record in reversed(self._load()) if game_id is None or record.game_id == game_id)

    @staticmethod
    def _copy_consistent(source: Path, destination: Path) -> tuple[int, str]:
        """Une copie n'est publiée que si deux lectures concordent et les stats restent stables."""
        _path(source)
        before = _signature(source)
        if before[2] > MAX_SAVE_BYTES:
            raise SaveManagerError("Sauvegarde trop volumineuse pour ce gestionnaire.")
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as reader, destination.open("wb") as writer:
            while chunk := reader.read(64 * 1024):
                size += len(chunk)
                if size > MAX_SAVE_BYTES:
                    raise SaveManagerError("Sauvegarde modifiée pendant la copie ; réessayez une fois stable.")
                digest.update(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if before != _signature(source) or size != before[2] or _digest(source) != digest.hexdigest() or \
                before != _signature(source) or _digest(destination) != digest.hexdigest():
            raise SaveManagerError("Sauvegarde modifiée pendant la copie ; aucun backup n'a été publié.")
        return size, digest.hexdigest()

    def backup(self, save_path: str | Path, game_id: str, retention: int = 10,
               reason: str = "manual") -> BackupRecord:
        _game(game_id)
        if type(retention) is not int or not 1 <= retention <= 10000:
            raise SaveManagerError("La rétention doit être comprise entre 1 et 10 000 backups par jeu.")
        if reason not in BACKUP_REASONS:
            raise SaveManagerError("Motif de backup invalide.")
        source = _path(save_path)
        if source.suffix.lower() != ".dsv" or source.is_relative_to(self.root):
            raise SaveManagerError("Choisissez une sauvegarde .dsv extérieure au dossier dédié aux backups.")
        if not source.is_file():
            raise SaveManagerError("La sauvegarde normale est introuvable.")
        with self._locked():
            return self._backup_locked(source, game_id, retention, reason)

    def _backup_locked(self, source: Path, game_id: str, retention: int, reason: str) -> BackupRecord:
        records = self._load()  # Un manifeste corrompu bloque toute écriture.
        temporary: Path | None = None
        published: Path | None = None
        recorded = False
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".backup_", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
            size, digest = self._copy_consistent(source, temporary)
            now = datetime.now(timezone.utc)
            stem = f"{game_id}_{now.strftime('%Y-%m-%d_%H-%M-%S')}"
            # Ne pas réattribuer le nom d'une copie supprimée par la rétention
            # quelques millisecondes plus tôt dans la même seconde.
            same_second = [item.filename for item in records
                           if item.filename == f"{stem}.dsv" or item.filename.startswith(f"{stem}_")]
            counters = [0 if name == f"{stem}.dsv" else int(Path(name).stem.rsplit("_", 1)[1])
                        for name in same_second]
            counter = max(counters) + 1 if counters else 0
            while True:
                filename = f"{stem}{'_' + str(counter) if counter else ''}.dsv"
                candidate = self.root / filename
                try:
                    # Lien atomique avec création exclusive : jamais d'écrasement, même en collision.
                    os.link(temporary, candidate)
                    published = candidate
                    break
                except FileExistsError:
                    counter += 1
            record = BackupRecord(filename, game_id, now.isoformat(), size, digest,
                                  hashlib.sha256(os.path.normcase(str(source)).encode("utf-8")).hexdigest(), reason)
            records.append(record)
            self._write(records)
            recorded = True
            self._retain(records, game_id, retention)
            return record
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if published is not None and not recorded:
                published.unlink(missing_ok=True)

    def _verified(self, record: BackupRecord) -> Path:
        path = _path(self.root / record.filename)
        if not path.is_file() or path.stat().st_size != record.size or _digest(path) != record.sha256:
            raise SaveManagerError("Un backup est manquant ou a changé ; restauration/rétention refusée.")
        return path

    def _retain(self, records: list[BackupRecord], game_id: str, retention: int) -> None:
        candidates = [record for record in records if record.game_id == game_id][:-retention]
        # Vérifier tous les candidats avant la première suppression. Les fichiers étrangers sont ignorés.
        paths = [self._verified(record) for record in candidates]
        for path in paths:
            _path(path)
            path.unlink()
        if candidates:
            self._write([record for record in records if record not in candidates])

    def restore(self, filename: str, target_path: str | Path, game_id: str, *, confirmed: bool = False,
                emulator_running: bool = False, retention: int = 10) -> BackupRecord:
        """Action explicite uniquement ; une copie de l'original précède son remplacement."""
        _game(game_id)
        if confirmed is not True:
            raise SaveManagerError("La restauration exige une confirmation explicite.")
        if emulator_running is not False:
            raise SaveManagerError("Fermez DeSmuME avant de restaurer une sauvegarde.")
        if type(retention) is not int or not 1 <= retention <= 10000:
            raise SaveManagerError("Rétention invalide.")
        target = _path(target_path)
        if target.suffix.lower() != ".dsv" or target.is_relative_to(self.root) or not target.is_file():
            raise SaveManagerError("La cible doit être la sauvegarde .dsv existante, hors du dossier de backups.")
        with self._locked():
            records = self._load()
            record = next((item for item in records if item.filename == filename and item.game_id == game_id), None)
            if record is None:
                raise SaveManagerError("Backup inconnu ou associé à un autre jeu.")
            source = self._verified(record)
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".pce-restore_", suffix=".tmp", delete=False) as handle:
                    temporary = Path(handle.name)
                self._copy_consistent(source, temporary)
                before = _signature(target)
                safety = self._backup_locked(target, game_id, retention, "pre_restore")
                if before != _signature(target) or _digest(target) != safety.sha256:
                    raise SaveManagerError("La sauvegarde a changé ; restauration annulée.")
                _path(target)
                temporary.replace(target)
                return safety
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
