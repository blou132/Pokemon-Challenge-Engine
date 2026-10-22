"""Explicit, additive migration; source files and existing adventures are never replaced."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import tomllib

from app.core.profile_manager import _read_json
from app.core.run_manager import RunManager
from app.models.challenge import Challenge
from app.models.profile import Profile, validate_profile_id
from app.services.discovery_safety import file_hash, file_signature, local_path
from app.services.emulator_settings_service import IniDocument
from app.services.run_isolation_service import PATHS, RunIsolationService


PREFERENCES = ("config.json", "game-mode.local.json", "controls.local.json", "randomizer.local.json")


@dataclass(frozen=True)
class ImportPlan:
    source: Path
    destination: Path
    runs: tuple[str, ...]
    profiles: tuple[str, ...]
    preferences: tuple[str, ...]
    skipped_preferences: tuple[str, ...]


def plan_import(source: Path, destination: Path) -> ImportPlan:
    source, destination = local_path(source), local_path(destination)
    if not source.is_dir() or source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError("Choisissez l'ancien dossier PCE, distinct du dossier de données actuel.")
    manager = RunManager(source / "runs")
    runs = tuple(run.run_id for run in manager.list_runs())
    if manager.warnings:
        raise ValueError("Une ancienne partie est illisible. Réparez-la avant l'import ; aucun fichier n'a été copié.")
    profile_root = local_path(source / "profiles")
    profile_ids = []
    for directory in sorted(profile_root.iterdir()) if profile_root.exists() else ():
        local_path(directory)
        if directory.name.startswith(".") or not directory.is_dir():
            continue
        validate_profile_id(directory.name)
        if (directory / ".transaction.json").exists():
            raise ValueError("Un modèle contient une sauvegarde interrompue. Ouvrez l'ancien PCE pour la terminer avant l'import.")
        data = _read_json(local_path(directory / "challenge.json"))
        if data.get("profile_id", directory.name) != directory.name:
            raise ValueError("Identité de modèle invalide.")
        challenge = Challenge.from_dict({key: value for key, value in data.items() if key not in {"profile_id", "profile_name"}})
        profile = Profile(directory.name, data.get("profile_name", directory.name), challenge,
                          _read_json(local_path(directory / "progress.json")), _read_json(local_path(directory / "history.json")))
        profile.validate()
        profile_ids.append(directory.name)
    profile_ids = tuple(profile_ids)
    for category, identifiers in (("runs", runs), ("profiles", profile_ids)):
        for identifier in identifiers:
            if local_path(destination / category / identifier).exists():
                raise ValueError("Une partie ou un modèle existe déjà dans la destination. Import annulé sans écrasement.")
    preferences, skipped = [], []
    for name in PREFERENCES:
        if local_path(source / name).is_file():
            (skipped if local_path(destination / name).exists() else preferences).append(name)
    if not (runs or profile_ids or preferences):
        raise ValueError("Aucune partie, aucun modèle ni préférence à importer dans ce dossier.")
    return ImportPlan(source, destination, runs, profile_ids, tuple(preferences), tuple(skipped))


def _copy(source: Path, destination: Path, signatures: dict) -> None:
    source = local_path(source)
    info = source.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("L'import refuse les liens, les jonctions et les fichiers partagés.")
    before = file_signature(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as reader, destination.open("xb") as writer:
        shutil.copyfileobj(reader, writer, 1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    digest = file_hash(destination)
    if before != file_signature(source) or digest != file_hash(source):
        raise ValueError("Les anciennes données ont changé. Fermez l'ancien PCE et ses émulateurs avant l'import.")
    signatures[source] = before


def _copy_tree(source: Path, destination: Path, signatures: dict) -> None:
    local_path(source)
    before = file_signature(source)
    destination.mkdir()
    for child in source.iterdir():
        local_path(child)
        if child.is_dir():
            _copy_tree(child, destination / child.name, signatures)
        else:
            _copy(child, destination / child.name, signatures)
    if file_signature(source) != before:
        raise ValueError("Un ancien dossier a changé pendant la copie ; import interrompu.")
    signatures[source] = before


def _stored_path(value: object) -> Path:
    """Read a historical path lexically, never probe the obsolete filesystem."""
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError("Un chemin de partie ancien est invalide ; import refusé.")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Un chemin de partie ancien est ambigu ; import refusé.")
    return path


def _relocate_run(staged: Path, destination: Path, identifier: str) -> None:
    manager = RunManager(staged / "runs")
    run = manager.load(identifier)
    options = run.launch_profile or {}
    kind = options.get("emulator_kind", "desmume")
    name = "play-melonds" if kind == "melonds" else "play"
    final_play = destination / "runs" / identifier / name
    staged_play = staged / "runs" / identifier / name
    if not staged_play.exists():
        return
    if kind not in {"desmume", "melonds"}:
        raise ValueError("Type d'environnement inconnu ; import refusé.")
    # A moved store keeps its absolute paths. Infer their old anchor only from
    # this run's recognised layout, then validate the actual staged files. Never
    # use old paths as read/copy sources, even when their former drive exists.
    original_play = _stored_path(options.get("rom_path")).parent.parent
    if original_play.parts[-3:] != ("runs", identifier, name):
        raise ValueError("L'ancien chemin ne correspond pas au dossier de cette partie ; import refusé.")
    service = RunIsolationService(manager)
    expected = service._paths(run)
    relative = {key: path.relative_to(staged_play) for key, path in expected.items()}
    if (any(_stored_path(options.get(key)) != original_play / path for key, path in relative.items())
            or _stored_path(run.save_path) != original_play / relative["save_path"]):
        raise ValueError("Les chemins de cette partie mélangent plusieurs espaces ; import refusé.")
    old_save = run.save_path
    # Temporarily rebase only the staged copy, so the existing ownership/hash/
    # identity validators inspect the copied bytes, not missing historical paths.
    run.launch_profile.update({key: str(path) for key, path in expected.items()})
    run.save_path = str(expected["save_path"])
    if kind == "melonds":
        _relocate_melonds_config(expected["ini_path"], original_play, staged_play)
    else:
        document = IniDocument(expected["ini_path"].read_bytes())
        for key, folder in PATHS.items():
            # Lua may point to a prior session, unlike the owned output folders.
            if key != "Lua" and _stored_path(document.get_text("PathSettings", key)) != original_play / folder:
                raise ValueError("La configuration DeSmuME mélange plusieurs espaces ; import refusé.")
            document.set_text("PathSettings", key, str(staged_play / folder))
        expected["ini_path"].write_bytes(document.to_bytes())
    if kind == "melonds":
        service.validate(run)
    else:
        # The temporary prefix must not shorten DeSmuME's supported destination
        # path length. Only the final location will ever launch the emulator.
        service._check_location(final_play)
        service._validate_files(run)
    if not expected["save_path"].exists() and not service.save_may_be_missing(run):
        raise ValueError("Une sauvegarde attendue manque dans le dossier déplacé ; import refusé.")
    # Provenance, inactive emulator environments and historical events stay
    # byte-for-byte unchanged. Only active destinations and backup lookup change.
    run.launch_profile.update({key: str(final_play / path) for key, path in relative.items()})
    run.save_path = str(final_play / relative["save_path"])
    if kind == "melonds":
        _relocate_melonds_config(expected["ini_path"], staged_play, final_play)
    else:
        for key, folder in PATHS.items():
            document.set_text("PathSettings", key, str(final_play / folder))
        expected["ini_path"].write_bytes(document.to_bytes())
    manager.save(run)
    backups = staged_play / "backups" / "pce-backups.json"
    if backups.exists() and old_save != run.save_path:
        data = json.loads(backups.read_text(encoding="utf-8"))
        old_key = hashlib.sha256(os.path.normcase(old_save).encode("utf-8")).hexdigest()
        new_key = hashlib.sha256(os.path.normcase(run.save_path).encode("utf-8")).hexdigest()
        for record in data.get("backups", []):
            if record.get("source_key") == old_key:
                record["source_key"] = new_key
        backups.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _relocate_melonds_config(path: Path, original: Path, destination: Path) -> None:
    """Change only owned output paths; retain all keyboard/rendering preferences."""
    from app.services.melonds_runtime import validate_config
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Configuration melonDS trop volumineuse.")
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    instance = config.get("Instance0", {})
    if (not isinstance(instance, dict)
            or _stored_path(instance.get("SaveFilePath")) != original / "saves"
            or _stored_path(instance.get("SavestatePath")) != original / "states"):
        raise ValueError("La configuration melonDS mélange plusieurs espaces ; import refusé.")
    values = {"SaveFilePath": str(destination / "saves"), "SavestatePath": str(destination / "states")}
    text = path.read_text(encoding="utf-8")
    section, seen, lines = None, set(), []
    for line in text.splitlines(keepends=True):
        heading = re.fullmatch(r"\s*\[([^\[\]]+)\]\s*(?:#.*)?", line.strip())
        if heading:
            section = heading[1]
        key = re.match(r"[ \t]*(SaveFilePath|SavestatePath)[ \t]*=", line) if section == "Instance0" else None
        if key:
            seen.add(key[1])
            line = key[0] + " " + json.dumps(values[key[1]], ensure_ascii=False) + "\n"
        lines.append(line)
    if seen != set(values):
        raise ValueError("La configuration melonDS ne permet pas un déplacement sûr des chemins.")
    config["Instance0"].update(values)
    rewritten = "".join(lines)
    if tomllib.loads(rewritten) != config:
        raise ValueError("Le déplacement modifierait d'autres réglages melonDS ; import refusé.")
    path.write_text(rewritten, encoding="utf-8")
    validate_config(path, destination)


def execute_import(plan: ImportPlan) -> dict:
    # Recheck the concrete preview after confirmation, including collisions.
    if plan_import(plan.source, plan.destination) != plan:
        raise ValueError("Les données ont changé depuis l'aperçu ; recommencez l'import.")
    plan.destination.mkdir(parents=True, exist_ok=True)
    signatures = {}
    with tempfile.TemporaryDirectory(prefix=".pce-import-", dir=plan.destination) as temporary:
        staging = Path(temporary)
        for category, identifiers in (("runs", plan.runs), ("profiles", plan.profiles)):
            (staging / category).mkdir()
            for identifier in identifiers:
                _copy_tree(plan.source / category / identifier, staging / category / identifier, signatures)
        for name in plan.preferences:
            _copy(plan.source / name, staging / name, signatures)
        for identifier in plan.runs:
            _relocate_run(staging, plan.destination, identifier)
        if any(file_signature(path) != before for path, before in signatures.items()):
            raise ValueError("Les anciennes données ont changé pendant l'import ; aucune partie publiée.")
        # Windows rename refuses an existing destination. Use the run lock so
        # another PCE instance cannot create a collision during publication.
        with RunManager(plan.destination / "runs")._writing():
            if plan_import(plan.source, plan.destination) != plan:
                raise ValueError("La destination a changé ; import annulé.")
            for category, identifiers in (("runs", plan.runs), ("profiles", plan.profiles)):
                parent = local_path(plan.destination / category)
                parent.mkdir(exist_ok=True)
                for identifier in identifiers:
                    (staging / category / identifier).rename(local_path(parent / identifier))
            for name in plan.preferences:
                # Exclusive copy also protects platforms where rename replaces.
                with (staging / name).open("rb") as reader, local_path(plan.destination / name).open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
    return {"runs": len(plan.runs), "profiles": len(plan.profiles),
            "preferences": len(plan.preferences), "skipped_preferences": list(plan.skipped_preferences)}
