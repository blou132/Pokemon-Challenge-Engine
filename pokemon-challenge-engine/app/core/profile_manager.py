"""Persistance des profils dans trois fichiers JSON, sans accès aux sauvegardes du jeu."""

import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any
import unicodedata
from uuid import uuid4

from app.models.challenge import Challenge
from app.models.profile import (
    Profile, default_progress, validate_history, validate_json_data, validate_profile_id, validate_progress,
)

logger = logging.getLogger(__name__)


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Clé JSON dupliquée : {key}.")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Valeur JSON non autorisée : {value}.")


def _read_json(path: Path) -> Any:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_strict_pairs,
                          parse_constant=_invalid_constant)
        validate_json_data(data)
        return data
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError(f"Impossible de lire « {path.name} » : fichier absent, inaccessible ou invalide.") from exc


class ProfileManager:
    """Gère uniquement le dossier des profils de l'application."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.warnings: list[str] = []

    def _directory(self, profile_id: str) -> Path:
        validate_profile_id(profile_id)
        directory = self.root / profile_id
        try:
            if directory.is_symlink() or directory.is_junction():
                raise ValueError("Un profil ne peut pas utiliser un lien symbolique ou une jonction de dossier.")
            if directory.resolve().parent != self.root:
                raise ValueError("Le dossier du profil sort du dossier de stockage autorisé.")
        except (OSError, RuntimeError) as exc:
            raise ValueError("Le dossier du profil est inaccessible ou contient un lien invalide.") from exc
        return directory

    def _file(self, directory: Path, filename: str) -> Path:
        path = directory / filename
        try:
            if path.is_symlink():
                raise ValueError(f"Le fichier « {filename} » ne peut pas être un lien symbolique.")
            if path.resolve().parent != directory.resolve():
                raise ValueError(f"Le fichier « {filename} » sort du dossier du profil.")
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"Le fichier « {filename} » est inaccessible ou contient un lien invalide.") from exc
        return path

    def _warning(self, message: str) -> None:
        self.warnings.append(message)
        logger.warning(message)

    def create(self, name: str, challenge: Challenge) -> Profile:
        """Crée un nouveau dossier unique ; ne remplace jamais un profil existant."""
        self.warnings.clear()
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("Le nom du profil doit contenir entre 1 et 100 caractères.")
        if not isinstance(challenge, Challenge):
            raise ValueError("Le challenge du profil est invalide.")
        try:
            validated_challenge = Challenge.from_dict(challenge.to_dict())
        except (TypeError, RecursionError) as exc:
            raise ValueError("Le challenge contient une structure invalide ou trop profondément imbriquée.") from exc
        slug = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
        slug = "_".join("".join(char if char.isalnum() else " " for char in slug).split())[:32]
        profile_id = f"{slug or 'profil'}_{uuid4().hex[:12]}"
        profile = Profile(id=profile_id, name=name.strip(), challenge=validated_challenge)
        profile.validate()
        directory = self._directory(profile_id)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            directory.mkdir(exist_ok=False)
            self._write(profile, directory)
        except OSError as exc:
            raise ValueError("Impossible de créer le profil : vérifiez les droits d'écriture.") from exc
        logger.info("Profil créé : %s", profile.id)
        return profile

    def load(self, profile_id: str) -> Profile:
        """Charge le challenge ; un suivi absent ou corrompu est signalé et remis à zéro en mémoire."""
        self.warnings.clear()
        return self._load(profile_id)

    def _load(self, profile_id: str) -> Profile:
        directory = self._directory(profile_id)
        data = _read_json(self._file(directory, "challenge.json"))
        if not isinstance(data, dict):
            raise ValueError("Le fichier challenge.json doit contenir un objet JSON.")
        if data.get("profile_id", profile_id) != profile_id:
            raise ValueError("L'identifiant enregistré ne correspond pas au dossier du profil.")
        challenge_data = {key: value for key, value in data.items() if key not in {"profile_id", "profile_name"}}
        challenge = Challenge.from_dict(challenge_data)
        progress = self._load_optional(directory, "progress.json", validate_progress, default_progress())
        history = self._load_optional(directory, "history.json", validate_history, [])
        profile = Profile(profile_id, data.get("profile_name", profile_id), challenge, progress, history)
        profile.validate()
        return profile

    def _load_optional(self, directory: Path, filename: str, validator: Any, fallback: Any) -> Any:
        try:
            return validator(_read_json(self._file(directory, filename)))
        except ValueError:
            self._warning(f"Profil « {directory.name} » : {filename} absent ou invalide ; valeurs par défaut utilisées en mémoire.")
            return fallback

    def list_profiles(self) -> list[Profile]:
        """Ignore les profils illisibles, tout en conservant leurs diagnostics."""
        self.warnings.clear()
        if not self.root.exists():
            return []
        profiles: list[Profile] = []
        try:
            directories = sorted(self.root.iterdir(), key=lambda path: path.name)
        except OSError:
            self._warning("Le dossier des profils est inaccessible.")
            return []
        for directory in directories:
            if directory.name.startswith("."):
                continue
            try:
                if directory.is_symlink() or directory.is_junction():
                    raise ValueError("Les liens symboliques et jonctions de dossier ne sont pas des profils.")
                if not directory.is_dir():
                    continue
                profiles.append(self._load(directory.name))
            except (ValueError, OSError) as exc:
                self._warning(f"Profil « {directory.name} » ignoré : {exc}")
        return profiles

    def save(self, profile: Profile) -> None:
        """Met à jour explicitement un profil valide, sans écraser de fichier corrompu."""
        self.warnings.clear()
        profile.validate()
        directory = self._directory(profile.id)
        if not directory.is_dir():
            raise ValueError("Ce profil n'existe plus. Créez un nouveau profil pour le sauvegarder.")
        # Lire avant toute écriture protège les fichiers existants, même si un fallback a été chargé.
        original = _read_json(self._file(directory, "challenge.json"))
        if not isinstance(original, dict) or original.get("profile_id", profile.id) != profile.id:
            raise ValueError("Le profil existant est corrompu ; sauvegarde refusée pour le préserver.")
        original_name = original.get("profile_name", profile.id)
        if not isinstance(original_name, str) or not original_name.strip() or len(original_name) > 100:
            raise ValueError("Le nom du profil existant est corrompu ; sauvegarde refusée pour le préserver.")
        Challenge.from_dict({key: value for key, value in original.items() if key not in {"profile_name", "profile_id"}})
        for filename, validator in (("progress.json", validate_progress), ("history.json", validate_history)):
            path = self._file(directory, filename)
            if path.exists():
                try:
                    validator(_read_json(path))
                except ValueError as exc:
                    raise ValueError(f"Le fichier {filename} existant est corrompu ; créez un nouveau profil pour le préserver.") from exc
        try:
            self._write(profile, directory)
        except OSError as exc:
            raise ValueError("Impossible de sauvegarder le profil : vérifiez les droits d'écriture.") from exc
        logger.info("Profil sauvegardé : %s", profile.id)

    def _write(self, profile: Profile, directory: Path) -> None:
        challenge_data = profile.challenge.to_dict() | {"profile_id": profile.id, "profile_name": profile.name}
        payloads = {"challenge.json": challenge_data, "progress.json": validate_progress(profile.progress),
                    "history.json": validate_history(profile.history)}
        # Chaque remplacement est atomique ; tous les contenus sont préparés avant le premier remplacement.
        prepared: list[tuple[Path, Path]] = []
        try:
            for filename, data in payloads.items():
                destination = self._file(directory, filename)
                serialized = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                                 prefix=".tmp_", suffix=".json", delete=False) as handle:
                    temporary = Path(handle.name)
                    prepared.append((temporary, destination))
                    handle.write(serialized)
                    handle.flush()
                    os.fsync(handle.fileno())
            for temporary, destination in prepared:
                temporary.replace(destination)
        finally:
            for temporary, _ in prepared:
                temporary.unlink(missing_ok=True)
