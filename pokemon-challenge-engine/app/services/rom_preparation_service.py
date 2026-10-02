"""Préparation locale .nds/.zip, cache immuable et aucun téléchargement de jeu."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import tempfile
import zipfile

from app.core.game_detector import GAME_CODE_PREFIXES, GameDetector
from app.services.config_service import _invalid_constant, _strict_pairs
from app.services.discovery_models import GameCandidate, PreparedRom
from app.services.discovery_safety import file_hash, file_signature, local_path

CACHE_OWNER = "pokemon-challenge-engine-rom-cache"
MAX_ROM_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 2048
MAX_CENTRAL_BYTES = 4 * 1024 * 1024
REGIONS = {"F": "FR", "O": "EN", "D": "DE", "I": "IT", "J": "JP", "K": "KO", "S": "ES"}


def _check_desmume_path(path: Path) -> None:
    # DeSmuME conserve des buffers Win32 MAX_PATH (260, terminaison comprise).
    if len(str(path).encode("utf-16-le")) // 2 > 259:
        raise ValueError("Chemin ROM trop long pour DeSmuME (259 caractères maximum). "
                         "Déplacez PCE ou son cache vers un dossier plus court ; la source reste intacte.")


def identity(header: bytes) -> tuple[str, str, str, int]:
    if len(header) < 32:
        raise ValueError("En-tête Nintendo DS incomplet.")
    try:
        code = header[12:16].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("Code Nintendo DS illisible.") from exc
    game = GAME_CODE_PREFIXES.get(code[:3])
    if game is None or not re.fullmatch(r"[A-Z0-9]{4}", code):
        raise ValueError("Cette ROM n'est pas un des quatre jeux Pokémon Gen V pris en charge.")
    return game, code, REGIONS.get(code[3], "unknown"), header[0x1E]


def _safe_member(name: str) -> str:
    # Les chemins ZIP ne sont jamais utilisés comme destination, mais toute
    # traversée/ambiguïté est refusée avant de lire les membres.
    if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
        raise ValueError("Nom de membre ZIP dangereux ou ambigu.")
    path = PurePosixPath(name)
    parts = name.rstrip("/").split("/")
    if path.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Traversée de dossier dans l'archive ZIP.")
    for part in parts:
        if len(part) > 180 or re.search(r'[:*?"<>|\x00-\x1f]', part) or part.endswith((" ", ".")) or \
                re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part):
            raise ValueError("Nom de fichier ZIP incompatible avec un chemin Windows sûr.")
    return path.name


@contextmanager
def open_safe_zip(path: Path):
    """Borne la table centrale avant que zipfile ne la charge en mémoire."""
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Archive trop volumineuse (limite 2 Gio).")
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 65557))
        tail = handle.read(65557)
    offset = tail.rfind(b"PK\x05\x06")
    if offset < 0 or len(tail) - offset < 22:
        raise ValueError("Archive ZIP invalide ou tronquée.")
    fields = struct.unpack_from("<4s4H2IH", tail, offset)
    _, disk, central_disk, count_disk, count, central_size, _start, comment_size = fields
    if disk or central_disk or count_disk != count or count > MAX_ARCHIVE_ENTRIES or \
            central_size > MAX_CENTRAL_BYTES or offset + 22 + comment_size != len(tail):
        raise ValueError("Archive ZIP fractionnée, ZIP64 ou table trop volumineuse : format non pris en charge.")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) != count:
                raise ValueError("Nombre de membres ZIP incohérent.")
            names = set()
            total = 0
            for info in entries:
                _safe_member(info.orig_filename)
                _safe_member(info.filename)
                folded = info.filename.casefold()
                if folded in names:
                    raise ValueError("L'archive contient des noms de fichiers dupliqués ou ambigus.")
                names.add(folded)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                    raise ValueError("Liens et fichiers spéciaux interdits dans le ZIP.")
                if info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError("Archive chiffrée ou compression non prise en charge.")
                total += info.file_size
                if info.file_size > MAX_ROM_BYTES or total > MAX_ARCHIVE_BYTES or \
                        info.file_size > max(1, info.compress_size) * 2000:
                    raise ValueError("Archive trop volumineuse après décompression ou taux de compression excessif.")
            yield archive
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError("Archive ZIP corrompue ou non prise en charge.") from exc


def inspect_rom_source(source_path: str | Path) -> tuple[GameCandidate, ...]:
    path = local_path(source_path)
    if not path.is_file():
        raise ValueError("ROM ou archive locale introuvable.")
    if path.suffix.lower() == ".nds":
        if path.stat().st_size > MAX_ROM_BYTES:
            raise ValueError("ROM trop volumineuse (limite 1 Gio).")
        detected = GameDetector.detect(path)
        with path.open("rb") as handle:
            game, code, region, revision = identity(handle.read(32))
        if game != detected:
            raise ValueError("Identité de ROM incohérente.")
        return (GameCandidate(path, None, game, code, region, revision, path.stat().st_size, "nds"),)
    if path.suffix.lower() != ".zip":
        raise ValueError("Formats locaux pris en charge : .nds et .zip ; .7z n'est pas disponible.")
    with open_safe_zip(path) as archive:
        members = [info for info in archive.infolist() if not info.is_dir() and info.filename.lower().endswith(".nds")]
        if not members:
            raise ValueError("L'archive ne contient aucune ROM .nds.")
        result = []
        for info in members:
            try:
                with archive.open(info) as handle:
                    game, code, region, revision = identity(handle.read(32))
            except ValueError:
                continue  # Une ROM inconnue ne devient pas un faux jeu Pokémon.
            result.append(GameCandidate(path, info.filename, game, code, region, revision, info.file_size,
                                        "zip", len(members) > 1))
        if not result:
            raise ValueError("Aucun jeu Pokémon Gen V reconnu dans les en-têtes du ZIP.")
        return tuple(result)


class RomPreparationService:
    def __init__(self, cache_root: Path, *, journal=None) -> None:
        self.cache_root = local_path(cache_root)
        self.journal = journal

    def prepare(self, source_path: str | Path, *, member: str | None = None,
                expected_game: str | None = None) -> PreparedRom:
        try:
            return self._prepare(source_path, member=member, expected_game=expected_game)
        except OSError as exc:
            raise ValueError("Préparation impossible : vérifiez les permissions, l'espace disque et les fichiers verrouillés.") from exc

    def _prepare(self, source_path, *, member, expected_game):
        source = local_path(source_path)
        candidates = inspect_rom_source(source)
        if source.suffix.lower() == ".nds":
            _check_desmume_path(source)
            if member is not None:
                raise ValueError("Un fichier .nds n'a pas de membre d'archive.")
            selected = candidates[0]
        else:
            if member is None and any(item.requires_choice for item in candidates):
                raise ValueError("Plusieurs ROM .nds : choisissez explicitement un membre de l'archive.")
            selected = next((item for item in candidates if member is None or item.archive_member == member), None)
            if selected is None:
                raise ValueError("Membre ROM inconnu ou jeu non pris en charge.")
        if expected_game is not None and selected.game_id != expected_game:
            raise ValueError("Le jeu réel de la ROM ne correspond pas au jeu choisi.")
        before = file_signature(source)
        source_hash = file_hash(source)
        if before != file_signature(source):
            raise ValueError("La ROM ou l'archive a changé pendant sa lecture.")
        if source.suffix.lower() == ".nds":
            actual = inspect_rom_source(source)[0]
            if (actual.game_id, actual.game_code, actual.region, actual.revision) != \
                    (selected.game_id, selected.game_code, selected.region, selected.revision) or before != file_signature(source):
                raise ValueError("L'identité de la ROM a changé pendant sa lecture.")
            return PreparedRom(source, selected.game_id, selected.game_code, selected.region, selected.revision,
                               source, None, None, source_hash, True, None)
        member_hash = hashlib.sha256(selected.archive_member.encode("utf-8")).hexdigest()
        parent = local_path(self.cache_root / selected.game_id / source_hash)
        target = local_path(parent / member_hash[:16])
        _check_desmume_path(target / _safe_member(selected.archive_member))
        if target.exists():
            reused = self._reuse(target, selected, source_hash)
            if before != file_signature(source):
                raise ValueError("L'archive a changé pendant la vérification du cache.")
            return reused
        parent.mkdir(parents=True, exist_ok=True)
        lock = parent / f".{member_hash[:16]}.lock"
        try:
            handle = lock.open("xb")
        except FileExistsError as exc:
            raise ValueError("Préparation déjà en cours ; vérifiez un éventuel verrou résiduel.") from exc
        temporary = None
        try:
            handle.close()
            if target.exists():
                reused = self._reuse(target, selected, source_hash)
                if before != file_signature(source):
                    raise ValueError("L'archive a changé pendant la vérification du cache.")
                return reused
            if shutil.disk_usage(parent).free < selected.size + 8 * 1024 * 1024:
                raise ValueError("Espace disque insuffisant pour préparer cette ROM.")
            temporary = Path(tempfile.mkdtemp(dir=parent, prefix=".partial-"))
            with open_safe_zip(source) as archive:
                info = archive.getinfo(selected.archive_member)
                filename = _safe_member(info.filename)
                destination = temporary / filename
                digest = hashlib.sha256()
                size = 0
                with archive.open(info) as reader, destination.open("xb") as writer:
                    while chunk := reader.read(1024 * 1024):
                        size += len(chunk)
                        if size > info.file_size or size > MAX_ROM_BYTES:
                            raise ValueError("La taille décompressée dépasse la taille autorisée.")
                        digest.update(chunk)
                        writer.write(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
                if size != info.file_size:
                    raise ValueError("Extraction ROM incomplète.")
                extracted = inspect_rom_source(destination)[0]
                if (extracted.game_id, extracted.game_code, extracted.region, extracted.revision) != \
                        (selected.game_id, selected.game_code, selected.region, selected.revision):
                    raise ValueError("L'identité a changé pendant la préparation de la ROM.")
                rom_hash = digest.hexdigest()
                if file_hash(destination) != rom_hash or before != file_signature(source) or \
                        file_hash(source) != source_hash or before != file_signature(source):
                    raise ValueError("La source ou la copie a changé pendant l'extraction.")
                manifest = {
                    "schema_version": 1, "owner": CACHE_OWNER, "complete": True,
                    "source_path": str(source), "archive_sha256": source_hash,
                    "archive_size": before[2], "archive_mtime_ns": before[3],
                    "archive_member": selected.archive_member, "member_crc32": info.CRC,
                    "member_sha256": member_hash,
                    "rom_filename": filename, "rom_size": size, "rom_sha256": rom_hash,
                    "game_id": selected.game_id, "game_code": selected.game_code,
                    "region": selected.region, "revision": selected.revision,
                }
                with (temporary / "manifest.json").open("x", encoding="utf-8") as writer:
                    json.dump(manifest, writer, ensure_ascii=False, indent=2, allow_nan=False)
                    writer.flush()
                    os.fsync(writer.fileno())
                local_path(target)
                if target.exists():
                    raise ValueError("Le dossier de cache a été créé par une autre opération ; aucun remplacement.")
                temporary.rename(target)
                temporary = None
            result = PreparedRom(target / filename, selected.game_id, selected.game_code, selected.region,
                                 selected.revision, source, selected.archive_member, source_hash, rom_hash,
                                 False, target / "manifest.json")
            if self.journal:
                self.journal("rom_extracted", source_path=str(source), path=str(result.path),
                             archive_sha256=source_hash, rom_sha256=rom_hash)
            return result
        finally:
            if temporary is not None:
                resolved = local_path(temporary)
                if resolved.is_relative_to(self.cache_root) and resolved.name.startswith(".partial-"):
                    shutil.rmtree(resolved)
            lock.unlink(missing_ok=True)

    def _reuse(self, directory: Path, selected: GameCandidate, archive_hash: str) -> PreparedRom:
        manifest_path = local_path(directory / "manifest.json")
        try:
            if not manifest_path.is_file() or manifest_path.stat().st_size > 65536:
                raise ValueError("Manifeste absent ou trop volumineux")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"),
                                  object_pairs_hook=_strict_pairs, parse_constant=_invalid_constant)
            fields = {"schema_version", "owner", "complete", "source_path", "archive_sha256", "archive_size",
                      "archive_mtime_ns", "archive_member", "member_crc32", "member_sha256", "rom_filename", "rom_size", "rom_sha256",
                      "game_id", "game_code", "region", "revision"}
            if not isinstance(manifest, dict) or set(manifest) != fields or \
                    manifest.get("owner") != CACHE_OWNER or type(manifest.get("schema_version")) is not int or \
                    manifest["schema_version"] != 1 or manifest.get("complete") is not True or \
                    manifest.get("archive_sha256") != archive_hash or manifest.get("archive_member") != selected.archive_member or \
                    manifest.get("member_sha256") != hashlib.sha256(selected.archive_member.encode("utf-8")).hexdigest() or \
                    manifest.get("rom_size") != selected.size or manifest.get("rom_filename") != _safe_member(selected.archive_member):
                raise ValueError("Manifeste incohérent")
            if any(type(manifest[key]) is not int or manifest[key] < 0
                   for key in ("archive_size", "archive_mtime_ns", "member_crc32", "rom_size", "revision")) or \
                    not isinstance(manifest["source_path"], str) or not manifest["source_path"] or \
                    not isinstance(manifest["rom_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", manifest["rom_sha256"]) or \
                    (manifest["game_id"], manifest["game_code"], manifest["region"], manifest["revision"]) != \
                    (selected.game_id, selected.game_code, selected.region, selected.revision):
                raise ValueError("Métadonnées du cache incohérentes")
            path = local_path(directory / manifest["rom_filename"])
            if not path.is_file() or path.stat().st_size != selected.size or file_hash(path) != manifest.get("rom_sha256"):
                raise ValueError("Contenu du cache altéré")
            actual = inspect_rom_source(path)[0]
            if (actual.game_id, actual.game_code, actual.region, actual.revision) != \
                    (selected.game_id, selected.game_code, selected.region, selected.revision):
                raise ValueError("Identité du cache incompatible")
            return PreparedRom(path, actual.game_id, actual.game_code, actual.region, actual.revision,
                               selected.source_path, selected.archive_member, archive_hash, manifest["rom_sha256"],
                               True, manifest_path)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
            raise ValueError("Cache existant incomplet ou altéré ; conservé sans écrasement. "
                             f"Vérifiez manuellement ce dossier avant de réessayer : {directory}") from exc
