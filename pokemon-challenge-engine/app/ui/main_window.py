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
        self.settings_page.config_changed.connect(self.config_changed)
        self.settings_page.installation_requested.connect(self.open_installation)
        self.navigate(0)
        self.refresh_home()
        self.statusBar().showMessage(f"Prêt  ·  V{__version__} : préparation et lecture Lua, règles à respecter manuellement")
        if self.config_service.warnings:
            warning_text = "\n".join(self.config_service.warnings)
            QTimer.singleShot(0, lambda: QMessageBox.warning(self, "Configuration à vérifier", warning_text))

    def navigate(self, index: int) -> None:
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
        self.game_mode_window.refresh_profiles()
        self.game_mode_window.show()
        self.game_mode_window.raise_()
        self.game_mode_window.activateWindow()

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
                active_session=lambda: self.bridge_controller.bridge.session_id or "")
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
        self.statusBar().showMessage("Installation du jeu préparée sur cet ordinateur.", 8000)

    def _play_installed_game(self, game_id):
        self.open_game_mode()
        mode = self.game_mode_window
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
            options = mode.service.config["launch_profiles"][game_id]
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
        if ((self.installation_dialog is not None and self.installation_dialog.is_busy)
                or (self.game_mode_window is not None and self.game_mode_window.play_runner.is_busy)):
            self.statusBar().showMessage("Attendez la fin de la préparation avant de fermer PCE.")
            event.ignore()
            return
        if self.installation_dialog is not None:
            self.installation_dialog.close()
        if self.game_mode_window is not None:
            self.game_mode_window.close()
        self.bridge_controller.shutdown()
        super().closeEvent(event)
