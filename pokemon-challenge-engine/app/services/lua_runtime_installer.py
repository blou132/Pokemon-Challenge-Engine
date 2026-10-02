"""Install only hash-pinned official Lua DLLs after explicit user action."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from app.services.pe_inspection import inspect_pe, inspect_pe_bytes
from app.services.discovery_safety import local_path
from app.services.trusted_download_service import TrustedDownloadService, archive_is_trusted, LUA_URL


DLL_MANIFEST = {
    "x64": {
        "lua51.dll": ("x64/lua51.dll", 11776, "a85ced1c2078348684b74bcc20074f63a73d02881e5dcd002581ed757d8adf86"),
        "lua5.1.dll": ("x64/lua5.1.dll", 314880, "23719300fa4ae3116e97c313b838945bb2c1e02094daee8165939059aaad82c5"),
    },
    "x86": {
        "lua51.dll": ("win32/lua51.dll", 11264, "b2ba19343691f22d1af1417f9a7cbaeae74ba820a2a412f5a6cdea271cc1a7b0"),
        "lua5.1.dll": ("win32/lua5.1.dll", 167936, "26384c6ee7d50863e3fb65fdc1bad452d9311f34d782390401de9bb130eecc4a"),
    },
}


@dataclass(frozen=True)
class DLLDiagnostic:
    name: str
    path: Path
    status: str
    architecture: str | None = None
    sha256: str | None = None
    expected_sha256: str | None = None


@dataclass(frozen=True)
class LuaDiagnostic:
    status: str
    architecture: str | None
    dlls: tuple[DLLDiagnostic, ...]
    installable: bool
    console_status: str = "not_tested"
    required_apis: tuple[str, ...] = ("memory.readbyte", "emu.frameadvance")
    message: str = ""

    @property
    def ready(self) -> bool:
        return self.status == "verified"


@dataclass(frozen=True)
class LuaInstallResult:
    changed: tuple[Path, ...]
    backups: tuple[Path, ...]
    diagnostic: LuaDiagnostic


class LuaReplacementRequired(ValueError):
    def __init__(self, paths: tuple[Path, ...]):
        self.paths = paths
        super().__init__("Des fichiers Lua différents existent déjà. Leur remplacement exige une confirmation explicite.")


def extractor_path() -> Path | None:
    # Prefer the Windows-owned bsdtar, not an executable in the current directory.
    if os.name == "nt":
        for base in (os.environ.get("SystemRoot", "C:/Windows"),):
            path = Path(base) / "System32" / "tar.exe"
            if path.is_file():
                return path
        for base in (os.environ.get("ProgramFiles", "C:/Program Files"),
                     os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")):
            path = Path(base) / "7-Zip" / "7z.exe"
            if path.is_file():
                return path
    return None


def extract_lua_dlls(archive: Path, architecture: str) -> dict[str, bytes]:
    if architecture not in DLL_MANIFEST or not archive_is_trusted(archive):
        raise ValueError("Archive Lua non vérifiée ; extraction refusée.")
    executable = extractor_path()
    if executable is None:
        raise ValueError("Extraction Lua indisponible : tar Windows ou 7-Zip doit être installé.")
    result = {}
    for name, (member, size, digest) in DLL_MANIFEST[architecture].items():
        arguments = ([str(executable), "-xOf", str(archive.resolve()), member]
                     if executable.name.lower() == "tar.exe" else
                     [str(executable), "e", "-so", str(archive.resolve()), member])
        try:
            process = subprocess.run(arguments, shell=False, capture_output=True, timeout=30,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("Impossible d'extraire le support Lua vérifié.") from exc
        if process.returncode or len(process.stdout) != size or hashlib.sha256(process.stdout).hexdigest() != digest:
            raise ValueError("Le contenu extrait ne correspond pas aux DLL officielles attendues.")
        result[name] = process.stdout
    return result


def _running(executable: Path) -> bool:
    from app.services.emulator_window_manager import EmulatorWindowManager
    return EmulatorWindowManager().running_executable(executable)


class LuaRuntimeInstaller:
    def __init__(self, cache_dir: Path, *, running_probe=None, journal=None, downloader=None, extractor=None):
        self.cache_dir = local_path(cache_dir)
        self.running_probe = running_probe or _running
        self.journal = journal or self._local_journal
        self.downloader = downloader or TrustedDownloadService(self.cache_dir, journal=self.journal)
        self.extractor = extractor or extract_lua_dlls

    def _local_journal(self, event: str, **details):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / "lua-installation.jsonl"
        if path.is_symlink():
            raise ValueError("Journal d'installation symbolique refusé.")
        with path.open("a", encoding="utf-8") as handle:
            json.dump({"event": event, "timestamp": datetime.now(timezone.utc).isoformat(), **details},
                      handle, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def diagnose(self, executable: str | Path) -> LuaDiagnostic:
        try:
            info = inspect_pe(executable)
        except (ValueError, OSError) as exc:
            return LuaDiagnostic("unsupported", None, (), False, message=str(exc))
        if info.is_dll or not info.contains_desmume or not info.references_lua51 or info.architecture not in DLL_MANIFEST:
            return LuaDiagnostic("unsupported", info.architecture, (), False,
                                 message="Ce binaire DeSmuME/Lua n'est pas identifié de manière suffisante.")
        items = []
        for name, (_, _, expected) in DLL_MANIFEST[info.architecture].items():
            path = info.path.parent / name
            status, architecture, digest = "missing", None, None
            if path.exists() or path.is_symlink():
                try:
                    dll = inspect_pe(path)
                    architecture, digest = dll.architecture, dll.sha256
                    if not dll.is_dll:
                        status = "invalid"
                    elif architecture != info.architecture:
                        status = "wrong_architecture"
                    else:
                        status = "verified" if digest == expected else "different"
                except (ValueError, OSError):
                    status = "invalid"
            items.append(DLLDiagnostic(name, path, status, architecture, digest, expected))
        ready = all(item.status == "verified" for item in items)
        status = "verified" if ready else "missing" if all(item.status == "missing" for item in items) else "repair_needed"
        return LuaDiagnostic(status, info.architecture, tuple(items), extractor_path() is not None,
                             message="Fichiers Lua vérifiés (PE et empreintes). Chargement non testé." if ready else
                                     "Support Lua à installer ou réparer. Aucun test de chargement effectué.")

    def _guard_stopped(self, executable: Path):
        try:
            if self.running_probe(executable) is not False:
                raise ValueError("Fermez DeSmuME avant l'installation du support Lua.")
        except OSError as exc:
            raise ValueError("Impossible de confirmer l'arrêt de DeSmuME ; installation annulée.") from exc

    @staticmethod
    def _read_existing(path: Path) -> bytes | None:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("La destination Lua est un lien ou un fichier non régulier.")
        if not path.exists():
            return None
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("DLL existante trop volumineuse ; remplacement automatique refusé.")
        return path.read_bytes()

    @staticmethod
    def _backup(path: Path, raw: bytes) -> Path:
        for number in range(100000):
            destination = path.with_name(path.name + ".pce-backup" + (f".{number}" if number else ""))
            created = False
            try:
                with destination.open("xb") as handle:
                    created = True
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                return destination
            except FileExistsError:
                continue
            except OSError:
                if created:
                    destination.unlink(missing_ok=True)
                raise
        raise ValueError("Trop de backups Lua existants.")

    @staticmethod
    def _temporary(parent: Path, raw: bytes) -> Path:
        path = None
        try:
            with tempfile.NamedTemporaryFile(dir=parent, prefix=".pce_lua_", delete=False) as handle:
                path = Path(handle.name)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            return path
        except OSError:
            if path is not None:
                path.unlink(missing_ok=True)
            raise

    def install(self, executable: str | Path, *, allow_replace: bool = False) -> LuaInstallResult:
        if type(allow_replace) is not bool:
            raise ValueError("La confirmation de remplacement doit être explicite.")
        executable = local_path(executable)
        diagnostic = self.diagnose(executable)
        if diagnostic.status == "unsupported":
            raise ValueError(diagnostic.message)
        if diagnostic.ready:
            self.journal("lua_runtime_verified", executable=str(executable), changed=[])
            return LuaInstallResult((), (), diagnostic)
        self._guard_stopped(executable)
        before_executable = inspect_pe(executable).sha256
        originals = {item.path: self._read_existing(item.path) for item in diagnostic.dlls}
        different = tuple(item.path for item in diagnostic.dlls if originals[item.path] is not None and item.status != "verified")
        if different and not allow_replace:
            raise LuaReplacementRequired(different)
        self.journal("lua_runtime_install_started", executable=str(executable), architecture=diagnostic.architecture,
                     source=LUA_URL, replacements=[str(path) for path in different])
        try:
            archive = self.downloader.download_lua()
            blobs = self.extractor(archive.path, diagnostic.architecture)
            manifest = DLL_MANIFEST[diagnostic.architecture]
            if set(blobs) != set(manifest):
                raise ValueError("Les deux DLL Lua attendues ne sont pas présentes.")
            for name, data in blobs.items():
                info = inspect_pe_bytes(data)
                if (not info.is_dll or info.architecture != diagnostic.architecture
                        or info.sha256 != manifest[name][2] or info.size != manifest[name][1]):
                    raise ValueError("La DLL extraite ne correspond pas à l'architecture et à l'empreinte officielles.")
        except (OSError, ValueError) as exc:
            try:
                self.journal("lua_runtime_install_failed", stage="preparation", error=str(exc), changed=[])
            except (OSError, ValueError):
                pass
            raise ValueError("Préparation du support Lua impossible : " + str(exc)) from exc
        staged, backups, changed = {}, [], []
        try:
            for item in diagnostic.dlls:
                if item.status != "verified":
                    staged[item.path] = self._temporary(item.path.parent, blobs[item.name])
            self._guard_stopped(executable)
            if inspect_pe(executable).sha256 != before_executable:
                raise ValueError("DeSmuME a changé pendant la préparation ; installation annulée.")
            for path in staged:
                if self._read_existing(path) != originals[path]:
                    raise ValueError("Une DLL a changé pendant la préparation ; installation annulée.")
                if originals[path] is not None:
                    backup = self._backup(path, originals[path])
                    backups.append(backup)
                    self.journal("lua_runtime_backup", path=str(path), backup=str(backup),
                                 sha256=hashlib.sha256(originals[path]).hexdigest())
            for path, temporary in staged.items():
                self._guard_stopped(executable)
                if self._read_existing(path) != originals[path]:
                    raise ValueError("Une DLL a changé avant sa copie ; installation annulée.")
                temporary.replace(path)
                changed.append(path)
            after = self.diagnose(executable)
            if not after.ready:
                raise ValueError("La vérification des DLL installées a échoué.")
            self.journal("lua_runtime_installed", executable=str(executable), architecture=after.architecture,
                         files=[{"path": str(item.path), "sha256": item.sha256} for item in after.dlls],
                         validation="pe_and_hash_verified", console_status="not_tested")
            return LuaInstallResult(tuple(changed), tuple(backups), after)
        except (OSError, ValueError) as exc:
            rollback_failed = []
            for path in reversed(changed):
                try:
                    if self._read_existing(path) != blobs[path.name]:
                        raise ValueError("Destination modifiée après installation.")
                    if originals[path] is None:
                        path.unlink()
                    else:
                        rollback = self._temporary(path.parent, originals[path])
                        try:
                            rollback.replace(path)
                        finally:
                            rollback.unlink(missing_ok=True)
                except (OSError, ValueError):
                    rollback_failed.append(str(path))
            try:
                self.journal("lua_runtime_install_failed", error=str(exc), rollback_failed=rollback_failed,
                             backups=[str(path) for path in backups])
            except (OSError, ValueError):
                pass
            suffix = " Certains fichiers nécessitent une restauration depuis les backups." if rollback_failed else ""
            raise ValueError("Installation Lua annulée. Vérifiez les permissions, le verrouillage et l'espace disque." + suffix) from exc
        finally:
            for temporary in staged.values():
                temporary.unlink(missing_ok=True)
