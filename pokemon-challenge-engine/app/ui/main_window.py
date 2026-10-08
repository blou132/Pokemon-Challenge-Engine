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
        self.discovery_runner = SetupTaskRunner(self)
        self.discovery_runner.succeeded.connect(lambda report: self._discovery_completed(report, automatic=True))
        self.discovery_runner.failed.connect(self._discovery_failed)
        self.discovery_runner.busy_changed.connect(self._discovery_busy)
        self._discovery_started = False
        self._discovery_pending = False
        self._discovery_force = False
        self._discovery_report = None
        self._manual_config_changes = []
        self._discovery_changes = []
        self._closing = False
        self._installation_watch = QTimer(self)
        self._installation_watch.setInterval(30_000)
        self._installation_watch.timeout.connect(self._watch_installation)
        self.runs = RunManager(base_dir / "runs")
        self.runs_page = None
        self.run_controller = RunController(base_dir / "runs", self)
        self.run_controller.activated.connect(self._run_activated)
        self.run_controller.changed.connect(self._run_changed)
        self.run_controller.failed.connect(self._run_failed)
        self.run_controller.action_succeeded.connect(self._run_action_saved)
        self.run_prepare = SetupTaskRunner(self)
        self.run_prepare.succeeded.connect(self._run_prepared)
        self.run_prepare.failed.connect(self._run_prepare_failed)
        self._prepared_run = None
        self._requested_run_id = None
        self._preparing_run_id = None
        self._queued_resume_id = None
        self._open_after_activation = True
        self._run_mismatch_dialog = None
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
        self.runs_button = QPushButton("▣   Mes parties")
        self.runs_button.setObjectName("nav")
        self.runs_button.setCheckable(True)
        self.nav_group.addButton(self.runs_button, 6)
        side.addWidget(self.runs_button)
        # Keep page IDs stable; the template manager and editor are secondary
        # pages within Mes parties, with no competing sidebar entries.
        self.nav_buttons: dict[int, QPushButton] = {}
        for index, name in [(0, "⌂   Accueil"), (2, "≡   Règles"), (4, "⚙   Paramètres"), (5, "↔   Connexion DeSmuME")]:
            button = QPushButton(name)
            button.setObjectName("nav")
            button.setCheckable(True)
            self.nav_group.addButton(button, index)
            self.nav_buttons[index] = button
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
        self.bridge_controller.state_changed.connect(self.run_controller.consume)
        self.bridge_controller.state_changed.connect(lambda _: self._refresh_pending_installation())
        self.bridge_page = BridgePage(catalog, self.bridge_controller, self.config)
        for page in (self.home_page, self.challenge_page, self.rules_page, self.profile_page, self.settings_page, self.bridge_page):
            self.pages.addWidget(page)
        main.addWidget(self.pages, 1)
        self.setCentralWidget(center)
        self.home_page.create_requested.connect(lambda game_id: self.new_run(game_id=game_id))
        self.home_page.runs_requested.connect(lambda: self.navigate(6))
        self.challenge_page.back_requested.connect(lambda: self.navigate(3))
        self.challenge_page.saved.connect(self.profile_saved)
        self.challenge_page.launch_requested.connect(self.launch_challenge)
        self.profile_page.open_requested.connect(self.open_profile)
        self.profile_page.launch_requested.connect(self.launch_challenge)
        self.profile_page.changed.connect(self.refresh_home)
        self.profile_page.start_run_requested.connect(self.new_run)
        self.profile_page.back_requested.connect(lambda: self.navigate(6))
        self.profile_page.create_requested.connect(lambda: self.new_challenge(self.challenge_page.game_combo.currentData()))
        self.settings_page.config_changed.connect(self.config_changed)
        self.settings_page.installation_requested.connect(self.open_installation)
        self.settings_page.detection_requested.connect(lambda: self.refresh_installation(force=True))
        self.navigate(6)
        self.refresh_home()
        self.statusBar().showMessage(f"Prêt  ·  V{__version__} : préparation et lecture Lua, règles à respecter manuellement")
        if self.config_service.warnings:
            warning_text = "\n".join(self.config_service.warnings)
            QTimer.singleShot(0, lambda: QMessageBox.warning(self, "Configuration à vérifier", warning_text))
        try:
            restored_id = self.runs.active_id
        except (OSError, ValueError) as exc:
            restored_id = None
            self.statusBar().showMessage("Sélection précédente illisible, données conservées : " + str(exc))
        if restored_id is not None:
            self._requested_run_id = restored_id
            self._open_after_activation = False
            QTimer.singleShot(0, lambda: self._restore_run_selection(restored_id))

    def navigate(self, index: int) -> None:
        if index == 6:
            if self.runs_page is None:
                from app.ui.runs_page import RunsPage
                self.runs_page = RunsPage(self.catalog, self.runs)
                self.runs_page.new_requested.connect(self.new_run)
                self.runs_page.models_requested.connect(lambda: self.navigate(3))
                self.runs_page.installation_requested.connect(self.open_installation)
                self.runs_page.detection_requested.connect(lambda: self.refresh_installation(force=True))
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
            if self._discovery_report is not None:
                self.runs_page.set_detection_state(self._discovery_report)
            if self._discovery_started:
                self.refresh_installation()
            return
        if index == 3:
            self.profile_page.refresh()
        if index == 5:
            self.bridge_page.set_profiles(self.profiles.list_profiles())
        self.pages.setCurrentIndex(index)
        if index in (1, 3):
            self.runs_button.setChecked(True)
        else:
            self.nav_buttons[index].setChecked(True)

    def new_challenge(self, game_id: str) -> None:
        self.challenge_page.game_combo.setCurrentIndex(self.challenge_page.game_combo.findData(game_id))
        self.navigate(1)

    def profile_saved(self, profile: Profile) -> None:
        self.profile_page.refresh(select_profile_id=profile.id)
        self.refresh_home()
        self.statusBar().showMessage(f"Modèle « {profile.name} » enregistré", 8000)

    def refresh_home(self) -> None:
        profiles = self.profiles.list_profiles()
        self.bridge_page.set_profiles(profiles)
        count = len(profiles)
        self.home_page.model_count.setText(f"{count} modèle(s) disponible(s) pour vos prochaines parties. Retrouvez vos aventures dans Mes parties." if count else "Votre première partie vous attend : classique, depuis un modèle ou avec un challenge personnalisé.")

    def open_profile(self, profile: Profile) -> None:
        self.challenge_page.load_challenge(profile.challenge, profile.name)
        self.navigate(1)

    def config_changed(self, config: AppConfig) -> None:
        self._manual_config_changes.append((self.config, config))
        self.config = config
        self.bridge_page.set_config(config)
        self.statusBar().showMessage("Paramètres enregistrés", 6000)
        self.refresh_installation(force=True)

    def _ensure_game_mode(self):
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
            self.game_mode_window.process_context_changed.connect(lambda *_: self._refresh_pending_installation())
            self.game_mode_window.installation_changed.connect(lambda: self.refresh_installation())
            self.game_mode_window.set_run_guard(self._validate_requested_run)
            self.game_mode_window.run_mismatch.connect(self._show_run_mismatch)
            self.game_mode_window._setup_service = self.setup_service()
        return self.game_mode_window

    def _validate_requested_run(self, requested_run_id):
        active = self.run_controller.active_run
        try:
            return (not self.run_controller.activation_pending
                    and requested_run_id is not None
                    and requested_run_id == self._requested_run_id
                    and active is not None and active.run_id == requested_run_id
                    and self.run_controller.requested_run_id == requested_run_id
                    and self.runs.active_id == requested_run_id)
        except (OSError, ValueError):
            return False

    def _show_run_mismatch(self, requested_run_id):
        message = "La partie active ne correspond pas à celle demandée."
        self.statusBar().showMessage(message)
        if self.game_mode_window is not None:
            self.game_mode_window.hide()
        if self._run_mismatch_dialog is not None:
            self._run_mismatch_dialog.close()
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Partie à vérifier")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(message)
        retry = dialog.addButton("Réessayer", QMessageBox.ButtonRole.AcceptRole)
        library = dialog.addButton("Retour à Mes parties", QMessageBox.ButtonRole.RejectRole)
        retry.clicked.connect(lambda: self.resume_run(requested_run_id))
        library.clicked.connect(lambda: self.navigate(6))
        self._run_mismatch_dialog = dialog
        dialog.open()

    def open_game_mode(self, requested_run_id=None) -> None:
        # clicked(bool) is not a run identifier.
        requested = requested_run_id if isinstance(requested_run_id, str) else self._requested_run_id
        active = self.run_controller.active_run
        if requested is None and active is not None:
            requested = active.run_id
            self._requested_run_id = requested
        if requested is not None:
            if self.run_controller.activation_pending:
                self._open_after_activation = True
                self.statusBar().showMessage("Activation de la partie demandée…")
                return
            if not self._validate_requested_run(requested):
                self._show_run_mismatch(requested)
                return
        mode = self._ensure_game_mode()
        if requested is not None:
            mode.bind_requested_run(active, self.run_controller.state)
        self.game_mode_window.refresh_profiles()
        self.game_mode_window.show()
        self.game_mode_window.raise_()
        self.game_mode_window.activateWindow()

    def _restore_run_selection(self, run_id):
        if self._requested_run_id == run_id and self.run_controller.requested_run_id is None:
            self.run_controller.activate(run_id)

    def new_run(self, profile=None, *, game_id=None):
        from app.ui.run_dialogs import NewRunDialog
        from app.services.run_launch_service import RunLaunchService
        from PySide6.QtWidgets import QDialog
        options = GameModeConfigStore(self.base_dir, self.config).load()["launch_profiles"]
        dialog = NewRunDialog(self.catalog, self.profiles.list_profiles(), options, self, profile=profile)
        if self._discovery_report is not None:
            dialog.set_detection_state(self._discovery_report, select_ready=profile is None and game_id is None)
        if game_id is not None:
            dialog.game_combo.setCurrentIndex(dialog.game_combo.findData(game_id))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            values = dialog.selection()
            source = values.get("source", "profile" if values["profile_id"] else "classic")
            if source not in {"classic", "profile", "custom"}:
                raise ValueError("Source de configuration inconnue.")
            if source == "profile" and not values["profile_id"]:
                raise ValueError("Choisissez le modèle de cette partie.")
            if source != "profile" and values["profile_id"]:
                raise ValueError("Cette configuration directe ne doit pas référencer un modèle.")
            selected = self.profiles.load(values["profile_id"]) if source == "profile" else None
            game = self.catalog.games[values["game_id"]]
            challenge = selected.challenge if selected else None
            if source == "custom":
                challenge = Challenge.from_dict(values.get("challenge"))
                errors = ChallengeEngine(self.catalog).validate(challenge)
                if errors:
                    raise ValueError("\n".join(errors))
            snapshot = RunLaunchService(self.base_dir, self.config).snapshot(game.id, values["launch_profile"], values["save_path"])
            run = self.runs.create(values["name"], game.id, generation=game.generation,
                challenge=challenge, profile_id=selected.id if selected else None,
                preset=challenge.settings.get("preset_id") if challenge else "classic",
                game_code=game.game_code, region=game.region, revision=game.revision,
                save_path=values["save_path"] or None, launch_profile=snapshot)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Partie non créée", str(exc))
            return
        self.navigate(6)
        self.runs_page.notify_created(run.run_id)
        self.statusBar().showMessage("Partie créée", 8000)
        self.resume_run(run.run_id)
        return run

    def _session_busy(self):
        mode = self.game_mode_window
        return ((mode is not None and (mode.service.state.running or mode.launch_busy))
                or self.bridge_controller.state.status != "stopped")

    def _request_run(self, run_id):
        self._requested_run_id = run_id
        self.run_controller.expect_run(run_id)
        if self.game_mode_window is not None:
            previous = self.game_mode_window.persistent_run
            if previous is not None and previous.run_id != run_id:
                self.game_mode_window.hide()

    def resume_run(self, run_id):
        try:
            run = self.runs.load(run_id)
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage("Reprise impossible : " + str(exc))
            return
        self._request_run(run_id)
        self._open_after_activation = True
        active = self.run_controller.active_run
        if self.run_prepare.is_busy:
            self._queued_resume_id = run_id
            self.statusBar().showMessage("La partie demandée sera préparée après la vérification en cours.")
            return
        if self._session_busy():
            if active and active.run_id == run_id:
                self.open_game_mode(run_id)
            else:
                self.navigate(6)
                self.runs_page.highlight_run(run_id)
                self.statusBar().showMessage("Partie enregistrée. Fermez DeSmuME et arrêtez Lua, puis reprenez la partie demandée.")
            return
        try:
            from app.services.run_launch_service import RunLaunchService
            self._prepared_run = run
            self._preparing_run_id = run_id
            self._queued_resume_id = None
            self.statusBar().showMessage("Vérification de l'environnement de la partie…")
            setup = self.setup_service()
            self.run_prepare.start(lambda: RunLaunchService(self.base_dir, self.config, setup=setup).prepare(run))
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage("Reprise impossible : " + str(exc))

    def _run_prepare_failed(self, message):
        if self._queued_resume_id is not None:
            pending, self._queued_resume_id = self._queued_resume_id, None
            self.resume_run(pending)
            return
        self._preparing_run_id = None
        self.statusBar().showMessage("Partie conservée ; reprise impossible : " + message)

    def _run_prepared(self, result):
        if self._session_busy():
            self.statusBar().showMessage("Une session a démarré pendant la vérification. Terminez-la avant de reprendre cette partie.")
            return
        if self._queued_resume_id is not None:
            pending, self._queued_resume_id = self._queued_resume_id, None
            self.resume_run(pending)
            return
        if result.get("run_id") != self._requested_run_id:
            return
        self._preparing_run_id = None
        self._run_preparation_result = result
        self.run_controller.activate(result["run_id"])

    def _run_activated(self, run):
        if self._requested_run_id is None:
            self._requested_run_id = self.run_controller.requested_run_id
        if run.run_id != self._requested_run_id:
            return
        if not self._validate_requested_run(run.run_id):
            self._show_run_mismatch(run.run_id)
            return
        if self.runs_page is not None:
            self.runs_page.refresh_visible()
            self.runs_page.set_active_run(run.run_id)
            self.runs_page.highlight_run(run.run_id)
        if not self._open_after_activation:
            self.statusBar().showMessage(f"Partie sélectionnée : {run.name}. Reprenez-la depuis Mes parties.")
            return
        mode = self._ensure_game_mode()
        mode.bind_requested_run(run, self.run_controller.state)
        self.open_game_mode(run.run_id)
        self.bridge_controller.select_profile(None)
        self.bridge_page.persistent_game = run.game_id
        with QSignalBlocker(self.bridge_page.profile_combo):
            self.bridge_page.profile_combo.setCurrentIndex(0)
        with QSignalBlocker(self.bridge_page.game_combo):
            self.bridge_page.game_combo.setCurrentIndex(self.bridge_page.game_combo.findData(run.game_id))
        self.bridge_page.game_combo.setEnabled(False)
        self.bridge_page.profile_combo.setEnabled(False)
        result = getattr(self, "_run_preparation_result", None)
        if result and result["run_id"] == run.run_id:
            if result["health"]["ready"]:
                from copy import deepcopy
                snapshot = deepcopy(result["profile"])
                source = result.get("source", (run.launch_profile or {}).get("_source"))
                if source:
                    snapshot["_source"] = deepcopy(source)
                self._run_action(run.run_id, "update_launch_reference", {
                    "profile": snapshot, "rom_fingerprint": result["rom_fingerprint"]})
                message = "Partie prête. Jouer prépare la connexion Lua et lance DeSmuME ; le temps commence avec les messages du jeu."
            else:
                message = "Environnement à vérifier : " + "\n".join(result["health"]["issues"])
            self.game_mode_window.set_run_notice(message)
            self.statusBar().showMessage(message)

    def _run_changed(self, run, state):
        if run is None or (self._requested_run_id is not None and run.run_id != self._requested_run_id):
            return
        if self.game_mode_window and self._validate_requested_run(run.run_id):
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
        if action != "set_status" and (active is None or active.run_id != run_id
                                      or self._requested_run_id not in (None, run_id)):
            self.statusBar().showMessage("Reprenez cette partie pour y enregistrer une action.")
            return
        if action == "update_launch_reference" and self.game_mode_window and self.game_mode_window._pending_run_launch is None:
            self.game_mode_window._pending_reference_save = True
            self.game_mode_window.page.launch_button.setEnabled(False)
        self.run_controller.action(run_id, action, payload)

    def _run_failed(self, message):
        self.statusBar().showMessage("Partie : " + message)
        if self.game_mode_window and self.game_mode_window.persistent_run is not None and self.game_mode_window.persistent_run.run_id == self._requested_run_id:
            self.game_mode_window.run_action_failed(message)

    def _run_action_saved(self, run_id, action, run):
        if self.game_mode_window and self._requested_run_id == run_id:
            self.game_mode_window.run_action_saved(run_id, action, run)
        if self.runs_page and action == "set_status":
            self.runs_page.refresh_visible()

    def _run_saves(self, run_id):
        active = self.run_controller.active_run
        if active is None or active.run_id != run_id:
            self.statusBar().showMessage("Reprenez cette partie avant d'ouvrir ses sauvegardes.")
            return
        self.open_game_mode(run_id)
        if self.game_mode_window is None or not self._validate_requested_run(run_id):
            return
        self.game_mode_window.open_settings("saves")

    def setup_service(self):
        if self._setup_service is None:
            from app.services.auto_setup_service import AutoSetupService
            self._setup_service = AutoSetupService(self.base_dir, self.config)
        return self._setup_service

    def start_first_run(self) -> None:
        # Called by app.main after the window appears, on every startup.
        # Missing games are status information, never a compulsory wizard.
        self._discovery_started = True
        self.refresh_installation()

    def refresh_installation(self, *, force=False) -> None:
        if self._closing:
            return
        self._discovery_force |= force
        if self.discovery_runner.is_busy:
            self._discovery_pending = True
            return
        if self._session_busy() or (self.installation_dialog is not None and self.installation_dialog.is_busy):
            self._discovery_pending = True
            return
        self._discovery_started = True
        self._discovery_pending = False
        requested_force, self._discovery_force = self._discovery_force, False
        changes, self._manual_config_changes = self._manual_config_changes, []
        self._discovery_changes = changes
        service = self.setup_service()

        def discover():
            for previous, current in changes:
                service.apply_manual_config(previous, current)
            return service.automatic_setup(force=requested_force)

        self.discovery_runner.start(discover)

    def _refresh_pending_installation(self):
        if self._discovery_pending and not self.discovery_runner.is_busy and not self._session_busy():
            self.refresh_installation()

    def _watch_installation(self):
        # Stat cached discovery roots so a disk/file change is noticed even when
        # the player stays on the same page. Unchanged files reuse the report.
        if not self.discovery_runner.is_busy:
            self.refresh_installation()

    def _discovery_busy(self, busy):
        if self.runs_page is not None:
            self.runs_page.set_detection_busy(busy)

    def _discovery_completed(self, report, *, automatic=False):
        if automatic:
            self._discovery_changes = []
            if not self._installation_watch.isActive():
                self._installation_watch.start()
        self._discovery_report = report
        self.settings_page.set_detection_state(report)
        self.home_page.set_detection_state(report)
        if self.runs_page is not None:
            self.runs_page.set_detection_state(report)
        if self.installation_dialog is not None and not self.installation_dialog.is_busy:
            self.installation_dialog.set_detection_state(report)
        mode = self.game_mode_window
        if mode is not None and not mode.service.state.running and not mode.launch_busy:
            mode.service.reload_preferences()
        self.statusBar().showMessage("Installation prête." if report.get("ready") else
                                     "Recherche terminée. Consultez l'état des jeux dans Mes parties.", 8000)
        if self._discovery_pending or self._manual_config_changes:
            QTimer.singleShot(0, lambda: self.refresh_installation())

    def _discovery_failed(self, message):
        # Reapplying these explicit edits is idempotent. Keep them for a user
        # retry if persistence or discovery failed; never overwrite their intent.
        self._manual_config_changes = self._discovery_changes + self._manual_config_changes
        self._discovery_changes = []
        self._discovery_pending = False
        self._installation_watch.stop()  # A failed operation needs a deliberate retry.
        self.statusBar().showMessage("Recherche à vérifier : " + message)
        report = {"game_states": {game.id: {"status": "needs_attention", "message": message}
                                  for game in self.catalog.games.values() if game.status == "supported"},
                  "ready": False, "warnings": [message], "error": message}
        self._discovery_report = report
        self.settings_page.set_detection_state(report)
        self.home_page.set_detection_state(report)
        if self.runs_page is not None:
            self.runs_page.set_detection_state(report)

    def open_installation(self, *, first_run=False) -> None:
        from app.ui.setup_dialog import InstallationDialog
        if self.installation_dialog is None:
            self.installation_dialog = InstallationDialog(self.setup_service(), self, first_run=first_run,
                active_session=lambda: self.bridge_controller.bridge.session_id or (
                    "owned-emulator" if self.game_mode_window and self.game_mode_window.service.state.running else ""))
            self.installation_dialog.configuration_ready.connect(self._installation_ready)
            self.installation_dialog.play_requested.connect(self._play_installed_game)
            self.installation_dialog.detection_completed.connect(self._discovery_completed)
        self.installation_dialog.show()
        self.installation_dialog.raise_()
        self.installation_dialog.activateWindow()
        if self._discovery_report is not None:
            self.installation_dialog.set_detection_state(self._discovery_report)
        if not self.discovery_runner.is_busy:
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
        if (self.discovery_runner.is_busy or self.run_prepare.is_busy or self.run_controller.activation_pending or (self.installation_dialog is not None and self.installation_dialog.is_busy)
                or (self.game_mode_window is not None and (self.game_mode_window.launch_busy
                    or self.game_mode_window._pending_run_launch is not None or self.game_mode_window._pending_reference_save))):
            self.statusBar().showMessage("Attendez la fin de la préparation avant de fermer PCE.")
            event.ignore()
            return
        self._closing = True
        self._installation_watch.stop()
        if self.installation_dialog is not None:
            self.installation_dialog.close()
        if self.game_mode_window is not None:
            self.game_mode_window.close()
            self.game_mode_window.shutdown_tracking()
        if not self.run_controller.shutdown():
            self._closing = False
            self.statusBar().showMessage("La progression PCE n'a pas pu être enregistrée. Vérifiez l'espace disque et réessayez de fermer.")
            event.ignore()
            return
        self.bridge_controller.shutdown()
        super().closeEvent(event)
