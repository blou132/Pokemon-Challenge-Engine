"""Propose des sauvegardes locales par association de chemins, jamais par contenu supposé."""

from datetime import datetime, timezone
from pathlib import Path

from app.services.discovery_models import GameCandidate, SaveCandidate
from app.services.discovery_safety import bounded_files, local_path
from app.services.emulator_settings_service import IniDocument


class SaveDiscoveryService:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.state_slots_directory: Path | None = None

    @staticmethod
    def _ini_paths(emulator_path: str | Path) -> tuple[Path | None, Path | None]:
        """PathInfo::ReadKeyW/SwitchPath : chemins relatifs au module, valeurs par défaut documentées."""
        executable = local_path(emulator_path)
        ini = local_path(executable.parent / "desmume.ini")
        if not ini.is_file():
            return None, None
        if ini.stat().st_size > 1024 * 1024:
            raise ValueError("Configuration DeSmuME trop volumineuse.")
        document = IniDocument(ini.read_bytes())
        document.require_windows_profile_encoding()
        results = []
        for key in ("Battery", "StateSlots"):
            index = document.entries.get(("pathsettings", key.casefold()))
            value = document.lines[index].split("=", 1)[1].strip().strip('"') if index is not None else key
            if not value:
                value = "."
            path = Path(value)
            results.append(local_path(path if path.is_absolute() else executable.parent / path))
        return tuple(results)

    @classmethod
    def expected_save_path(cls, emulator_path: str | Path, rom_path: str | Path) -> Path | None:
        """Cible Battery déterminée par l'INI réel et le basename chargé ; ne crée rien."""
        battery, _ = cls._ini_paths(emulator_path)
        return local_path(battery / (Path(rom_path).stem + ".dsv")) if battery is not None else None

    def discover(self, candidate: GameCandidate, *, retrobat_root=None, emulator_path=None,
                 configured_directories=(), configured_save=None) -> tuple[SaveCandidate, ...]:
        self.warnings.clear()
        self.state_slots_directory = None
        if not isinstance(candidate, GameCandidate):
            raise ValueError("La recherche de sauvegardes exige un jeu détecté.")
        stems = {candidate.source_path.stem.casefold()}
        if candidate.archive_member:
            stems.add(Path(candidate.archive_member).stem.casefold())
        directories: dict[Path, str] = {}
        explicit = None
        try:
            if configured_save and str(configured_save).strip():
                explicit = local_path(configured_save)
            for raw in tuple(configured_directories)[:32]:
                directories[local_path(raw)] = "Dossier de sauvegardes configuré"
            if retrobat_root is not None:
                root = local_path(retrobat_root)
                for suffix in (Path("saves/nds/DeSmuME"), Path("saves/nds")):
                    folder = local_path(root / suffix)
                    if folder.is_dir():
                        directories[folder] = "Dossier de sauvegardes RetroBat présent"
            # Une sauvegarde placée à côté de la ROM reste un candidat, pas un chemin créé.
            directories[candidate.source_path.parent] = "Dossier de la ROM source"
            if emulator_path and str(emulator_path).strip():
                battery, slots = self._ini_paths(emulator_path)
                if battery is not None:
                    directories[battery] = "Dossier Battery lu dans desmume.ini"
                self.state_slots_directory = slots
        except (OSError, ValueError) as exc:
            self.warnings.append(str(exc))
        found: dict[Path, SaveCandidate] = {}

        def consider(path: Path, reason: str, *, selected=False):
            suffix = path.suffix.lower()
            if suffix not in {".dsv", ".srm"} or not path.is_file():
                return
            stem = path.stem.casefold()
            exact = stem in stems
            related = any(stem.startswith(name + separator) for name in stems for separator in ("_", " - ", " ("))
            if not selected and not exact and not related:
                return
            value = path.stat()
            # Vérifier l'accès en lecture, sans parser ni modifier la sauvegarde.
            with path.open("rb") as reader:
                reader.read(1)
            compatible = suffix == ".dsv"
            confidence = "high" if exact and compatible and value.st_size > 0 else "possible"
            detail = reason + (" ; nom exact associé à la ROM" if exact else " ; association à confirmer")
            if not compatible:
                detail += " ; SRAM .srm, import manuel dans DeSmuME requis"
            found[path] = SaveCandidate(path, value.st_size,
                                        datetime.fromtimestamp(value.st_mtime, timezone.utc).isoformat(),
                                        confidence, detail, compatible)

        if explicit is not None:
            try:
                if not explicit.is_file():
                    self.warnings.append("La sauvegarde précédemment configurée est introuvable ; choisissez son nouvel emplacement.")
                consider(explicit, "Chemin précédemment configuré", selected=True)
            except (OSError, ValueError) as exc:
                self.warnings.append(str(exc))
        for folder, reason in directories.items():
            try:
                if not folder.is_dir():
                    continue
                for path in bounded_files(folder):
                    consider(path, reason)
            except (OSError, ValueError) as exc:
                self.warnings.append(str(exc))
        return tuple(sorted(found.values(), key=lambda item: (item.confidence != "high", str(item.path).casefold())))

    def proposed(self, candidates) -> SaveCandidate | None:
        # Une recherche interrompue peut cacher un second candidat crédible.
        if self.warnings:
            return None
        credible = [item for item in candidates if item.compatible]
        return credible[0] if len(credible) == 1 and credible[0].confidence == "high" else None
