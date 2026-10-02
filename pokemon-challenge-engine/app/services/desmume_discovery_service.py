"""Bounded DeSmuME discovery by PE content, not by an executable's name."""

from dataclasses import dataclass
from pathlib import Path

from app.services.emulator_capabilities import VERIFIED_BUILD_SHA256
from app.services.lua_runtime_installer import DLLDiagnostic, LuaRuntimeInstaller
from app.services.pe_inspection import inspect_pe


@dataclass(frozen=True)
class EmulatorCandidate:
    path: Path
    architecture: str | None
    sha256: str
    version: str | None
    known_build: bool
    ini_path: Path | None
    lua_status: str
    dlls: tuple[DLLDiagnostic, ...]
    lua_supported: bool
    identity_source: str

    @property
    def replacement_required(self) -> bool:
        return any(item.status not in ("missing", "verified") for item in self.dlls)


class DeSmuMEDiscoveryService:
    def __init__(self, *, journal=None):
        self.journal = journal or (lambda event, **details: None)
        self.warnings: list[str] = []

    def inspect(self, path: str | Path) -> EmulatorCandidate:
        info = inspect_pe(path)
        if info.is_dll or not info.contains_desmume:
            raise ValueError("Ce binaire n'est pas identifié comme DeSmuME.")
        known = info.sha256 == VERIFIED_BUILD_SHA256
        version = info.file_version or ("0.9.14 git#a779eb7 x64-JIT SSE2" if known else None)
        ini = info.path.parent / "desmume.ini"
        if not ini.is_file() or ini.is_symlink():
            ini = None
        # diagnose only reads files; this cache directory is never created here.
        diagnostic = LuaRuntimeInstaller(info.path.parent / ".unused-diagnostic-cache").diagnose(info.path)
        return EmulatorCandidate(info.path, info.architecture, info.sha256, version, known, ini,
                                 diagnostic.status, diagnostic.dlls, info.references_lua51,
                                 "verified_fingerprint" if known else "pe_binary_markers")

    def discover(self, directories: list[Path], configured_paths=()) -> list[EmulatorCandidate]:
        self.warnings.clear()
        paths = list(configured_paths)[:64]
        for directory in directories[:32]:
            directory = Path(directory)
            try:
                if not directory.is_dir() or directory.is_symlink():
                    continue
                count = 0
                for entry in directory.iterdir():
                    count += 1
                    if count > 512:
                        self.warnings.append(f"Recherche limitée aux 512 entrées de {directory}.")
                        break
                    if entry.is_file() and not entry.is_symlink() and entry.suffix.lower() == ".exe":
                        paths.append(entry)
            except OSError:
                self.warnings.append(f"Dossier DeSmuME inaccessible : {directory}.")
        result, seen = [], set()
        for path in paths:
            try:
                resolved = Path(path).resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                candidate = self.inspect(path)
                result.append(candidate)
                self.journal("emulator_detected", path=str(candidate.path), architecture=candidate.architecture,
                             sha256=candidate.sha256, identity_source=candidate.identity_source)
            except (ValueError, OSError):
                continue
        return sorted(result, key=lambda candidate: str(candidate.path).casefold())
