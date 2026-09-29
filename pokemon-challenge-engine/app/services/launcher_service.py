"""Lancement direct de DeSmuME sans modification de ROM ni de sauvegarde."""

import logging
import os
from pathlib import Path
import subprocess

from app.services.config_service import AppConfig

logger = logging.getLogger(__name__)


class LauncherService:
    """Valide les chemins puis confie une ROM à l'émulateur standalone."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def validate(self, game_id: str) -> list[str]:
        """Contrôle uniquement les métadonnées des chemins, jamais le contenu des fichiers."""
        errors: list[str] = []
        if game_id not in {"black", "black2"}:
            return ["Ce jeu n'est pas pris en charge pour le lancement dans la V0.1."]
        try:
            config = AppConfig.from_dict(self.config.to_dict())
        except (AttributeError, TypeError, ValueError):
            return ["La configuration des chemins est invalide."]
        if not config.desmume_path.strip():
            errors.append("Sélectionnez l'exécutable DeSmuME dans les paramètres.")
        else:
            emulator = Path(config.desmume_path)
            if emulator.suffix.lower() != ".exe":
                errors.append("Le chemin DeSmuME doit désigner un exécutable Windows .exe.")
            elif not self._is_file(emulator):
                errors.append("L'exécutable DeSmuME est introuvable ou inaccessible.")
        rom_path = config.rom_paths.get(game_id, "")
        if not rom_path.strip():
            errors.append("Sélectionnez la ROM de ce jeu dans les paramètres.")
        else:
            rom = Path(rom_path)
            if rom.suffix.lower() != ".nds":
                errors.append("La ROM doit être un fichier Nintendo DS .nds.")
            elif not self._is_file(rom):
                errors.append("La ROM configurée est introuvable ou inaccessible.")
        return errors

    @staticmethod
    def _is_file(path: Path) -> bool:
        try:
            return path.is_file()
        except (OSError, ValueError):
            return False

    def build_command(self, game_id: str) -> list[str]:
        errors = self.validate(game_id)
        if errors:
            raise ValueError("\n".join(errors))
        return [str(Path(self.config.desmume_path).resolve()), str(Path(self.config.rom_paths[game_id]).resolve())]

    def launch(self, game_id: str) -> subprocess.Popen[bytes]:
        """Retourne un processus démarré ; cela ne prouve pas que le jeu est chargé."""
        command = self.build_command(game_id)
        logger.debug("Commande DeSmuME : %r", command)
        try:
            process = subprocess.Popen(
                command, shell=False, cwd=str(Path(command[0]).parent),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError as exc:
            logger.error("Impossible de démarrer DeSmuME (erreur système %s).", exc.errno)
            raise ValueError("Impossible de démarrer DeSmuME. Vérifiez l'exécutable et ses droits d'accès.") from exc
        logger.info("Processus DeSmuME démarré pour %s (PID %s).", game_id, process.pid)
        return process
