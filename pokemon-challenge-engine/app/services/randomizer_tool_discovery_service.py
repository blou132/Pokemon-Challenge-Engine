"""Bounded local discovery; explicit choices are preserved and never persisted here."""

from dataclasses import dataclass
import os
from pathlib import Path
import time

from app.services import rom_transformation_service as transformation


MAX_PATH_ENTRIES = 32
MAX_JAVA_PROBES = 3
MAX_JAR_BYTES = 64 * 1024 * 1024
DISCOVERY_SECONDS = 20


@dataclass(frozen=True)
class RandomizerToolDiscovery:
    java_path: str
    jar_path: str
    verified: bool
    message: str


def _automatic_path(value: str) -> Path | None:
    # Never turn an empty/relative PATH entry into a search of the working folder.
    if not value or len(value) > 4096 or "\0" in value or value.startswith(("\\\\", "//")):
        return None
    path = Path(value)
    return path if path.is_absolute() else None


class RandomizerToolDiscoveryService:
    def __init__(self, base_dir: Path, *, environment=None):
        self.base_dir = Path(base_dir)
        self.environment = dict(os.environ if environment is None else environment)

    def _java_candidates(self):
        name = "java.exe" if os.name == "nt" else "java"
        home = _automatic_path(self.environment.get("JAVA_HOME", ""))
        if home is not None:
            yield home / "bin" / name
        entries = self.environment.get("PATH", "").split(os.pathsep, MAX_PATH_ENTRIES)
        for value in entries[:MAX_PATH_ENTRIES]:
            folder = _automatic_path(value)
            if folder is not None:
                yield folder / name

    def discover(self, java_path: str = "", jar_path: str = "") -> RandomizerToolDiscovery:
        deadline = time.monotonic() + DISCOVERY_SECONDS
        selected_java, selected_jar = java_path.strip(), jar_path.strip()

        def result(verified, message):
            return RandomizerToolDiscovery(selected_java, selected_jar, verified, message)

        jars = (Path(selected_jar),) if selected_jar else (
            self.base_dir / "PokeRandoZX.jar", self.base_dir / "tools" / "randomizer" / "PokeRandoZX.jar")
        jar = None
        for candidate in jars:
            if time.monotonic() >= deadline:
                break
            try:
                candidate = transformation._regular(candidate)
                if candidate.stat().st_size > MAX_JAR_BYTES:
                    raise ValueError("JAR trop volumineux pour la détection automatique.")
                if transformation.file_hash(candidate) != transformation.ZX_JAR_SHA256:
                    raise ValueError("JAR non reconnu. Choisissez le PokeRandoZX.jar officiel de ZX 4.6.1.")
            except (OSError, ValueError):
                if selected_jar:
                    return result(False, "Le JAR choisi est absent ou non reconnu. Choix conservé ; sélectionnez le JAR officiel ZX 4.6.1.")
                continue
            jar = candidate
            if not selected_jar:
                selected_jar = str(jar)
            break
        if jar is None:
            return result(False, "JAR officiel ZX 4.6.1 non trouvé dans le stockage local. Sélectionnez PokeRandoZX.jar, puis relancez la détection.")

        candidates = (Path(selected_java),) if selected_java else self._java_candidates()
        seen, probes = set(), 0
        for candidate in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or probes >= MAX_JAVA_PROBES:
                break
            try:
                resolved = candidate.resolve(strict=True)
                if not selected_java and _automatic_path(str(resolved)) is None:
                    continue
                if resolved in seen:
                    continue
                seen.add(resolved)
                service = transformation.RomTransformationService(resolved, jar)
                probes += 1
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                service.validate_tool(timeout=remaining)
            except (OSError, ValueError):
                if selected_java:
                    return result(False, "Java choisi n'a pas pu être vérifié (JDK 11+ requis). Choix conservé ; vérifiez ce chemin ou sélectionnez un autre JDK.")
                continue
            if not selected_java:
                selected_java = str(service.java_path)
            return result(True, "Java et JAR vérifiés. Enregistrez les outils locaux pour les prochaines parties. Compatibilité de la ROM encore à vérifier.")
        return result(False, "JAR officiel vérifié, mais aucun Java compatible vérifié dans les limites de recherche. Sélectionnez un JDK 11+ ou relancez la détection.")
