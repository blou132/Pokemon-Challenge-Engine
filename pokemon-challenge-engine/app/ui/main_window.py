"""Navigation principale et orchestration des services applicatifs."""

import logging
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QMainWindow, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from app import __version__
from app.core.catalog import Catalog
from app.core.challenge_engine import ChallengeEngine
from app.core.profile_manager import ProfileManager
from app.models.challenge import Challenge
from app.models.profile import Profile
from app.services.bridge_controller import BridgeController
from app.services.config_service import AppConfig, ConfigService
from app.services.launcher_service import LauncherService
from app.services.game_mode_config import GameModeConfigStore
from app.ui.bridge_page import BridgePage
from app.ui.challenge_page import ChallengePage
from app.ui.home_page import HomePage
from app.ui.game_mode_window import GameModeWindow
from app.ui.profile_page import ProfilePage
from app.ui.rules_page import RulesPage
from app.ui.settings_page import SettingsPage
from app.ui.widgets.common import label

LOGGER = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, catalog: Catalog, base_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.setWindowTitle("Pokemon Challenge Engine")
        self.resize(1260, 740)
        self.setMinimumSize(1060, 640)
        self.config_service = ConfigService(base_dir / "config.json")
        self.config = self.config_service.load()
        self.profiles = ProfileManager(base_dir / "profiles")
        self.base_dir = base_dir
        self.game_mode_window: GameModeWindow | None = None
        self.installation_dialog = None
        self._setup_service = None
        from app.core.run_manager import RunManager
        from app.services.run_controller import RunController
        from app.ui.setup_tasks import SetupTaskRunner
        self.runs = RunManager(base_dir / "runs")
        self.runs_page = None
        self.run_controller = RunController(base_dir / "runs", self)
        self.run_controller.activated.connect(self._run_activated)
        self.run_controller.changed.connect(self._run_changed)
        self.run_controller.failed.connect(self._run_failed)
        self.run_controller.action_succeeded.connect(self._run_action_saved)
        self.run_prepare = SetupTaskRunner(self)
        self.run_prepare.succeeded.connect(self._run_prepared)
        self.run_prepare.failed.connect(lambda message: self.statusBar().showMessage("Reprise impossible : " + message))
        self._prepared_run = None
        self._last_run_saved = None
        self._game_mode_shortcut = QShortcut(self)
        self._game_mode_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._game_mode_shortcut.activated.connect(self.open_game_mode)
        self._set_game_mode_shortcut(GameModeConfigStore(base_dir, self.config).load()["shortcuts"])
        center = QWidget()
        main = QHBoxLayout(center)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 28, 16, 18)
        side.setSpacing(7)
        side.addWidget(label("◈  POKEMON", "brand"))
        side.addWidget(label("     CHALLENGE ENGINE", "eyebrow"))
        side.addSpacing(28)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons: list[QPushButton] = []
        for index, name in enumerate(["⌂   Accueil", "+   Nouveau challenge", "≡   Règles", "▤   Profils", "⚙   Paramètres", "↔   Connexion DeSmuME"]):
            button = QPushButton(name)
            button.setObjectName("nav")
            button.setCheckable(True)
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            side.addWidget(button)
        self.nav_group.idClicked.connect(self.navigate)
        self.runs_button = QPushButton("▣   Mes parties")
        self.runs_button.setObjectName("nav")
        self.runs_button.setCheckable(True)
        self.nav_group.addButton(self.runs_button, 6)
        side.insertWidget(4, self.runs_button)
        self.game_mode_button = QPushButton("▷   Mode Jeu")
        self.game_mode_button.setObjectName("primary")
        self.game_mode_button.setToolTip("Ouvre les panneaux de jeu autour d'une fenêtre DeSmuME externe.")
        self.game_mode_button.clicked.connect(self.open_game_mode)
        side.addSpacing(12)
        side.addWidget(self.game_mode_button)
        side.addStretch()
        side.addWidget(label("UN CHALLENGE À LA FOIS", "eyebrow"))
        side.addWidget(label("Préparez. Sauvegardez.\nPartez à l'aventure.", "muted"))
        side.addSpacing(15)
        side.addWidget(label(f"V{__version__}   •   LOCAL", "badge"))
        main.addWidget(sidebar)
        self.pages = QStackedWidget()
        self.home_page = HomePage(catalog)
        self.challenge_page = ChallengePage(catalog, self.profiles)
        self.rules_page = RulesPage(catalog)
        self.profile_page = ProfilePage(catalog, self.profiles)
        self.settings_page = SettingsPage(self.config_service, self.config, catalog.games.values())
        self.bridge_controller = BridgeController(base_dir, self)
        self.bridge_controller.state_changed.connect(self.run_controller.consume)
        self.bridge_page = BridgePage(catalog, self.bridge_controller, self.config)
        for page in (self.home_page, self.challenge_page, self.rules_page, self.profile_page, self.settings_page, self.bridge_page):
            self.pages.addWidget(page)
        main.addWidget(self.pages, 1)
        self.setCentralWidget(center)
        self.home_page.create_requested.connect(self.new_challenge)
        self.home_page.profiles_requested.connect(lambda: self.navigate(3))
        self.challenge_page.saved.connect(self.profile_saved)
        self.challenge_page.launch_requested.connect(self.launch_challenge)
        self.profile_page.open_requested.connect(self.open_profile)
        self.profile_page.launch_requested.connect(self.launch_challenge)
        self.profile_page.changed.connect(self.refresh_home)
        self.profile_page.start_run_requested.connect(self.new_run)
        self.settings_page.config_changed.connect(self.config_changed)
        self.settings_page.installation_requested.connect(self.open_installation)
        self.navigate(0)
        self.refresh_home()
        self.statusBar().showMessage(f"Prêt  ·  V{__version__} : préparation et lecture Lua, règles à respecter manuellement")
        if self.config_service.warnings:
            warning_text = "\n".join(self.config_service.warnings)
            QTimer.singleShot(0, lambda: QMessageBox.warning(self, "Configuration à vérifier", warning_text))

    def navigate(self, index: int) -> None:
        if index == 6:
            if self.runs_page is None:
                from app.ui.runs_page import RunsPage
                self.runs_page = RunsPage(self.catalog, self.runs)
                self.runs_page.new_requested.connect(self.new_run)
                self.runs_page.resume_requested.connect(self.resume_run)
                self.runs_page.saves_requested.connect(self._run_saves)
                self.runs_page.action_requested.connect(self._run_action)
                self.pages.addWidget(self.runs_page)
            self.runs_page.refresh()
            active = self.run_controller.active_run
            try:
                active_id = active.run_id if active else self.runs.active_id
            except (OSError, ValueError) as exc:
                active_id = None
                self.statusBar().showMessage("Sélection précédente illisible, données conservées : " + str(exc))
            self.runs_page.set_active_run(active_id)
            self.pages.setCurrentWidget(self.runs_page)
            self.runs_button.setChecked(True)
            return
        if index == 3:
            self.profile_page.refresh()
        if index == 5:
            self.bridge_page.set_profiles(self.profiles.list_profiles())
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)

    def new_challenge(self, game_id: str) -> None:
        self.challenge_page.game_combo.setCurrentIndex(self.challenge_page.game_combo.findData(game_id))
        self.navigate(1)

    def profile_saved(self, profile: Profile) -> None:
        self.profile_page.refresh(select_profile_id=profile.id)
        self.refresh_home()
        self.statusBar().showMessage(f"Profil « {profile.name} » enregistré", 8000)

    def refresh_home(self) -> None:
        profiles = self.profiles.list_profiles()
        self.bridge_page.set_profiles(profiles)
        count = len(profiles)
        self.home_page.profile_count.setText(f"{count} profil(s) enregistré(s) · Retrouvez vos aventures dans Profils." if count else "Votre premier challenge vous attend. Commencez par choisir un jeu.")

    def open_profile(self, profile: Profile) -> None:
        self.challenge_page.load_challenge(profile.challenge, profile.name)
        self.navigate(1)

    def config_changed(self, config: AppConfig) -> None:
        self.config = config
        self.bridge_page.set_config(config)
        self.statusBar().showMessage("Paramètres enregistrés", 6000)

    def open_game_mode(self) -> None:
        if self.game_mode_window is None:
            self.game_mode_window = GameModeWindow(self.catalog, self.base_dir, self.bridge_controller,
                                                   self.profiles, self.config, self)
            self.game_mode_window.bridge_requested.connect(self._show_bridge_for_game_mode)
            self.game_mode_window.profile_selected.connect(self._game_mode_profile_selected)
            self.game_mode_window.process_launched.connect(self.bridge_page.track_process)
            self.game_mode_window.shortcuts_changed.connect(self._set_game_mode_shortcut)
            self.game_mode_window.installation_requested.connect(self.open_installation)
            self.game_mode_window.run_action_requested.connect(self._run_action)
            self.game_mode_window.process_context_changed.connect(self.run_controller.process_context)
        self.game_mode_window.refresh_profiles()
        self.game_mode_window.show()
        self.game_mode_window.raise_()
        self.game_mode_window.activateWindow()

    def new_run(self, profile=None):
        from app.ui.run_dialogs import NewRunDialog
        from app.services.run_launch_service import RunLaunchService
        from PySide6.QtWidgets import QDialog
        options = GameModeConfigStore(self.base_dir, self.config).load()["launch_profiles"]
        dialog = NewRunDialog(self.catalog, self.profiles.list_profiles(), options, self, profile=profile)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            values = dialog.selection()
            selected = self.profiles.load(values["profile_id"]) if values["profile_id"] else None
            game = self.catalog.games[values["game_id"]]
            snapshot = RunLaunchService(self.base_dir, self.config).snapshot(game.id, values["launch_profile"], values["save_path"])
            run = self.runs.create(values["name"], game.id, generation=game.generation,
                challenge=selected.challenge if selected else None, profile_id=selected.id if selected else None,
                preset=selected.challenge.settings.get("preset_id") if selected else "classic",
                game_code=game.game_code, region=game.region, revision=game.revision,
                save_path=values["save_path"] or None, launch_profile=snapshot)
            self.navigate(6)
            self.resume_run(run.run_id)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Partie non créée", str(exc))

    def resume_run(self, run_id):
        if self.run_prepare.is_busy:
            return
        active = self.run_controller.active_run
        mode = self.game_mode_window
        busy = (mode is not None and (mode.service.state.running or mode.play_runner.is_busy)) or self.bridge_controller.state.status != "stopped"
        if busy:
            if active and active.run_id == run_id:
                self.open_game_mode()
            else:
                self.statusBar().showMessage("Fermez DeSmuME et arrêtez Lua avant de changer de partie.")
            return
        try:
            from app.services.run_launch_service import RunLaunchService
            self._prepared_run = self.runs.load(run_id)
            run = self._prepared_run
            self.statusBar().showMessage("Vérification de l'environnement de la partie…")
            self.run_prepare.start(lambda: RunLaunchService(self.base_dir, self.config).prepare(run))
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage("Reprise impossible : " + str(exc))

    def _run_prepared(self, result):
        mode = self.game_mode_window
        if (mode is not None and (mode.service.state.running or mode.play_runner.is_busy)) or self.bridge_controller.state.status != "stopped":
            self.statusBar().showMessage("Une session a démarré pendant la vérification. Terminez-la avant de reprendre cette partie.")
            return
        self._run_preparation_result = result
        self.run_controller.activate(result["run_id"])

    def _run_activated(self, run):
        self.open_game_mode()
        self.bridge_controller.select_profile(None)
        self.bridge_page.persistent_game = run.game_id
        with QSignalBlocker(self.bridge_page.profile_combo):
            self.bridge_page.profile_combo.setCurrentIndex(0)
        with QSignalBlocker(self.bridge_page.game_combo):
            self.bridge_page.game_combo.setCurrentIndex(self.bridge_page.game_combo.findData(run.game_id))
        self.bridge_page.game_combo.setEnabled(False)
        self.bridge_page.profile_combo.setEnabled(False)
        self.game_mode_window.set_persistent_run(run)
        result = getattr(self, "_run_preparation_result", None)
        if result and result["run_id"] == run.run_id:
            if result["health"]["ready"]:
                from copy import deepcopy
                snapshot = deepcopy(result["profile"])
                if "_source" in run.launch_profile:
                    snapshot["_source"] = deepcopy(run.launch_profile["_source"])
                self._run_action(run.run_id, "update_launch_reference", {
                    "profile": snapshot, "rom_fingerprint": result["rom_fingerprint"]})
                message = "Partie prête. Lancez DeSmuME avec Jouer ; le temps commencera avec les messages du jeu."
            else:
                message = "Environnement à vérifier : " + "\n".join(result["health"]["issues"])
            self.game_mode_window.set_run_notice(message)
            self.statusBar().showMessage(message)

    def _run_changed(self, run, state):
        if run is None:
            return
        if self.game_mode_window:
            self.game_mode_window.set_persistent_run(run, state)
            options = self.game_mode_window.launch_options(run.game_id)
            self.bridge_page.set_config(AppConfig(self.config.retrobat_path, options.get("emulator_path", ""),
                self.config.rom_paths | {run.game_id: options.get("rom_path", "")}, self.config.save_path))
        marker = (run.run_id, state.get("last_saved_at"))
        if self.runs_page and marker != self._last_run_saved:
            self._last_run_saved = marker
            self.runs_page.set_active_run(run.run_id)
            self.runs_page.refresh_visible()

    def _run_action(self, run_id, action, payload):
        active = self.run_controller.active_run
        if action != "set_status" and (active is None or active.run_id != run_id):
            self.statusBar().showMessage("Reprenez cette partie pour y enregistrer une action.")
            return
        if action == "update_launch_reference" and self.game_mode_window and self.game_mode_window._pending_run_launch is None:
            self.game_mode_window._pending_reference_save = True
            self.game_mode_window.page.launch_button.setEnabled(False)
        self.run_controller.action(run_id, action, payload)

    def _run_failed(self, message):
        self.statusBar().showMessage("Partie : " + message)
        if self.game_mode_window:
            self.game_mode_window.run_action_failed(message)

    def _run_action_saved(self, run_id, action, run):
        if self.game_mode_window:
            self.game_mode_window.run_action_saved(run_id, action, run)
        if self.runs_page and action == "set_status":
            self.runs_page.refresh_visible()

    def _run_saves(self, run_id):
        active = self.run_controller.active_run
        if active is None or active.run_id != run_id:
            self.statusBar().showMessage("Reprenez cette partie avant d'ouvrir ses sauvegardes.")
            return
        self.open_game_mode()
        self.game_mode_window.open_settings("saves")

    def setup_service(self):
        if self._setup_service is None:
            from app.services.auto_setup_service import AutoSetupService
            self._setup_service = AutoSetupService(self.base_dir, self.config)
        return self._setup_service

    def start_first_run(self) -> None:
        try:
            if not self.setup_service().first_run_done:
                self.open_installation(first_run=True)
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage("Installation à vérifier : " + str(exc))

    def open_installation(self, *, first_run=False) -> None:
        from app.ui.setup_dialog import InstallationDialog
        if self.installation_dialog is None:
            self.installation_dialog = InstallationDialog(self.setup_service(), self, first_run=first_run,
                active_session=lambda: self.bridge_controller.bridge.session_id or (
                    "owned-emulator" if self.game_mode_window and self.game_mode_window.service.state.running else ""))
            self.installation_dialog.configuration_ready.connect(self._installation_ready)
            self.installation_dialog.play_requested.connect(self._play_installed_game)
        self.installation_dialog.show()
        self.installation_dialog.raise_()
        self.installation_dialog.activateWindow()
        self.installation_dialog.start()

    def _installation_ready(self, game_id):
        if self.game_mode_window is not None:
            self.game_mode_window.service.reload_preferences()
            if not self.game_mode_window.service.state.running:
                self.game_mode_window._game_changed(self.game_mode_window.page.game_combo.currentData())
            run = self.game_mode_window.persistent_run
            if run and run.game_id == game_id and not self.game_mode_window.service.state.running and self.bridge_controller.state.status == "stopped":
                answer = QMessageBox.question(self, "Associer l'installation à cette partie ?",
                    f"Utiliser la ROM, l'émulateur et la sauvegarde préparés pour « {run.name} » ? "
                    "Cela change les références locales de cette partie. Aucun fichier Pokémon n'est déplacé ou importé.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if answer == QMessageBox.StandardButton.Yes:
                    from app.services.run_launch_service import RunLaunchService
                    try:
                        snapshot = RunLaunchService(self.base_dir, self.config).snapshot(game_id)
                        self._run_action(run.run_id, "update_launch_reference", {"profile": snapshot})
                        self.game_mode_window.set_run_notice("Installation associée à la partie. Jouer revérifiera les références avant lancement.")
                    except (OSError, ValueError) as exc:
                        self.statusBar().showMessage("Association non enregistrée : " + str(exc))
        self.statusBar().showMessage("Installation du jeu préparée sur cet ordinateur.", 8000)

    def _play_installed_game(self, game_id):
        self.open_game_mode()
        mode = self.game_mode_window
        if mode.persistent_run is not None:
            mode.page.status_label.setText("Une partie est sélectionnée. Son environnement se règle dans Profil de lancement ; reprenez une autre partie depuis Mes parties.")
            return
        if mode.service.state.running or self.bridge_controller.state.status != "stopped":
            mode.page.status_label.setText("Terminez la session actuelle avant de lancer un autre jeu.")
            return
        mode.service.reload_preferences()
        mode.page.game_combo.setCurrentIndex(mode.page.game_combo.findData(game_id))
        mode.launch_game(game_id)

    def _set_game_mode_shortcut(self, values: dict) -> None:
        value = values.get("game_mode", "")
        self._game_mode_shortcut.setKey(QKeySequence(value))
        self._game_mode_shortcut.setEnabled(bool(value))

    def _show_bridge_for_game_mode(self) -> None:
        self.navigate(5)
        if self.game_mode_window is not None and self.bridge_controller.state.status == "stopped":
            mode = self.game_mode_window
            game_id = mode.page.game_combo.currentData()
            options = mode.launch_options(game_id)
            self.bridge_page.set_config(AppConfig(
                retrobat_path=self.config.retrobat_path,
                desmume_path=options["emulator_path"],
                rom_paths=self.config.rom_paths | {game_id: options["rom_path"]},
                save_path=self.config.save_path,
            ))
            with QSignalBlocker(self.bridge_page.game_combo):
                self.bridge_page.game_combo.setCurrentIndex(self.bridge_page.game_combo.findData(game_id))
            with QSignalBlocker(self.bridge_page.profile_combo):
                index = self.bridge_page.profile_combo.findData(mode.page.profile_combo.currentData())
                self.bridge_page.profile_combo.setCurrentIndex(max(0, index))
        self.show()
        self.raise_()
        self.activateWindow()

    def _game_mode_profile_selected(self, profile_id) -> None:
        # Le Mode Jeu a déjà demandé la sélection au contrôleur. Synchroniser
        # uniquement le choix visible pour conserver une association unique.
        with QSignalBlocker(self.bridge_page.profile_combo):
            index = self.bridge_page.profile_combo.findData(profile_id)
            self.bridge_page.profile_combo.setCurrentIndex(max(index, 0))
        if self.game_mode_window:
            with QSignalBlocker(self.bridge_page.game_combo):
                game_id = self.game_mode_window.page.game_combo.currentData()
                self.bridge_page.game_combo.setCurrentIndex(self.bridge_page.game_combo.findData(game_id))

    def launch_challenge(self, challenge: Challenge) -> None:
        if self.run_controller.active_run is not None or (self.game_mode_window is not None and self.game_mode_window.service.state.running):
            self.statusBar().showMessage("Une partie ou session est déjà sélectionnée. Utilisez Mes parties ou le Mode Jeu pour continuer.")
            self.open_game_mode()
            return
        errors = ChallengeEngine(self.catalog).validate(challenge)
        launcher = LauncherService(self.config)
        errors.extend(launcher.validate(challenge.game_id))
        if errors:
            QMessageBox.warning(self, "Lancement impossible", "\n".join(errors) + "\n\nLes chemins se règlent dans Paramètres.")
            return
        try:
            process = launcher.launch(challenge.game_id)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Lancement impossible", str(exc))
            return
        self.bridge_page.track_process(process)
        self.statusBar().showMessage("DeSmuME démarré · Consultez Connexion DeSmuME pour préparer Lua. Les règles restent manuelles.", 12000)
        # Détecter un refus immédiat, sans attendre ni bloquer l'interface.
        QTimer.singleShot(1500, lambda: self._check_launch(process))

    def _check_launch(self, process: object) -> None:
        code = process.poll()
        if code is not None and code != 0:
            LOGGER.warning("DeSmuME s'est arrêté au démarrage (code %s).", code)
            QMessageBox.warning(self, "DeSmuME s'est arrêté", "L'émulateur s'est arrêté après le lancement. Vérifiez votre installation et la ROM sélectionnée.")

    def closeEvent(self, event) -> None:
        if (self.run_prepare.is_busy or (self.installation_dialog is not None and self.installation_dialog.is_busy)
                or (self.game_mode_window is not None and (self.game_mode_window.play_runner.is_busy
                    or self.game_mode_window._pending_run_launch is not None or self.game_mode_window._pending_reference_save))):
            self.statusBar().showMessage("Attendez la fin de la préparation avant de fermer PCE.")
            event.ignore()
            return
        if self.installation_dialog is not None:
            self.installation_dialog.close()
        if self.game_mode_window is not None:
            self.game_mode_window.close()
            self.game_mode_window.shutdown_tracking()
        if not self.run_controller.shutdown():
            self.statusBar().showMessage("La progression PCE n'a pas pu être enregistrée. Vérifiez l'espace disque et réessayez de fermer.")
            event.ignore()
            return
        self.bridge_controller.shutdown()
        super().closeEvent(event)
