"""Navigation principale et orchestration des services applicatifs."""

import logging
from pathlib import Path

from PySide6.QtCore import QTimer
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
from app.ui.bridge_page import BridgePage
from app.ui.challenge_page import ChallengePage
from app.ui.home_page import HomePage
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
        self.profile_page.refresh()
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
        self.bridge_controller.shutdown()
        super().closeEvent(event)
