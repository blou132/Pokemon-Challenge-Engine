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
from app.services.run_isolation_service import PATHS


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


def _relocate_run(staged: Path, source: Path, destination: Path, identifier: str) -> None:
    manager = RunManager(staged / "runs")
    run = manager.load(identifier)
    kind = (run.launch_profile or {}).get("emulator_kind", "desmume")
    name = "play-melonds" if kind == "melonds" else "play"
    original_play = source / "runs" / identifier / name
    final_play = destination / "runs" / identifier / name
    staged_play = staged / "runs" / identifier / name
    if not staged_play.exists():
        return
    # Limit relocation to a recognised owned environment. Do not rewrite
    # provenance, transformation manifests, historic events, or external paths.
    marker = staged_play / "isolation.json"
    metadata = json.loads(marker.read_text(encoding="utf-8"))
    if metadata.get("owner") != "pokemon-challenge-engine-run" or metadata.get("run_id") != identifier:
        raise ValueError("Un environnement de partie ancien n'est pas reconnu ; import refusé.")
    old_save = run.save_path
    def relocated(value):
        if not isinstance(value, str) or not Path(value).is_absolute():
            return value
        path = local_path(value)
        return str(final_play / path.relative_to(original_play)) if path.is_relative_to(original_play) else value
    run.save_path = relocated(run.save_path)
    if run.launch_profile:
        for key in ("rom_path", "emulator_path", "ini_path", "save_path", "save_state_directory", "backup_directory"):
            if key in run.launch_profile:
                run.launch_profile[key] = relocated(run.launch_profile[key])
    manager.save(run)
    if kind == "melonds":
        _relocate_melonds_config(staged_play / "emulator/portable/melonDS.toml", original_play, final_play)
    ini_path = staged_play / "emulator" / "desmume.ini"
    if ini_path.exists():
        document = IniDocument(ini_path.read_bytes())
        for key, folder in PATHS.items():
            document.set_text("PathSettings", key, str(final_play / folder))
        ini_path.write_bytes(document.to_bytes())
    backups = staged_play / "backups" / "pce-backups.json"
    if backups.exists() and old_save and old_save != run.save_path:
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
    config = validate_config(path, original)
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
            _relocate_run(staging, plan.source, plan.destination, identifier)
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
