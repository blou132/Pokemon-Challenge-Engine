"""Delete only a reviewed run directory; never follow its external references."""

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from app.core.run_manager import RunManager
from app.models.run import validate_run_id
from app.services.discovery_safety import file_hash, local_path


MAX_DELETE_ENTRIES = 10000
MAX_DELETE_DEPTH = 32


@dataclass(frozen=True)
class DeletionEntry:
    path: str
    is_directory: bool
    size: int
    signature: tuple[int, int, int, int, int]
    digest: str = ""


@dataclass(frozen=True)
class RunDeletionPlan:
    run_id: str
    name: str
    directory: Path
    entries: tuple[DeletionEntry, ...]
    preserved_references: tuple[str, ...]
    token: str

    @property
    def files(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.entries if not item.is_directory)

    @property
    def directories(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.entries if item.is_directory)

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.entries if not item.is_directory)


def _references(value):
    """Inspect metadata as text only: referenced files are never opened or removed."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item)
    elif isinstance(value, str) and "\0" not in value and Path(value).is_absolute():
        yield Path(os.path.abspath(value))


class RunDeletionService:
    def __init__(self, manager: RunManager, *, running_probe=None):
        self.manager = manager
        if running_probe is None:
            from app.services.emulator_window_manager import EmulatorWindowManager
            running_probe = EmulatorWindowManager().running_executable
        self.running_probe = running_probe

    @staticmethod
    def _entry(path: Path, directory: Path) -> DeletionEntry:
        local_path(path)
        value = path.stat(follow_symlinks=False)
        is_directory = stat.S_ISDIR(value.st_mode)
        if not is_directory and not stat.S_ISREG(value.st_mode):
            raise ValueError("La partie contient un fichier spécial ; suppression refusée.")
        if not is_directory and value.st_nlink != 1:
            raise ValueError("La partie contient un lien physique ; suppression refusée.")
        signature = (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        digest = "" if is_directory else file_hash(path)
        after = path.stat(follow_symlinks=False)
        if signature != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("La partie a changé pendant la vérification ; recommencez la confirmation.")
        return DeletionEntry(path.relative_to(directory).as_posix(), is_directory,
                             0 if is_directory else value.st_size, signature, digest)

    def _preview(self, run_id: str) -> RunDeletionPlan:
        validate_run_id(run_id)
        root = local_path(self.manager.root)
        directory = local_path(root / run_id)
        if directory.parent != root:
            raise ValueError("Le dossier de partie ne se trouve pas dans la bibliothèque PCE.")
        run = self.manager.load(run_id)
        if self.manager.active_id == run_id or any(item["ended_at"] is None for item in run.sessions):
            raise ValueError("Arrêtez la session et le suivi de cette partie avant de la supprimer.")
        executable = (run.launch_profile or {}).get("emulator_path")
        if executable and self.running_probe(executable) is not False:
            raise ValueError("Fermez DeSmuME avant de supprimer cette partie, même si PCE ne suit plus sa session.")

        # Old metadata can still reference another run's copy. Refuse to destroy
        # such shared data rather than infer ownership from a filename alone.
        others = self.manager.list_runs()
        if self.manager.warnings:
            raise ValueError("Certaines parties sont illisibles ; impossible de vérifier leurs références avant suppression.")
        for other in others:
            if other.run_id != run_id and any(path.is_relative_to(directory) for path in _references(other.to_dict())):
                raise ValueError("Une autre partie utilise des fichiers de ce dossier ; suppression refusée.")

        entries = [self._entry(directory, directory)]
        pending = [(directory, 0)]
        while pending:
            folder, depth = pending.pop()
            local_path(folder)
            if depth > MAX_DELETE_DEPTH:
                raise ValueError("Le dossier de partie est trop profond pour une suppression vérifiée.")
            with os.scandir(folder) as children:
                for child in children:
                    if len(entries) >= MAX_DELETE_ENTRIES:
                        raise ValueError("La partie contient trop de fichiers pour une suppression vérifiée.")
                    path = local_path(child.path)
                    if not path.is_relative_to(directory):
                        raise ValueError("Un fichier sort du dossier de partie ; suppression refusée.")
                    entry = self._entry(path, directory)
                    entries.append(entry)
                    if entry.is_directory:
                        pending.append((path, depth + 1))
        ordered = tuple(sorted(entries, key=lambda item: item.path))
        preserved = tuple(sorted({str(path) for path in _references(run.to_dict())
                                  if not path.is_relative_to(directory)}))
        raw = [(item.path, item.is_directory, item.size, item.signature, item.digest) for item in ordered]
        token = sha256(json.dumps([str(root), run_id, raw, preserved], ensure_ascii=False).encode("utf-8")).hexdigest()
        return RunDeletionPlan(run_id, run.name, directory, ordered, preserved, token)

    def preview(self, run_id: str) -> RunDeletionPlan:
        """Return the exact inventory to show before the user's confirmation."""
        with self.manager._writing():
            return self._preview(run_id)

    def delete(self, plan: RunDeletionPlan) -> None:
        """Execute an explicitly confirmed inventory, refusing any intervening change."""
        if not isinstance(plan, RunDeletionPlan):
            raise ValueError("Confirmation de suppression invalide.")
        with self.manager._writing():
            current = self._preview(plan.run_id)
            if current != plan:
                raise ValueError("La partie a changé depuis la confirmation ; vérifiez à nouveau les fichiers à supprimer.")
            directory = current.directory
            # No rmtree: delete only reviewed files, never ROM/save paths from
            # run.json. Keep run.json until all other files were removed so a
            # filesystem error leaves the remaining run visible for recovery.
            files = [item for item in current.entries if not item.is_directory and item.path != "run.json"]
            manifest = next(item for item in current.entries if item.path == "run.json")
            try:
                for item in files:
                    path = local_path(directory / item.path)
                    if self._entry(path, directory) != item:
                        raise ValueError("Un fichier a changé pendant la suppression ; les fichiers restants sont conservés.")
                    path.unlink()
                for item in sorted((item for item in current.entries if item.is_directory and item.path != "."),
                                   key=lambda item: len(Path(item.path).parts), reverse=True):
                    local_path(directory / item.path).rmdir()
                path = local_path(directory / "run.json")
                if self._entry(path, directory) != manifest:
                    raise ValueError("La partie a changé pendant la suppression ; son suivi est conservé.")
                path.unlink()
                local_path(directory).rmdir()
            except OSError as exc:
                raise ValueError("Suppression interrompue par le système ; les fichiers restants ont été conservés. "
                                 "Fermez les programmes utilisant cette partie puis réessayez.") from exc
