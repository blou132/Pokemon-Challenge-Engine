"""Private, persistent ROM masters; source files are only ever opened for reading.

The library is independent of a portable installation, run data, build output and
the repository. Public packages contain this service, never its user-owned data.
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

from app.services.config_service import _invalid_constant, _strict_pairs
from app.services.discovery_safety import file_signature, local_path
from app.services.rom_preparation_service import MAX_ROM_BYTES, REGIONS, open_safe_zip


LIBRARY_GAME_PREFIXES = {
    "ADA": "diamond", "APA": "pearl", "CPU": "platinum",
    "IPK": "heartgold", "IPG": "soulsilver",
    "IRB": "black", "IRA": "white", "IRE": "black2", "IRD": "white2",
}
GEN4_GAMES = frozenset({"diamond", "pearl", "platinum", "heartgold", "soulsilver"})
LIBRARY_OWNER = "pokemon-challenge-engine-personal-rom-library"
MANIFEST_NAME = "library.json"
MANIFEST_LIMIT = 256 * 1024
CHUNK_SIZE = 1024 * 1024


def default_library_root() -> Path:
    """A per-user location that never depends on cwd, --data-dir or a build."""
    folder = os.environ.get("LOCALAPPDATA")
    if folder:
        if not Path(folder).is_absolute():
            raise ValueError("LOCALAPPDATA doit être un chemin absolu pour la bibliothèque personnelle.")
        return local_path(Path(folder) / "Pokemon-Challenge-Engine" / "library")
    if os.name == "nt":
        raise ValueError("LOCALAPPDATA est introuvable : bibliothèque personnelle non localisable.")
    # Development on other systems uses a stable user store as well.
    folder = os.environ.get("XDG_DATA_HOME")
    base = Path(folder) if folder else Path.home() / ".local" / "share"
    if not base.is_absolute():
        raise ValueError("XDG_DATA_HOME doit être un chemin absolu.")
    return local_path(base / "Pokemon-Challenge-Engine" / "library")


@dataclass(frozen=True, slots=True)
class LibraryEntry:
    game_id: str
    game_code: str
    generation: int
    region: str
    revision: int
    sha256: str
    size: int
    relative_path: str
    imported_at: str
    source_name: str


@dataclass(frozen=True, slots=True)
class LibrarySource:
    source_path: Path
    archive_member: str | None
    game_id: str
    game_code: str
    generation: int
    region: str
    revision: int
    sha256: str
    size: int
    source_sha256: str


@dataclass(frozen=True, slots=True)
class LibraryImportResult:
    entry: LibraryEntry
    imported: bool


@dataclass(frozen=True, slots=True)
class LibraryVerification:
    entry: LibraryEntry
    valid: bool
    error: str | None = None


def _regular_file(path: Path) -> None:
    local_path(path)
    if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
        raise ValueError("La source doit être un fichier local régulier, sans lien.")


def _identity(header: bytes) -> tuple[str, str, int, str, int]:
    if len(header) < 32:
        raise ValueError("En-tête Nintendo DS incomplet.")
    try:
        code = header[12:16].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("Code Nintendo DS illisible.") from exc
    game = LIBRARY_GAME_PREFIXES.get(code[:3])
    if game is None or not re.fullmatch(r"[A-Z0-9]{4}", code):
        raise ValueError("Cette ROM ne correspond pas à un des neuf jeux Pokémon DS reconnus.")
    return game, code, 4 if game in GEN4_GAMES else 5, REGIONS.get(code[3], "unknown"), header[30]


def _read_rom(reader, expected_size: int, writer=None) -> tuple[str, int, tuple]:
    if not 32 <= expected_size <= MAX_ROM_BYTES:
        raise ValueError("Taille de ROM invalide (32 octets à 1 Gio).")
    digest = hashlib.sha256()
    size = 0
    header = b""
    while chunk := reader.read(CHUNK_SIZE):
        if not header:
            header = chunk[:32]
        size += len(chunk)
        if size > expected_size:
            raise ValueError("La taille de la ROM a changé pendant sa lecture.")
        digest.update(chunk)
        if writer is not None:
            writer.write(chunk)
    if size != expected_size:
        raise ValueError("ROM tronquée ou modifiée pendant sa lecture.")
    return digest.hexdigest(), size, _identity(header)


@contextmanager
def _source_reader(path: Path):
    _regular_file(path)
    if path.suffix.lower() == ".nds":
        with path.open("rb") as reader:
            yield reader, path.stat().st_size, None
    elif path.suffix.lower() == ".zip":
        with open_safe_zip(path) as archive:
            members = [info for info in archive.infolist()
                       if not info.is_dir() and info.filename.lower().endswith(".nds")]
            if len(members) != 1:
                raise ValueError("Une archive de bibliothèque doit contenir une seule ROM .nds.")
            info = members[0]
            if stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG):
                raise ValueError("Le membre ROM doit être un fichier ZIP régulier.")
            with archive.open(info) as reader:
                yield reader, info.file_size, info.filename
    else:
        raise ValueError("La bibliothèque accepte uniquement les fichiers .nds et .zip locaux.")


def inspect_library_source(source: str | Path) -> LibrarySource:
    path = local_path(source)
    before = file_signature(path)
    with _source_reader(path) as (reader, expected_size, member):
        digest, size, identity = _read_rom(reader, expected_size)
    if member is None:
        source_digest = digest
    else:
        with path.open("rb") as reader:
            source_digest = hashlib.file_digest(reader, "sha256").hexdigest()
    if before != file_signature(path):
        raise ValueError("Le fichier source a changé pendant son identification.")
    return LibrarySource(path, member, *identity, digest, size, source_digest)


class RomLibraryService:
    """Append-only master files and a versioned, locked, atomic manifest.

    An explicit root is required for tests that import or verify fixtures. Merely
    constructing this service does not create a directory or import anything.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = default_library_root() if root is None else local_path(root)

    @property
    def manifest_path(self) -> Path:
        return local_path(self.root / MANIFEST_NAME)

    def list_entries(self) -> tuple[LibraryEntry, ...]:
        path = self.manifest_path
        if not path.exists():
            return ()
        _regular_file(path)
        if path.stat().st_size > MANIFEST_LIMIT:
            raise ValueError("Le manifeste de bibliothèque dépasse la taille autorisée.")
        try:
            value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_pairs,
                               parse_constant=_invalid_constant)
            if not isinstance(value, dict) or set(value) != {"owner", "schema_version", "entries"} or \
                    value["owner"] != LIBRARY_OWNER or type(value["schema_version"]) is not int or \
                    value["schema_version"] != 1 or not isinstance(value["entries"], list) or len(value["entries"]) > 9:
                raise ValueError("Format ou version de bibliothèque non pris en charge.")
            entries = []
            games = set()
            for raw in value["entries"]:
                if not isinstance(raw, dict):
                    raise ValueError("Entrée de bibliothèque invalide.")
                entry = LibraryEntry(**raw)
                self._validate_entry(entry)
                if entry.game_id in games:
                    raise ValueError("Plusieurs maîtresses sont déclarées pour un même jeu.")
                games.add(entry.game_id)
                entries.append(entry)
            return tuple(sorted(entries, key=lambda entry: entry.game_id))
        except (TypeError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("Le manifeste de bibliothèque est invalide ; il a été conservé.") from exc

    @staticmethod
    def _validate_entry(entry: LibraryEntry) -> None:
        if not isinstance(entry.game_code, str) or not re.fullmatch(r"[A-Z0-9]{4}", entry.game_code) or \
                LIBRARY_GAME_PREFIXES.get(entry.game_code[:3]) != entry.game_id:
            raise ValueError("Identité de bibliothèque incohérente.")
        if type(entry.generation) is not int or entry.generation != (4 if entry.game_id in GEN4_GAMES else 5) or \
                entry.region != REGIONS.get(entry.game_code[3], "unknown") or \
                type(entry.revision) is not int or not 0 <= entry.revision <= 255:
            raise ValueError("Région, génération ou révision de bibliothèque invalide.")
        if not isinstance(entry.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", entry.sha256) or \
                type(entry.size) is not int or not 32 <= entry.size <= MAX_ROM_BYTES:
            raise ValueError("Empreinte ou taille de bibliothèque invalide.")
        expected = f"masters/{entry.game_id}/{entry.sha256}.nds"
        if entry.relative_path != expected:
            raise ValueError("Le chemin de la maîtresse n'est pas celui du manifeste.")
        if not isinstance(entry.source_name, str) or not entry.source_name or len(entry.source_name) > 255 or \
                any(char in entry.source_name for char in "\\/\0") or \
                not isinstance(entry.imported_at, str):
            raise ValueError("Métadonnées de bibliothèque invalides.")
        try:
            stamp = datetime.fromisoformat(entry.imported_at)
            if stamp.tzinfo is None:
                raise ValueError("Date d'import sans fuseau horaire.")
        except ValueError as exc:
            raise ValueError("Date d'import de bibliothèque invalide.") from exc

    def master_path(self, entry: LibraryEntry) -> Path:
        self._validate_entry(entry)
        return local_path(self.root / entry.relative_path)

    def _verify_entry(self, entry: LibraryEntry) -> Path:
        path = self.master_path(entry)
        actual = inspect_library_source(path)
        if (actual.game_id, actual.game_code, actual.generation, actual.region, actual.revision,
            actual.sha256, actual.size) != (entry.game_id, entry.game_code, entry.generation, entry.region,
                                            entry.revision, entry.sha256, entry.size):
            raise ValueError(f"Intégrité de la ROM maîtresse {entry.game_id} invalide : génération refusée.")
        return path

    def resolve(self, game_id: str) -> Path | None:
        entry = next((item for item in self.list_entries() if item.game_id == game_id), None)
        if entry is None:
            return None
        try:
            return self._verify_entry(entry)
        except OSError as exc:
            raise ValueError(f"ROM maîtresse {game_id} inaccessible : génération refusée.") from exc

    def verify(self) -> tuple[LibraryVerification, ...]:
        results = []
        for entry in self.list_entries():
            try:
                self._verify_entry(entry)
                results.append(LibraryVerification(entry, True))
            except (OSError, ValueError) as exc:
                results.append(LibraryVerification(entry, False, str(exc)))
        return tuple(results)

    def scan_sources(self, folder: str | Path) -> tuple[LibrarySource, ...]:
        root = local_path(folder)
        if not root.is_dir():
            raise ValueError("Le dossier local de ROM sources est introuvable.")
        paths = []
        with os.scandir(root) as children:
            for count, child in enumerate(children):
                if count >= 2048:
                    raise ValueError("Dossier source trop volumineux (2048 entrées maximum).")
                if Path(child.name).suffix.lower() in {".nds", ".zip"}:
                    candidate = local_path(child.path)
                    _regular_file(candidate)
                    paths.append(candidate)
        sources = tuple(inspect_library_source(path) for path in sorted(paths))
        self._check_conflicts(sources, ())
        return sources

    @staticmethod
    def _check_conflicts(sources, entries) -> None:
        hashes = {entry.game_id: entry.sha256 for entry in entries}
        for source in sources:
            if source.game_id in hashes and hashes[source.game_id] != source.sha256:
                raise ValueError(f"Conflit pour {source.game_id} : une autre ROM existe déjà ; aucune maîtresse remplacée.")
            hashes[source.game_id] = source.sha256

    @contextmanager
    def _lock(self):
        local_path(self.root).mkdir(parents=True, exist_ok=True)
        lock = local_path(self.root / ".library.lock")
        with lock.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError("Un import de bibliothèque est déjà en cours ; réessayez après sa fin.") from exc
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _write_manifest(self, entries) -> None:
        value = {"owner": LIBRARY_OWNER, "schema_version": 1,
                 "entries": [asdict(entry) for entry in sorted(entries, key=lambda item: item.game_id)]}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root,
                                             prefix=".manifest-", suffix=".tmp", delete=False) as writer:
                temporary = Path(writer.name)
                json.dump(value, writer, ensure_ascii=False, indent=2, allow_nan=False)
                writer.write("\n")
                writer.flush()
                os.fsync(writer.fileno())
            os.replace(temporary, self.manifest_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def import_source(self, source: str | Path | LibrarySource) -> LibraryImportResult:
        actual = inspect_library_source(source.source_path if isinstance(source, LibrarySource) else source)
        if isinstance(source, LibrarySource) and source != actual:
            raise ValueError("La source a changé depuis son inventaire : import refusé.")
        with self._lock():
            return self._import_locked(actual)

    def import_directory(self, folder: str | Path) -> tuple[LibraryImportResult, ...]:
        sources = self.scan_sources(folder)
        if not sources:
            return ()
        with self._lock():
            self._check_conflicts(sources, self.list_entries())
            return tuple(self._import_locked(source) for source in sources)

    def _import_locked(self, source: LibrarySource) -> LibraryImportResult:
        entries = self.list_entries()
        self._check_conflicts((source,), entries)
        existing = next((entry for entry in entries if entry.game_id == source.game_id), None)
        if existing is not None:
            self._verify_entry(existing)
            return LibraryImportResult(existing, False)
        entry = LibraryEntry(source.game_id, source.game_code, source.generation, source.region, source.revision,
                             source.sha256, source.size, f"masters/{source.game_id}/{source.sha256}.nds",
                             datetime.now(timezone.utc).isoformat(), source.source_path.name)
        destination = self.master_path(entry)
        # A successful copy with an interrupted manifest commit is reusable only
        # after a complete hash check. It is never overwritten or deleted.
        if destination.exists():
            self._verify_entry(entry)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            before = file_signature(source.source_path)
            try:
                with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent, prefix=".import-",
                                                 suffix=".tmp", delete=False) as writer:
                    temporary = Path(writer.name)
                    with _source_reader(source.source_path) as (reader, size, member):
                        digest, copied_size, identity = _read_rom(reader, size, writer)
                    writer.flush()
                    os.fsync(writer.fileno())
                if (digest, copied_size, identity, member) != (
                        source.sha256, source.size,
                        (source.game_id, source.game_code, source.generation, source.region, source.revision),
                        source.archive_member) or before != file_signature(source.source_path):
                    raise ValueError("La source a changé pendant la copie : import refusé.")
                # link() publishes the completed bytes atomically and refuses an
                # existing destination on Windows and POSIX. No replace operation
                # ever targets a ROM. Removing our temporary name leaves the sole
                # library-owned master; it is not a hardlink to the user's source.
                os.link(temporary, destination)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        self._write_manifest((*entries, entry))
        return LibraryImportResult(entry, True)
