"""Frontend sessions: launch, requested settings, owned process and opt-in backups."""

from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic

from app.core.profile_manager import ProfileManager
from app.services.config_service import AppConfig
from app.services.emulator_window_manager import EmulatorWindowManager
from app.services.game_mode_config import GAME_IDS, SPEEDS, GameModeConfigStore
from app.services.launcher_service import LauncherService


@dataclass(frozen=True)
class RunState:
    game_id: str | None = None
    profile_id: str | None = None
    running: bool = False
    elapsed_seconds: int = 0
    requested_speed: str = "x1"
    confirmed_speed: str | None = None
    message: str = "DeSmuME reste dans une fenêtre séparée."
    window_title: str | None = None
    pid: int | None = None


class GameModeService:
    def __init__(self, base_dir: Path, legacy_config: AppConfig, *, clock=monotonic,
                 launcher_factory=LauncherService, window_manager=None):
        self.base_dir = Path(base_dir).resolve()
        self.legacy_config = legacy_config
        self.store = GameModeConfigStore(self.base_dir, legacy_config)
        self.config = self.store.load()
        self.profiles = ProfileManager(self.base_dir / "profiles")
        self.windows = window_manager if window_manager is not None else EmulatorWindowManager()
        self._clock = clock
        self._launcher_factory = launcher_factory
        self.process = None
        self._started = None
        self._last_periodic = None
        self._run_options = None
        self.state = RunState(message="\n".join(self.store.warnings) or RunState().message)

    def save_launch_profile(self, game_id: str, updates: dict) -> dict:
        if game_id not in GAME_IDS or not isinstance(updates, dict):
            raise ValueError("Profil de lancement inconnu.")
        candidate = deepcopy(self.config)
        candidate["launch_profiles"][game_id].update(updates)
        self.config = self.store.save(candidate)
        return deepcopy(self.config["launch_profiles"][game_id])

    def save_interface(self, updates: dict) -> dict:
        candidate = deepcopy(self.config)
        for key, value in updates.items():
            if key in {"visible", "sides"} and isinstance(value, dict):
                candidate["interface"][key].update(value)
            else:
                candidate["interface"][key] = value
        self.config = self.store.save(candidate)
        return deepcopy(self.config["interface"])

    def save_shortcuts(self, values: dict) -> dict:
        candidate = deepcopy(self.config)
        candidate["shortcuts"].update(values)
        self.config = self.store.save(candidate)
        return deepcopy(self.config["shortcuts"])

    def _backup(self, options: dict, reason: str):
        from app.services.save_manager_service import SaveManagerService
        if not options["save_path"]:
            raise ValueError("Choisissez explicitement une sauvegarde normale avant de créer un backup.")
        if not options["backup_directory"].strip():
            raise ValueError("Choisissez un dossier de backups.")
        return SaveManagerService(Path(options["backup_directory"])).backup(
            Path(options["save_path"]), options["game_id"], retention=options["backup_retention"], reason=reason)

    def backup_now(self, game_id: str | None = None):
        selected = game_id or self.state.game_id
        if selected not in GAME_IDS:
            raise ValueError("Choisissez le jeu à sauvegarder.")
        options = self._run_options if self.state.running and selected == self.state.game_id else self.config["launch_profiles"][selected]
        return self._backup(options, "manual")

    def _apply_launch_settings(self, options: dict) -> None:
        """Configured only by explicit opt-in; exports preserve an INI backup."""
        from app.services.emulator_settings_service import EmulatorSettingsService
        service = EmulatorSettingsService(Path(options["emulator_path"]),
                                          running_probe=lambda: self.windows.running_executable(options["emulator_path"]))
        # The settings adapter supplies the verified preset and profile exports.
        service.apply_launch_profile(options, self.base_dir)

    def launch(self, game_id: str, profile_id: str | None = None):
        if game_id not in GAME_IDS:
            raise ValueError("Jeu de lancement inconnu.")
        if self.process is not None and self.process.poll() is None:
            raise ValueError("Une session DeSmuME est déjà suivie ; fermez-la avant un autre lancement.")
        # A caller can relaunch between process exit and the next UI timer tick.
        # Finalise the old session (including its own close backup) first.
        if self.process is not None and self.state.running:
            self.tick()
        options = deepcopy(self.config["launch_profiles"][game_id])
        profile_id = profile_id or options["challenge_profile_id"]
        if profile_id is not None:
            profile = self.profiles.load(profile_id)
            if profile.challenge.game_id != game_id:
                raise ValueError("Le profil challenge et le jeu de lancement sont incompatibles.")
        if self.windows.running_executable(options["emulator_path"]):
            raise ValueError("Cet exécutable DeSmuME est déjà en cours ; aucun second lancement effectué.")
        config = AppConfig(self.legacy_config.retrobat_path, options["emulator_path"],
                           {game_id: options["rom_path"]}, self.legacy_config.save_path)
        launcher = self._launcher_factory(config)
        errors = launcher.validate(game_id)
        if errors:
            raise ValueError("\n".join(errors))
        if options["backup_on_launch"]:
            self._backup(options, "launch")
        if options["apply_settings"]:
            self._apply_launch_settings(options)
        process = launcher.launch(game_id)
        self.process = process
        self._started = self._last_periodic = self._clock()
        self._run_options = options
        self.state = RunState(game_id=game_id, profile_id=profile_id, running=True,
                              requested_speed=options["speed"], pid=process.pid,
                              message="DeSmuME démarré. Vitesse demandée ; état réel non confirmé.")
        return process

    def request_speed(self, value: str) -> RunState:
        if value not in SPEEDS:
            raise ValueError("Vitesse inconnue.")
        self.state = replace(self.state, requested_speed=value, confirmed_speed=None,
                             message="État demandé : " + value + ". Utilisez les raccourcis DeSmuME vérifiés ; état réel non confirmé.")
        return self.state

    def tick(self) -> RunState:
        if self.process is None or not self.state.running:
            return self.state
        now = self._clock()
        elapsed = max(0, int(now - self._started))
        options = self._run_options
        code = self.process.poll()
        message = self.state.message
        if code is not None:
            message = "DeSmuME fermé." if code == 0 else f"DeSmuME arrêté (code {code})."
            if options["backup_on_close"]:
                try:
                    self._backup(options, "close")
                    message += " Backup de fermeture créé."
                except (OSError, ValueError) as exc:
                    message += " Backup non créé : " + str(exc)
            self.state = replace(self.state, running=False, elapsed_seconds=elapsed, window_title=None,
                                 confirmed_speed=None, message=message)
            return self.state
        if options["backup_periodic"] and now - self._last_periodic >= options["backup_interval_minutes"] * 60:
            self._last_periodic = now
            try:
                self._backup(options, "periodic")
                message = "Backup périodique créé."
            except (OSError, ValueError) as exc:
                message = "Backup périodique non créé : " + str(exc)
        try:
            window = self.windows.find(self.process.pid, options["emulator_path"])
        except OSError:
            window = None
            notice = "Fenêtre non détectable pour le moment."
            if notice not in message:
                message += " " + notice
        self.state = replace(self.state, elapsed_seconds=elapsed, window_title=window.title if window else None,
                             message=message)
        return self.state

    def arrange(self, rect: tuple[int, int, int, int]):
        if not self.state.running or self._run_options is None:
            raise ValueError("Aucune fenêtre DeSmuME lancée par ce Mode Jeu.")
        return self.windows.arrange(self.state.pid, rect, executable=self._run_options["emulator_path"])

    def stop_tracking(self) -> RunState:
        # Do not kill the emulator or fabricate a close-backup while it is running.
        self.tick()
        self.process = None
        self.state = replace(self.state, running=False, confirmed_speed=None,
                             message="Suivi arrêté. DeSmuME n'a pas été fermé ; les backups automatiques sont arrêtés.")
        return self.state
