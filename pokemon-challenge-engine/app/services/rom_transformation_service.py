"""Reproducible, external ZX transformations; input files are never tool outputs.

The adapter calls ZX's explicit-seed Java API, not its seed-less CLI. A successful
transformation proves a structurally reread ROM, not playability in DeSmuME.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
from uuid import uuid4

from app.models.run import utc_now
from app.services.config_service import _invalid_constant, _strict_pairs
from app.services.discovery_safety import file_hash, file_signature, local_path
from app.services.rom_preparation_service import identity


ZX_VERSION = "4.6.1"
ZX_COMMIT = "7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c"
ZX_JAR_SHA256 = "380dc1e6c704a9a4ed8433e8b7892a149390f8912b9107a2a0e7263cfd71c7d8"
ZX_RELEASE = "https://github.com/Ajarmar/universal-pokemon-randomizer-zx/releases/tag/v4.6.1"
CATEGORIES = ("wild", "starters", "trainers", "movesets", "abilities", "field_items", "evolutions", "types")
SUPPORTED_CODES = {"black": "IRBF", "white": "IRAF", "black2": "IREF", "white2": "IRDF"}
GEN5_TYPES = frozenset({"normal", "fighting", "flying", "poison", "ground", "rock", "bug", "ghost", "steel",
                       "fire", "water", "grass", "electric", "psychic", "ice", "dragon", "dark"})
OWNER = "pokemon-challenge-engine-rom-transformation"
ADAPTER = Path(__file__).resolve().parents[2] / "tools" / "randomizer" / "PceRandomizer.java"


@dataclass(frozen=True)
class RandomizerOptions:
    categories: tuple[str, ...] = ("wild", "starters", "trainers")
    balanced: bool = False

    def __post_init__(self):
        if not isinstance(self.categories, tuple) or not self.categories or \
                any(not isinstance(item, str) or item not in CATEGORIES for item in self.categories) or \
                len(set(self.categories)) != len(self.categories):
            raise ValueError("Choisissez au moins une catégorie Randomizer prise en charge, sans doublon.")
        if type(self.balanced) is not bool:
            raise ValueError("Le réglage d'équilibrage doit être un booléen.")
        if self.balanced and not set(self.categories) & {"wild", "trainers", "evolutions"}:
            raise ValueError("L'équilibrage concerne les rencontres, dresseurs ou évolutions.")

    def to_dict(self):
        return {"categories": [item for item in CATEGORIES if item in self.categories], "balanced": self.balanced}


@dataclass(frozen=True)
class RomTransformationResult:
    rom_path: Path
    manifest_path: Path
    report_path: Path
    manifest: dict


def _regular(path: Path) -> Path:
    path = local_path(path)
    value = path.stat()
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise ValueError("Transformation refusée : fichier spécial ou lien partagé.")
    return path


def _write_json(path: Path, data):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_identity(path: Path):
    with _regular(path).open("rb") as handle:
        return identity(handle.read(512))


class RomTransformationService:
    def __init__(self, java_path: str | Path, jar_path: str | Path):
        # Java installations commonly expose a redirecting executable. Resolve
        # that explicit tool selection, while ROM/data paths forbid all links.
        self.java_path = _regular(Path(java_path).resolve(strict=True))
        self.jar_path = _regular(Path(jar_path))

    @classmethod
    def from_local_config(cls, base_dir: Path):
        data = RandomizerToolStore(base_dir).load()
        return cls(data["java_path"], data["jar_path"])

    @staticmethod
    def shiny_rate_support(game_id: str) -> dict:
        return {"original": game_id in SUPPORTED_CODES, "custom_denominators": [],
                "reason": "Aucun patch ROM du taux shiny n'est validé pour ce jeu. Taux original conservé ; aucune écriture RAM."}

    def validate_tool(self) -> str:
        if file_hash(_regular(self.jar_path)) != ZX_JAR_SHA256:
            raise ValueError("JAR non reconnu. Sélectionnez PokeRandoZX.jar de la release officielle ZX 4.6.1.")
        completed = self._execute([str(self.java_path), "-version"], cwd=self.jar_path.parent, timeout=20)
        version = (completed.stderr or completed.stdout).strip()
        match = re.search(r'version "(\d+)(?:\.(\d+))?', version)
        major = int(match.group(2) or 0) if match and match.group(1) == "1" else int(match.group(1)) if match else 0
        if not version or len(version) > 4096 or major < 11:
            raise ValueError("Impossible de vérifier Java. Un JDK 11 ou supérieur est nécessaire.")
        return version

    @staticmethod
    def _execute(command: list[str], *, cwd: Path, timeout: int):
        try:
            result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=timeout, check=False,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Le Randomizer a dépassé le délai autorisé. La source est conservée.") from exc
        except OSError as exc:
            raise ValueError("Impossible de lancer Java. Vérifiez le JDK sélectionné.") from exc
        if result.returncode:
            if (cwd / "owner.json").is_file():
                with (cwd / "randomizer-process.log").open("x", encoding="utf-8") as handle:
                    handle.write((result.stderr or result.stdout)[-16384:])
            # Do not present an untrusted external stack trace as a UI error.
            raise ValueError("Le Randomizer a refusé la transformation. Vérifiez Java (JDK 11+), la ROM originale et les paramètres.")
        return result

    @staticmethod
    def _validate_report(path: Path, game_code: str, options: RandomizerOptions) -> dict:
        if _regular(path).stat().st_size > 1024 * 1024:
            raise ValueError("Rapport Randomizer trop volumineux.")
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or report.get("schema_version") != 1 or report.get("tool_version") != ZX_VERSION or report.get("game_code") != game_code:
            raise ValueError("Identité ou version du rapport Randomizer incorrecte.")
        categories = report.get("categories", {})
        if not isinstance(categories, dict):
            raise ValueError("Catégories du rapport invalides.")
        for name in CATEGORIES:
            pair = categories.get(name, {})
            if not isinstance(pair, dict) or any(not isinstance(pair.get(key), str) or len(pair[key]) != 64 or
                   any(char not in "0123456789abcdef" for char in pair[key]) for key in ("before", "after")):
                raise ValueError("Empreinte de catégorie Randomizer incorrecte.")
            if name in options.categories and pair["before"] == pair["after"]:
                raise ValueError(f"La catégorie demandée n'a pas changé : {name}.")
            if name not in options.categories and pair["before"] != pair["after"]:
                raise ValueError(f"Une catégorie non sélectionnée a changé : {name}.")
        rows = report.get("pokemon")
        if not isinstance(rows, list) or not 649 <= len(rows) <= 1024:
            raise ValueError("La table des types effectifs est incomplète.")
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Entrée de table effective invalide.")
            species, form, types = row.get("species_id"), row.get("form"), row.get("types")
            if type(species) is not int or not 1 <= species <= 649 or type(form) is not int or not 0 <= form <= 31 or \
                    (species, form) in seen or not isinstance(types, list) or not 1 <= len(types) <= 2 or \
                    any(not isinstance(value, str) or value not in GEN5_TYPES for value in types) or len(set(types)) != len(types):
                raise ValueError("Table des types effectifs invalide ou ambiguë.")
            seen.add((species, form))
            evolutions = row.get("evolutions")
            if not isinstance(evolutions, list) or any(type(item) is not int or not 1 <= item <= 649 for item in evolutions):
                raise ValueError("Table des évolutions effectives invalide.")
            if "identity_evolutions" in row:
                individuals = row["identity_evolutions"]
                if not isinstance(individuals, list) or any(type(item) is not int or item not in evolutions for item in individuals):
                    raise ValueError("Évolutions d'identité incohérentes avec les données de la ROM.")
        if any((species, 0) not in seen for species in range(1, 650)):
            raise ValueError("Des espèces manquent dans la table des types effectifs.")
        return report

    def transform(self, source: str | Path, destination_directory: str | Path, *, game_id: str,
                  seed: int, options: RandomizerOptions) -> RomTransformationResult:
        if type(seed) is not int or not 0 <= seed <= 2**63 - 1:
            raise ValueError("La seed doit être un entier compris entre 0 et 9223372036854775807.")
        if not isinstance(options, RandomizerOptions):
            raise ValueError("Paramètres Randomizer invalides.")
        source = _regular(Path(source))
        destination = local_path(destination_directory)
        if destination.exists() or not destination.parent.is_dir() or source.is_relative_to(destination):
            raise ValueError("Choisissez un nouveau dossier de transformation dans un dossier existant.")
        found = _read_identity(source)
        if source.suffix.lower() != ".nds" or game_id not in SUPPORTED_CODES or found != (game_id, SUPPORTED_CODES[game_id], "FR", 0):
            raise ValueError("Seules les ROM originales Gen V françaises révision 0 sont prises en charge par cet adaptateur.")
        java_version = self.validate_tool()
        source_signature, source_hash = file_signature(source), file_hash(source)
        if file_signature(source) != source_signature:
            raise ValueError("La ROM source a changé pendant sa vérification.")
        staging = local_path(destination.parent / (".pce-transform-" + uuid4().hex))
        staging.mkdir()
        _write_json(staging / "owner.json", {"owner": OWNER, "destination": destination.name})
        try:
            working = staging / "source.nds"
            with source.open("rb") as reader, working.open("xb") as writer:
                shutil.copyfileobj(reader, writer, 1024 * 1024)
                writer.flush()
                os.fsync(writer.fileno())
            if file_signature(source) != source_signature or file_hash(working) != source_hash:
                raise ValueError("La ROM source a changé pendant la copie.")
            adapter = staging / "PceRandomizer.java"
            with _regular(ADAPTER).open("rb") as reader, adapter.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
            output, report_path = staging / "derived.nds", staging / "report.json"
            self._execute([str(self.java_path), "-Xmx2048M", "-Djava.awt.headless=true", "-cp", str(self.jar_path),
                           str(adapter), str(working), str(output), str(report_path), str(seed),
                           ",".join(options.to_dict()["categories"]), str(options.balanced).lower(), found[1]],
                          cwd=staging, timeout=600)
            if file_signature(source) != source_signature or file_hash(source) != source_hash or \
                    file_hash(working) != source_hash or file_hash(self.jar_path) != ZX_JAR_SHA256:
                raise ValueError("L'entrée ou l'outil a changé pendant la transformation ; résultat non publié.")
            if _read_identity(output) != found:
                raise ValueError("La ROM dérivée possède une identité inattendue.")
            output_hash = file_hash(output)
            if source_hash == output_hash:
                raise ValueError("La transformation n'a pas modifié la ROM.")
            report = self._validate_report(report_path, found[1], options)
            manifest = {"schema_version": 1, "owner": OWNER, "created_at": utc_now(), "game_id": game_id,
                        "game_code": found[1], "region": "FR", "revision": 0,
                        "tool": {"name": "Universal Pokemon Randomizer ZX", "version": ZX_VERSION,
                                 "commit": ZX_COMMIT, "jar_sha256": ZX_JAR_SHA256, "release": ZX_RELEASE,
                                 "adapter_sha256": file_hash(adapter), "java": java_version},
                        "seed": seed, "options": options.to_dict(), "source_sha256": source_hash,
                        "source_size": source.stat().st_size, "output_sha256": output_hash,
                        "output_size": output.stat().st_size, "output_file": "derived.nds",
                        "report_sha256": file_hash(report_path), "settings_string": report.get("settings_string"),
                        "transformation_order": ["upr-zx-4.6.1"],
                        "validation": {"source_unchanged": True, "rom_reloaded_by_tool": True,
                                       "selected_categories_changed": True, "emulator": "not_tested",
                                       "lua": "not_tested", "shiny_rate": "original"}}
            _write_json(staging / "manifest.json", manifest)
            # Remove only our verified working copy; retain derived ROM and provenance.
            _regular(working).unlink()
            if destination.exists():
                raise ValueError("Le dossier de destination vient d'être créé ; aucun remplacement effectué.")
            staging.rename(destination)
            return RomTransformationResult(destination / "derived.nds", destination / "manifest.json",
                                           destination / "report.json", manifest)
        except Exception:
            # Keep recoverable local evidence in the unpublished, explicitly owned
            # staging directory; it is never usable as an adventure automatically.
            try:
                _write_json(staging / "failed.json", {"owner": OWNER, "status": "not_published"})
            except OSError:
                pass  # The primary exception must survive a full disk or lost directory.
            raise


def transformation_options(challenge_snapshot: dict) -> RandomizerOptions | None:
    """Absent means a historical declaration, never an implicit ROM operation."""
    value = challenge_snapshot.get("settings", {}).get("rom_transformation")
    if value is None:
        return None
    if "randomizer" not in challenge_snapshot.get("active_rules", []) or not isinstance(value, dict) or \
            set(value) != {"kind", "categories", "balanced"} or value.get("kind") != "zx" or \
            not isinstance(value.get("categories"), list):
        raise ValueError("Configuration de transformation ROM invalide ou Randomizer inactif.")
    seed = challenge_snapshot.get("seed")
    if type(seed) is not int or not 0 <= seed <= 2**63 - 1:
        raise ValueError("La seed Randomizer doit être comprise entre 0 et 9223372036854775807.")
    return RandomizerOptions(tuple(value["categories"]), value["balanced"])


class RandomizerToolStore:
    """Paths local to this PCE installation, never embedded in reusable profiles."""
    def __init__(self, base_dir: Path):
        self.path = local_path(Path(base_dir) / "randomizer.local.json")

    def load(self) -> dict:
        if not self.path.exists():
            raise ValueError("Configurez Java (JDK 11+) et le JAR officiel ZX 4.6.1 avant de créer une ROM Randomizer.")
        if _regular(self.path).stat().st_size > 16384:
            raise ValueError("Configuration Randomizer trop volumineuse.")
        data = json.loads(self.path.read_text(encoding="utf-8"), object_pairs_hook=_strict_pairs, parse_constant=_invalid_constant)
        if not isinstance(data, dict) or set(data) != {"schema_version", "java_path", "jar_path"} or \
                type(data.get("schema_version")) is not int or data["schema_version"] != 1 or \
                any(not isinstance(data.get(key), str) or not data[key].strip() or len(data[key]) > 4096 or "\0" in data[key]
                    for key in ("java_path", "jar_path")):
            raise ValueError("Configuration des outils Randomizer invalide.")
        return data

    def save(self, java_path: str | Path, jar_path: str | Path):
        service = RomTransformationService(java_path, jar_path)
        service.validate_tool()
        if self.path.exists():
            _regular(self.path)
        temporary = local_path(self.path.with_name(".randomizer-config-" + uuid4().hex + ".local.json"))
        try:
            _write_json(temporary, {"schema_version": 1, "java_path": str(service.java_path), "jar_path": str(service.jar_path)})
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                _regular(temporary).unlink()


def verified_transformation_report(directory: Path, rom: Path, *, game_id: str, rom_sha256: str,
                                   configuration: dict) -> dict:
    """Verify persisted derivation evidence against the actual adventure ROM."""
    directory = local_path(directory)
    manifest_path = _regular(directory / "manifest.json")
    if manifest_path.stat().st_size > 65536:
        raise ValueError("Manifeste Randomizer trop volumineux.")
    data = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_strict_pairs, parse_constant=_invalid_constant)
    options = transformation_options(configuration)
    if options is None or not isinstance(data, dict) or data.get("owner") != OWNER or data.get("schema_version") != 1 or \
            data.get("game_id") != game_id or data.get("game_code") != SUPPORTED_CODES.get(game_id) or \
            data.get("region") != "FR" or data.get("revision") != 0 or data.get("seed") != configuration.get("seed") or \
            data.get("options") != options.to_dict() or data.get("output_file") != "derived.nds" or \
            data.get("transformation_order") != ["upr-zx-4.6.1"]:
        raise ValueError("La provenance de la ROM dérivée ne correspond pas à cette partie.")
    tool = data.get("tool")
    if not isinstance(tool, dict) or tool.get("version") != ZX_VERSION or tool.get("commit") != ZX_COMMIT or \
            tool.get("jar_sha256") != ZX_JAR_SHA256 or tool.get("adapter_sha256") != file_hash(_regular(directory / "PceRandomizer.java")):
        raise ValueError("La provenance de l'outil Randomizer a changé.")
    if data.get("output_sha256") != rom_sha256 or file_hash(_regular(rom)) != rom_sha256 or \
            data.get("output_size") != rom.stat().st_size or \
            _read_identity(rom) != (game_id, SUPPORTED_CODES[game_id], "FR", 0):
        raise ValueError("La ROM dérivée ne correspond plus à son manifeste.")
    report_path = _regular(directory / "report.json")
    if data.get("report_sha256") != file_hash(report_path):
        raise ValueError("Les données effectives de la ROM dérivée ont changé.")
    return RomTransformationService._validate_report(report_path, SUPPORTED_CODES[game_id], options)
