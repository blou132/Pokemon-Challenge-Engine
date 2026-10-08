"""Bounded local setup, with automatic preparation of unambiguous installations.

No ROM/save downloads, no implicit INI changes, and no emulator or game input.
The Qt adapter runs these bounded filesystem/network operations in a worker.
"""

from dataclasses import asdict, is_dataclass
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading

from app.services.config_service import AppConfig
from app.services.game_mode_config import GameModeConfigStore
from app.services.installation_journal import InstallationJournal
from app.services.setup_state import SetupStateStore
from app.services.discovery_safety import local_path, file_signature

RESOURCE_DIR = Path(__file__).resolve().parents[2]
GAME_LABELS = {"black": "Pokémon Noir", "white": "Pokémon Blanc", "black2": "Pokémon Noir 2", "white2": "Pokémon Blanc 2"}


def plain(value):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def fingerprint(path: str | Path):
    file = local_path(path)
    before = file_signature(file)
    with file.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if before != file_signature(file):
        raise ValueError("Un fichier a changé pendant sa vérification ; recommencez.")
    after = file.stat()
    return {"size": after.st_size, "mtime_ns": after.st_mtime_ns, "sha256": digest}


class AutoSetupService:
    _locks = {}
    _locks_guard = threading.Lock()

    def __init__(self, base_dir: Path, legacy_config: AppConfig):
        self.base_dir = Path(base_dir).resolve()
        self.legacy = legacy_config
        self.cache_root = self.base_dir / "runtime" / "extracted-roms"
        self.download_root = self.base_dir / "runtime" / "downloads"
        self.journal = InstallationJournal(self.base_dir)
        self.store = SetupStateStore(self.base_dir)
        self._report = None
        self._automatic_report = None
        self._automatic_signature = None
        self._automatic_scope = None
        with self._locks_guard:
            self._lock = self._locks.setdefault(str(self.base_dir).casefold(), threading.RLock())

    @property
    def first_run_done(self):
        try:
            return self.store.load()["first_run_done"]
        except (ValueError, OSError):
            return False

    def complete_first_run(self):
        with self._lock:
            state = self.store.load()
            state["first_run_done"] = True
            self.store.save(state)

    def is_configured(self, game_id):
        try:
            return game_id in self.store.load()["games"]
        except (ValueError, OSError):
            return False

    def _preferences(self):
        store = GameModeConfigStore(self.base_dir, self.legacy)
        values = store.load()
        if store.warnings:
            raise ValueError("Les préférences Mode Jeu sont illisibles ; réparez-les avant une configuration automatique.")
        return store, values

    def apply_manual_config(self, previous: AppConfig, current: AppConfig):
        """Apply only explicitly edited legacy paths to the per-game launch choices."""
        with self._lock:
            self.store.load()  # Keep corrupt provenance and preferences untouched.
            store = GameModeConfigStore(self.base_dir, previous)
            preferences = store.load()
            if store.warnings:
                raise ValueError("Les préférences Mode Jeu sont illisibles ; les choix existants sont conservés.")
            changed = False
            for game, options in preferences["launch_profiles"].items():
                if previous.desmume_path != current.desmume_path:
                    options["emulator_path"] = current.desmume_path
                    changed = True
                if previous.rom_paths.get(game, "") != current.rom_paths.get(game, ""):
                    options["rom_path"] = current.rom_paths.get(game, "")
                    changed = True
            if changed:
                store.save(preferences)
            self.legacy = current
            self._automatic_signature = None

    @staticmethod
    def _supported(candidate):
        profiles = json.loads((RESOURCE_DIR / "data/memory_profiles.json").read_text(encoding="utf-8"))
        return any(item["game_id"] == candidate["game_id"] and item["game_code"] == candidate["game_code"]
                   and item["revision"] == candidate["revision"] and item["region"] == candidate["region"]
                   for item in profiles)

    def scan(self, retrobat_path="", emulator_path="", rom_path="", *, game_id=None):
        from app.services.retrobat_discovery_service import RetroBatDiscoveryService
        from app.services.game_discovery_service import GameDiscoveryService
        from app.services.save_discovery_service import SaveDiscoveryService
        from app.services.desmume_discovery_service import DeSmuMEDiscoveryService
        with self._lock:
            warnings = []
            try:
                state = self.store.load()
            except (OSError, ValueError) as exc:
                state = {"retrobat_root": "", "games": {}, "first_run_done": False}
                warnings.append(str(exc))
            _, preferences = self._preferences()
            options = preferences["launch_profiles"]
            discovery = RetroBatDiscoveryService()
            hints = [value for value in (retrobat_path, state["retrobat_root"], self.legacy.retrobat_path) if value]
            for item in options.values():
                if item["emulator_path"]:
                    hints.append(str(Path(item["emulator_path"]).parent.parent.parent))
                if item["rom_path"]:
                    hints.append(item["rom_path"])
            installations = discovery.discover(hints)
            warnings.extend(discovery.warnings)
            if retrobat_path:
                installations = tuple(item for item in installations if Path(item.root).resolve() == Path(retrobat_path).resolve())
            emulator_finder = DeSmuMEDiscoveryService()
            configured = list(dict.fromkeys(value for value in [emulator_path, self.legacy.desmume_path,
                *(item["emulator_path"] for item in options.values())] if value))
            emulators = emulator_finder.discover([Path(item.emulators_directory) / "desmume" for item in installations],
                                                 configured_paths=configured)
            warnings.extend(getattr(emulator_finder, "warnings", []))
            emulator_values = plain(emulators)
            for value in emulator_values:
                value["replacement_required"] = any(item["status"] not in {"verified", "missing"} for item in value["dlls"])
            chosen_exe = emulator_path or (emulator_values[0]["path"] if len(emulator_values) == 1 else "")
            root = retrobat_path or (str(installations[0].root) if len(installations) == 1 else "")
            games = GameDiscoveryService(self.cache_root)
            # Cache paths are omitted: source provenance is the authoritative discovery entry.
            explicit = [rom_path, *self.legacy.rom_paths.values(),
                        *(item["source_path"] for item in state["games"].values())]
            explicit.extend(item["rom_path"] for item in options.values()
                            if item["rom_path"] and not Path(item["rom_path"]).resolve().is_relative_to(self.cache_root))
            directories = [Path(item.roms_directory) / "nds" for item in installations]
            directories.extend(Path(item).parent for item in explicit if item)
            candidates = games.discover(list(dict.fromkeys(directories)),
                                         explicit_paths=[item for item in explicit if item])
            warnings.extend(games.warnings)
            game_values = []
            for candidate in candidates:
                value = plain(candidate)
                value["id"] = candidate.candidate_id
                value["label"] = GAME_LABELS.get(value["game_id"], value["game_id"]) + f" · {value['region']} · rev{value['revision']}"
                value["supported"] = self._supported(value)
                saves = SaveDiscoveryService()
                found = saves.discover(candidate, retrobat_root=root or None, emulator_path=chosen_exe or None,
                    configured_directories=[self.legacy.save_path] if self.legacy.save_path else (),
                    configured_save=options[value["game_id"]]["save_path"] or None) if game_id in (None, candidate.game_id) else ()
                proposed = saves.proposed(found)
                value["saves"] = plain(found)
                value["proposed_save"] = str(proposed.path) if proposed else ""
                value["save_warnings"] = list(saves.warnings)
                value["state_slots_directory"] = str(saves.state_slots_directory or "")
                warnings.extend(getattr(saves, "warnings", []))
                game_values.append(value)
            result = {"installations": plain(installations), "emulators": emulator_values,
                      "games": game_values, "warnings": list(dict.fromkeys(warnings)),
                      "details": [], "setup_complete": state["first_run_done"]}
            # Local trace only. Scans never modify RetroBat, its INI, ROMs or saves.
            for event, rows in (("retrobat_detected", result["installations"]), ("emulator_detected", emulator_values)):
                for row in rows:
                    self.journal(event, candidate=row)
            for row in game_values:
                self.journal("rom_archive_detected" if row["source_kind"] == "zip" else "rom_detected",
                             source=row["source_path"], member=row["archive_member"], game_id=row["game_id"])
                for save in row["saves"]:
                    self.journal("save_detected", game_id=row["game_id"], **save)
            result["details"] = self.journal.recent()
            self._report = result
            return result

    def _automatic_fingerprint(self, report, state, preferences):
        """Stat known files and bounded discovery roots; never hash ROMs in this fast path."""
        from app.services.retrobat_discovery_service import RetroBatDiscoveryService
        paths = {self.store.path, self.base_dir / "game-mode.local.json"}
        roots = [Path(drive) / "RetroBat" for drive in RetroBatDiscoveryService._drives()]
        roots.extend(Path(item) for item in (state["retrobat_root"], self.legacy.retrobat_path) if item)
        roots.extend(Path(item["root"]) for item in (report or {}).get("installations", ()))
        for root in roots:
            paths.update((root, root / "roms/nds", root / "emulators/desmume", root / "saves/nds",
                          root / "saves/nds/DeSmuME"))
        for options in preferences["launch_profiles"].values():
            for key in ("rom_path", "emulator_path", "ini_path", "save_path"):
                if options[key]:
                    path = Path(options[key])
                    paths.update((path, path.parent))
        for record in state["games"].values():
            for key in ("source_path", "prepared_path"):
                path = Path(record[key])
                paths.update((path, path.parent, path.parent / "manifest.json"))
        for emulator in (report or {}).get("emulators", ()):
            path = Path(emulator["path"])
            paths.update((path, path.parent, path.parent / "desmume.ini",
                          path.parent / "lua51.dll", path.parent / "lua5.1.dll"))
            from app.services.save_discovery_service import SaveDiscoveryService
            try:
                battery, _ = SaveDiscoveryService._ini_paths(path)
                if battery:
                    paths.add(battery)
            except (ValueError, OSError):
                pass  # Its signature/error is checked again by the full health report.
        for candidate in (report or {}).get("games", ()):
            path = Path(candidate["source_path"])
            paths.update((path, path.parent))
            paths.update(Path(item["path"]) for item in candidate["saves"])
        if self.legacy.save_path:
            paths.add(Path(self.legacy.save_path))
        values = []
        for path in sorted(paths, key=str):
            try:
                signature = file_signature(local_path(path))
            except (OSError, ValueError):
                signature = None
            values.append((str(path), signature))
        return (self.legacy.retrobat_path, self.legacy.desmume_path,
                tuple(sorted(self.legacy.rom_paths.items())), self.legacy.save_path, tuple(values))

    @staticmethod
    def _same_path(first, second):
        return bool(first and second and Path(first).resolve() == Path(second).resolve())

    def _automatic_candidate(self, game_id, candidates, options, record):
        """Existing valid choices take precedence over a new unique discovery."""
        path = options["rom_path"]
        chosen = [item for item in candidates if self._same_path(path, item["source_path"])]
        if record and self._same_path(path, record["prepared_path"]):
            chosen = [item for item in candidates if self._same_path(record["source_path"], item["source_path"])
                      and item["archive_member"] == record["archive_member"]]
        if len(chosen) == 1 and (not chosen[0]["requires_choice"] or record
                                and self._same_path(chosen[0]["source_path"], record["source_path"])
                                and chosen[0]["archive_member"] == record["archive_member"]):
            return chosen[0], ""
        if chosen:
            return None, "Plusieurs jeux sont présents dans cette archive. Choisissez celui à préparer."
        # A present manual file with another identity must never be silently replaced.
        if path and Path(path).is_file() and not (record and self._same_path(path, record["prepared_path"])):
            return None, "Le jeu choisi manuellement ne correspond pas à cette version. Vérifiez ce choix."
        if record:
            previous = next((item for item in candidates if self._same_path(item["source_path"], record["source_path"])
                             and item["archive_member"] == record["archive_member"]), None)
            if previous:
                return previous, ""
        supported = [item for item in candidates if item["supported"]]
        if len(supported) != 1 or supported[0]["requires_choice"]:
            return None, "Plusieurs copies du jeu ont été trouvées. Choisissez celle à utiliser." if supported else ""
        candidate = supported[0]
        if record and not Path(record["source_path"]).is_file():
            previous = record["fingerprints"].get(record["source_path"])
            if previous and fingerprint(candidate["source_path"])["sha256"] != previous["sha256"]:
                return None, "Le jeu a été déplacé et la copie trouvée est différente. Confirmez celle à utiliser."
        return candidate, ""

    def _automatic_saves(self, candidate, emulator, options, root, record=None):
        from app.services.discovery_models import GameCandidate
        from app.services.save_discovery_service import SaveDiscoveryService
        fields = {key: candidate[key] for key in GameCandidate.__dataclass_fields__}
        fields["source_path"] = Path(fields["source_path"])
        finder = SaveDiscoveryService()
        saves = finder.discover(GameCandidate(**fields), retrobat_root=root or None,
            emulator_path=emulator["path"], configured_directories=[self.legacy.save_path] if self.legacy.save_path else (),
            configured_save=options["save_path"] or None)
        proposed = finder.proposed(saves)
        candidate.update(saves=plain(saves), proposed_save=str(proposed.path) if proposed else "",
                         state_slots_directory=str(finder.state_slots_directory or ""), save_warnings=list(finder.warnings))
        # In an existing configuration, the current empty association is a saved
        # choice (including an explicit clearing of a previously associated save).
        # Keep offering discovered candidates without silently binding them.
        if record is not None and not options["save_path"]:
            return "", ""
        explicit = next((item for item in saves if self._same_path(item.path, options["save_path"])
                         and item.compatible), None)
        if explicit:
            return str(explicit.path), ""
        if proposed:
            return str(proposed.path), ""
        if saves:
            return None, "Plusieurs sauvegardes ou une association à confirmer : choisissez la sauvegarde à utiliser."
        if options["save_path"]:
            return None, "La sauvegarde associée n'a pas été retrouvée. Choisissez son nouvel emplacement."
        if finder.warnings:
            return None, "La recherche de sauvegardes est incomplète. Vérifiez les emplacements dans le diagnostic."
        return "", ""

    def automatic_setup(self, force=False, game_id=None):
        """Prepare unique local choices without downloads or external modifications.

        Missing games are independent states, not global installation failures. The
        cached report is reused only while files, configuration and discovery roots
        keep their signatures. Explicit rescans and changes run the bounded readers.
        """
        if game_id is not None and game_id not in GAME_LABELS:
            raise ValueError("Jeu de lancement inconnu.")
        with self._lock:
            state = self.store.load()  # Refuse corrupt state before any local mutation.
            _, preferences = self._preferences()
            if (not force and self._automatic_report is not None and self._automatic_scope in (None, game_id)
                    and self._automatic_signature == self._automatic_fingerprint(self._automatic_report, state, preferences)):
                return deepcopy(self._automatic_report) | {"cached": True, "prepared_games": []}
            result = self.scan(game_id=game_id) if game_id is not None else self.scan()
            result.update(game_states={}, ready=False, prepared_games=[], cached=False)
            for current, label in GAME_LABELS.items():
                entry = {"status": "not_found", "message": f"{label} n'a pas été trouvé. Ajoutez le jeu à votre bibliothèque RetroBat.",
                         "candidate_id": "", "emulator_path": "", "save_path": ""}
                result["game_states"][current] = entry
                candidates = [item for item in result["games"] if item["game_id"] == current]
                if not candidates:
                    continue
                if game_id is not None and current != game_id:
                    entry.update(status="needs_attention", message="Jeu trouvé. Sa préparation sera vérifiée au lancement.")
                    continue
                options = preferences["launch_profiles"][current]
                record = state["games"].get(current)
                try:
                    candidate, issue = self._automatic_candidate(current, candidates, options, record)
                    if candidate is None:
                        entry.update(status="needs_choice" if issue else "needs_attention",
                            message=issue or "Jeu trouvé, mais cette région ou révision n'est pas encore prise en charge.")
                        continue
                    entry["candidate_id"] = candidate["id"]
                    if not candidate["supported"]:
                        entry.update(status="needs_attention", message="La région ou révision du jeu choisi n'est pas encore prise en charge.")
                        continue
                    emulators = [item for item in result["emulators"] if item["architecture"]]
                    emulator = next((item for item in emulators if self._same_path(item["path"], options["emulator_path"])), None)
                    if emulator is None and record:
                        emulator = next((item for item in emulators if self._same_path(item["path"], record["emulator_path"])), None)
                    if emulator is None and len(emulators) == 1:
                        emulator = emulators[0]
                    if emulator is None:
                        entry.update(status="needs_choice" if emulators else "needs_attention",
                            message="Plusieurs installations DeSmuME ont été trouvées. Choisissez celle à utiliser." if emulators
                                    else "DeSmuME n'a pas été trouvé. Ajoutez votre installation ou choisissez-la manuellement.")
                        continue
                    entry["emulator_path"] = emulator["path"]
                    root = next((item["root"] for item in result["installations"]
                                 if Path(candidate["source_path"]).is_relative_to(Path(item["roms_directory"]))), "")
                    save, issue = self._automatic_saves(candidate, emulator, options, root, record)
                    if issue:
                        entry.update(status="needs_choice", message=issue)
                        continue
                    entry["save_path"] = save
                    before = deepcopy(options)
                    prepared = self.prepare({"candidate_id": candidate["id"], "emulator_path": emulator["path"],
                        "retrobat_root": root, "save_path": save}, install_lua=False, preserve_manual_ini=True)
                    health = prepared["health"]
                    if before != prepared["profile"] or record is None or record["source_path"] != candidate["source_path"]:
                        result["prepared_games"].append(current)
                    entry["health"] = health
                    entry["profile"] = prepared["profile"]
                    entry["save_message"] = ("Sauvegarde trouvée." if save else
                        "Aucune sauvegarde associée. Les sauvegardes trouvées restent disponibles dans le diagnostic." if candidate["saves"] else
                        "Aucune sauvegarde existante trouvée. Une nouvelle partie reste possible.")
                    if health["ready"]:
                        entry.update(status="ready", message="Prêt")
                    elif health["launch_ready"]:
                        entry.update(status="lua_required", message="Support Lua requis. Installez-le automatiquement depuis le diagnostic.")
                    else:
                        entry.update(status="needs_attention", message=" ".join(health["issues"]))
                except (ValueError, OSError) as exc:
                    entry.update(status="needs_attention", message=str(exc))
            result["ready"] = any(item["status"] == "ready" for item in result["game_states"].values())
            _, latest_preferences = self._preferences()
            self._automatic_signature = self._automatic_fingerprint(result, self.store.load(), latest_preferences)
            self._automatic_scope = game_id
            self._automatic_report = deepcopy(result)
            return result

    def _selection(self, selection):
        report = self._report
        if report is None:
            report = self.scan(selection.get("retrobat_root", ""), selection.get("emulator_path", ""))
        candidate = next((row for row in report["games"] if row["id"] == selection.get("candidate_id")), None)
        if candidate is None:
            raise ValueError("Choisissez un jeu détecté ; relancez le diagnostic si sa source a changé.")
        if not candidate["supported"]:
            raise ValueError("Aucun profil mémoire compatible avec ce jeu, cette région et cette révision.")
        executable = selection.get("emulator_path", "")
        emulator = next((row for row in report["emulators"] if row["path"] == executable), None)
        if emulator is None:
            raise ValueError("Choisissez un émulateur détecté.")
        save = selection.get("save_path")
        if save is None:
            save = candidate["proposed_save"]
            if not save and candidate["saves"]:
                raise ValueError("Plusieurs sauvegardes possibles : choisissez un fichier ou explicitement aucune sauvegarde.")
        if save and save not in {row["path"] for row in candidate["saves"]}:
            raise ValueError("La sauvegarde choisie ne correspond pas aux candidats détectés.")
        if save and not next(row for row in candidate["saves"] if row["path"] == save).get("compatible", True):
            raise ValueError("Ce format nécessite un import manuel dans DeSmuME ; aucune conversion automatique effectuée.")
        return candidate, emulator, save

    def prepare(self, selection, *, install_lua=False, replace_confirmed=False, preserve_manual_ini=False):
        from app.services.rom_preparation_service import RomPreparationService
        from app.services.lua_runtime_installer import LuaRuntimeInstaller
        with self._lock:
            candidate, emulator, save = self._selection(selection)
            # Refuse corrupt/concurrently edited local state before creating
            # caches or changing an explicitly selected external installation.
            state = self.store.load()
            preferences_store, preferences = self._preferences()
            self.journal("configuration_requested", game_id=candidate["game_id"], source=candidate["source_path"],
                         emulator=emulator["path"], install_lua=install_lua, replace_confirmed=replace_confirmed)
            prepared = RomPreparationService(self.cache_root).prepare(candidate["source_path"],
                member=candidate["archive_member"], expected_game=candidate["game_id"])
            actions = []
            if candidate["source_kind"] == "zip":
                self.journal("rom_extracted", **plain(prepared))
                actions.append("ROM préparée dans le cache local ; archive originale conservée.")
            if install_lua:
                installed = LuaRuntimeInstaller(self.download_root, journal=self.journal).install(
                    emulator["path"], allow_replace=replace_confirmed)
                actions.append("Support Lua vérifié sur disque." if not installed.changed else "Support Lua installé et vérifié sur disque.")
            game_id = candidate["game_id"]
            profile = preferences["launch_profiles"][game_id]
            ini_path = emulator.get("ini_path") or ""
            if preserve_manual_ini and profile["ini_path"]:
                from app.services.emulator_settings_service import IniDocument
                chosen_ini = local_path(profile["ini_path"])
                if chosen_ini.is_file() and chosen_ini.stat().st_size <= 1024 * 1024:
                    IniDocument(chosen_ini.read_bytes()).require_windows_profile_encoding()
                    ini_path = profile["ini_path"]
            profile.update(rom_path=str(prepared.path), emulator_path=emulator["path"],
                           ini_path=ini_path, save_path=save or "")
            if candidate.get("state_slots_directory"):
                profile.update(save_state_directory=candidate["state_slots_directory"], save_state_stem=prepared.path.stem)
            # Existing challenge, settings, backup policies and controls remain intact.
            record = {"source_path": candidate["source_path"], "archive_member": candidate["archive_member"],
                      "prepared_path": str(prepared.path), "emulator_path": emulator["path"],
                      "save_path": save or "", "fingerprints": {}}
            record["fingerprints"] = self._fingerprints(profile, record)
            preferences_store.save(preferences)
            state["games"][game_id] = record
            state["retrobat_root"] = selection.get("retrobat_root", "")
            self.store.save(state)
            health = self.health_check(game_id)
            self.journal("configuration_ready" if health["ready"] else "configuration_incomplete",
                         game_id=game_id, issues=health["issues"], actions=actions)
            return {"game_id": game_id, "profile": profile, "health": health, "actions": actions}

    def repair(self, selection, replace_confirmed=False):
        return self.prepare(selection, install_lua=True, replace_confirmed=replace_confirmed)

    @staticmethod
    def _fingerprints(profile, record):
        exe = Path(profile["emulator_path"])
        paths = [exe, exe.parent / "lua51.dll", exe.parent / "lua5.1.dll", exe.parent / "desmume.ini",
                 Path(record["source_path"])]
        return {str(path): fingerprint(path) if path.is_file() else None for path in paths}

    def health_check(self, game_id, require_lua=True, *, options_override=None):
        from app.services.game_discovery_service import GameDiscoveryService
        from app.services.desmume_discovery_service import DeSmuMEDiscoveryService
        from app.services.lua_runtime_installer import LuaRuntimeInstaller
        from app.services.emulator_settings_service import IniDocument
        from app.services.save_manager_service import SaveManagerService
        issues, warnings = [], []
        with self._lock:
            _, preferences = self._preferences()
            if game_id not in preferences["launch_profiles"]:
                raise ValueError("Jeu de lancement inconnu.")
            options = preferences["launch_profiles"][game_id] if options_override is None else options_override
            # A persistent run owns its launch snapshot; later global setup changes
            # must not redirect that run to another ROM or save.
            record = self.store.load()["games"].get(game_id) if options_override is None else None
            changed = False
            if record:
                try:
                    changed = self._fingerprints(options, record) != record["fingerprints"]
                except (ValueError, OSError):
                    changed = True
                if changed:
                    warnings.append("Configuration modifiée depuis le dernier lancement. Relancez le diagnostic si nécessaire.")
            try:
                games = GameDiscoveryService().inspect(options["rom_path"])
                if len(games) != 1 or games[0].game_id != game_id or not self._supported(plain(games[0])):
                    issues.append("Le jeu préparé ne correspond pas au profil mémoire attendu.")
            except (ValueError, OSError) as exc:
                issues.append("ROM non prête : " + str(exc))
            found = DeSmuMEDiscoveryService().discover([], configured_paths=[options["emulator_path"]])
            if len(found) != 1 or not found[0].architecture:
                issues.append("DeSmuME absent, non identifié ou architecture inconnue. Lancez Diagnostic / Installation.")
            ini = Path(options["emulator_path"]).parent / "desmume.ini"
            try:
                ini = local_path(ini)
                if ini.stat().st_size > 1024 * 1024:
                    raise ValueError("Configuration trop volumineuse.")
                raw = ini.read_bytes()
                if raw.startswith((b"\xef\xbb\xbf", b"\xfe\xff")):
                    raise ValueError("Encodage INI non pris en charge par ce build.")
                IniDocument(raw)
            except (OSError, ValueError):
                issues.append("Configuration DeSmuME absente ou illisible. Ouvrez puis fermez DeSmuME une fois et relancez le diagnostic.")
            lua = plain(LuaRuntimeInstaller(self.download_root).diagnose(options["emulator_path"]))
            lua_issue = require_lua and lua.get("status") not in {"ready", "verified", "installed"}
            if lua_issue:
                issues.append("Support Lua à réparer avant de jouer avec la connexion PCE.")
            if options["save_path"]:
                try:
                    info = SaveManagerService.inspect_save(options["save_path"], game_id)
                    if not info.exists:
                        issues.append("La sauvegarde sélectionnée a été déplacée ou supprimée.")
                    else:
                        from app.services.save_discovery_service import SaveDiscoveryService
                        expected = SaveDiscoveryService.expected_save_path(options["emulator_path"], options["rom_path"])
                        if expected is None or local_path(options["save_path"]) != local_path(expected):
                            issues.append("La sauvegarde choisie n'est pas celle que DeSmuME chargera pour cette ROM. "
                                          "Vérifiez son dossier Battery et son nom dans DeSmuME, puis relancez le diagnostic. "
                                          "Aucune sauvegarde n'a été déplacée ou importée automatiquement.")
                except (ValueError, OSError) as exc:
                    issues.append("Sauvegarde à vérifier : " + str(exc))
            if options["challenge_profile_id"]:
                from app.core.profile_manager import ProfileManager
                try:
                    profile = ProfileManager(self.base_dir / "profiles").load(options["challenge_profile_id"])
                    if profile.challenge.game_id != game_id:
                        issues.append("Le challenge est associé à un autre jeu.")
                except (OSError, ValueError):
                    issues.append("Le profil de challenge sélectionné n'est plus disponible.")
            warnings.append("La présence vérifiée du support Lua ne prouve pas encore la connexion : elle sera confirmée par les messages du jeu.")
            return {"ready": not issues, "launch_ready": len(issues) == int(lua_issue),
                    "issues": issues, "warnings": warnings, "changed": changed, "lua_status": lua}

    def prepare_play(self, game_id):
        from app.services.rom_preparation_service import RomPreparationService
        with self._lock:
            record = self.store.load()["games"].get(game_id)
            if not record:
                raise ValueError("Préparez ce jeu dans Diagnostic / Installation avant de jouer.")
            store, preferences = self._preferences()
            profile = preferences["launch_profiles"][game_id]
            if profile["rom_path"] != record["prepared_path"] or profile["emulator_path"] != record["emulator_path"]:
                raise ValueError("Profil modifié depuis la préparation. Lancez Diagnostic / Installation pour vérifier ces chemins.")
            prepared = RomPreparationService(self.cache_root).prepare(record["source_path"],
                member=record["archive_member"], expected_game=game_id)
            if str(prepared.path) != profile["rom_path"]:
                profile["rom_path"] = str(prepared.path)
                store.save(preferences)
                record["prepared_path"] = str(prepared.path)
                state = self.store.load()
                state["games"][game_id] = record
                self.store.save(state)
                self.journal("rom_extracted", **plain(prepared))
            health = self.health_check(game_id)
            if health["ready"]:
                state = self.store.load()
                state["games"][game_id]["fingerprints"] = self._fingerprints(profile, record)
                self.store.save(state)
            self.journal("launch_checked", game_id=game_id, ready=health["ready"], issues=health["issues"])
            return {"game_id": game_id, "profile": profile, "health": health, "actions": []}

    def storage_summary(self):
        from app.services.local_storage_service import LocalStorageService
        return LocalStorageService(self.base_dir).summary()

    def cleanup(self, kind, confirmed=False, active_session=""):
        from app.services.local_storage_service import LocalStorageService
        from app.services.emulator_window_manager import EmulatorWindowManager
        if kind == "extracted_roms":
            _, preferences = self._preferences()
            windows = EmulatorWindowManager()
            for path in {item["emulator_path"] for item in preferences["launch_profiles"].values() if item["emulator_path"]}:
                if windows.running_executable(path):
                    raise ValueError("Fermez DeSmuME avant de nettoyer les ROM extraites.")
        return LocalStorageService(self.base_dir, journal=self.journal).cleanup(kind, confirmed=confirmed, active_session=active_session)
