"""Configuration locale des chemins choisis par l'utilisateur."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class AppConfig:
    """Les chemins sont informatifs jusqu'à la validation du lancement."""

    retrobat_path: str = ""
    desmume_path: str = ""
    rom_paths: dict[str, str] = field(default_factory=lambda: {"black": "", "black2": ""})
    save_path: str = ""

    @classmethod
    def from_dict(cls, value: Any) -> "AppConfig":
        if not isinstance(value, dict):
            raise ValueError("La configuration doit être un objet JSON.")
        if set(value) - {"retrobat_path", "desmume_path", "rom_paths", "save_path"}:
            raise ValueError("La configuration contient un champ inconnu.")
        for key in ("retrobat_path", "desmume_path", "save_path"):
            if not isinstance(value.get(key, ""), str) or "\x00" in value.get(key, ""):
                raise ValueError(f"Le chemin « {key} » doit être un texte valide.")
            _validate_unicode(value.get(key, ""))
        paths = value.get("rom_paths", {})
        if not isinstance(paths, dict) or any(
            not isinstance(key, str) or not isinstance(path, str) or "\x00" in path
            for key, path in paths.items()
        ):
            raise ValueError("Les chemins des ROM doivent associer des jeux à des chemins textuels.")
        for key, path in paths.items():
            _validate_unicode(key)
            _validate_unicode(path)
        return cls(retrobat_path=value.get("retrobat_path", ""), desmume_path=value.get("desmume_path", ""),
                   rom_paths={"black": "", "black2": ""} | paths, save_path=value.get("save_path", ""))

    def to_dict(self) -> dict[str, Any]:
        # Valider avant de copier évite une récursion sur un objet Python mal formé.
        validated = self.from_dict({"retrobat_path": self.retrobat_path, "desmume_path": self.desmume_path,
                                    "rom_paths": self.rom_paths, "save_path": self.save_path})
        return {"retrobat_path": validated.retrobat_path, "desmume_path": validated.desmume_path,
                "rom_paths": dict(validated.rom_paths), "save_path": validated.save_path}


def _validate_unicode(value: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("La configuration contient un texte Unicode invalide.") from exc


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("La configuration contient une clé JSON dupliquée.")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("La configuration contient une valeur JSON non autorisée.")


class ConfigService:
    """Charge sans écriture automatique et sauvegarde par remplacement atomique."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.warnings: list[str] = []

    def _read(self) -> AppConfig:
        data = json.loads(self.path.read_text(encoding="utf-8-sig"), object_pairs_hook=_strict_pairs,
                          parse_constant=_invalid_constant)
        return AppConfig.from_dict(data)

    def load(self) -> AppConfig:
        self.warnings.clear()
        if not self.path.exists():
            logger.info("Aucune configuration locale ; chemins à renseigner.")
            return AppConfig()
        try:
            config = self._read()
        except (OSError, UnicodeError, ValueError, RecursionError):
            message = "Configuration inaccessible ou invalide : chemins vides utilisés. Le fichier existant est conservé."
            self.warnings.append(message)
            logger.warning(message)
            return AppConfig()
        logger.info("Configuration locale chargée.")
        return config

    def save(self, config: AppConfig) -> None:
        """Préserve automatiquement une copie du fichier corrompu avant une sauvegarde explicite."""
        if not isinstance(config, AppConfig):
            raise ValueError("La configuration fournie est invalide.")
        validated = AppConfig.from_dict(config.to_dict())
        serialized = json.dumps(validated.to_dict(), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        self.warnings.clear()
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                try:
                    self._read()
                except (OSError, UnicodeError, ValueError, RecursionError):
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                    backup = self.path.with_name(f"{self.path.name}.invalid_{stamp}_{uuid4().hex[:6]}.bak")
                    shutil.copy2(self.path, backup)
                    message = f"L'ancienne configuration invalide a été conservée dans {backup.name}."
                    self.warnings.append(message)
                    logger.warning(message)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".config_", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        except OSError as exc:
            raise ValueError("Impossible d'enregistrer la configuration : vérifiez les droits d'écriture.") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        logger.info("Configuration locale enregistrée.")
