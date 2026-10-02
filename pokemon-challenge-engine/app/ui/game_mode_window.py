"""Fenêtre frontend indépendante ; DeSmuME conserve sa fenêtre et ses entrées."""

from pathlib import Path

from PySide6.QtCore import QPoint, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QMessageBox, QTabWidget, QVBoxLayout

from app.core.catalog import Catalog
from app.core.profile_manager import ProfileManager
from app.services.config_service import AppConfig
from app.services.emulator_settings_service import EmulatorSettingsService, key_label
from app.services.game_mode_service import GameModeService
from app.services.save_manager_service import SaveManagerService
from app.ui.controls_page import ControlsPage
from app.ui.game_mode_page import GAME_MODE_STYLE, GameModePage
from app.ui.game_mode_settings import InterfaceInGamePage, LaunchProfilePage
from app.ui.graphics_page import GraphicsPage
from app.ui.save_manager_page import SaveManagerPage
from app.ui.setup_tasks import SetupTaskRunner


class GameModeWindow(QMainWindow):
    bridge_requested = Signal()
    profile_selected = Signal(object)
    process_launched = Signal(object)
    shortcuts_changed = Signal(dict)
    installation_requested = Signal()

    def __init__(self, catalog: Catalog, base_dir: Path, bridge_controller, profiles: ProfileManager,
                 config: AppConfig, parent=None, *, service: GameModeService | None = None):
        super().__init__(parent)
        self.setWindowTitle("Pokemon Challenge Engine · Mode Jeu")
        self.resize(1366, 768)
        self.setMinimumSize(1100, 640)
        self.setStyleSheet(GAME_MODE_STYLE)
        self.catalog, self.base_dir, self.controller, self.profiles = catalog, Path(base_dir), bridge_controller, profiles
        self.service = service if service is not None else GameModeService(base_dir, config)
        self._legacy_config = config
        self._setup_service = None
        self._preparing_game = None
        self.play_runner = SetupTaskRunner(self)
        self.play_runner.succeeded.connect(self._play_prepared)
        self.play_runner.failed.connect(self._play_failed)
        self.play_runner.busy_changed.connect(self._play_busy)
        self.page = GameModePage(catalog)
        self.setCentralWidget(self.page)
        self.settings_dialog = None
        self._shortcuts = {}
        self._settings_game = None
        self._arrange_pending = False
        self._arrange_attempts = 0
        self._last_profile_revision = None
        self.page.launch_requested.connect(self.launch_game)
        self.page.profile_requested.connect(self._select_profile)
        self.page.game_changed.connect(self._game_changed)
        self.page.settings_requested.connect(self.open_settings)
        self.page.speed_requested.connect(self.request_speed)
        self.page.backup_requested.connect(self.backup_now)
        self.page.fullscreen_requested.connect(self.toggle_fullscreen)
        self.page.arrange_requested.connect(self.arrange_windows)
        self.page.reconnect_requested.connect(self.reconnect_lua)
        self.page.stop_session_requested.connect(self.stop_lua_for_change)
        self.controller.state_changed.connect(self.page.set_bridge_state)
        self.controller.tracking_changed.connect(self._tracking_changed)
        self.page.set_bridge_state(self.controller.state)
        self.page.set_tracking_state(self.controller.tracking_state)
        self.page.set_interface(self.service.config["interface"])
        self.page.set_run_state(self.service.state)
        self.set_shortcuts(self.service.config["shortcuts"])
        self.refresh_profiles()
        self._game_changed(self.page.game_combo.currentData(), select_associated=self.controller.tracking_state.profile_id is None)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh_run)
        self.timer.start()

    def refresh_profiles(self):
        values = self.profiles.list_profiles()
        active = self.controller.tracking_state.profile_id
        if active is None and self.controller.state.status == "stopped":
            active = self.page.profile_combo.currentData()
        self.page.set_profiles(values, active)
        if self.settings_dialog:
            self.launch_settings.set_profiles(values)

    def _select_profile(self, profile_id):
        if self.controller.state.status != "stopped" or self.service.state.running:
            self.page.set_profiles(self.profiles.list_profiles(), self.controller.tracking_state.profile_id)
            self.page.status_label.setText("Terminez la session et arrêtez la connexion Lua avant de changer de profil.")
            return
        self.controller.select_profile(profile_id)
        self.profile_selected.emit(profile_id)
        self._game_changed(self.page.game_combo.currentData(), select_associated=False)
        self.page.set_bridge_state(self.controller.state)

    def _game_changed(self, game_id, *, select_associated=True):
        options = self.service.config["launch_profiles"][game_id]
        if select_associated and self.controller.state.status == "stopped" and not self.service.state.running:
            desired = options["challenge_profile_id"]
            index = self.page.profile_combo.findData(desired)
            if index < 0:
                index = 0
                self.page.status_label.setText("Le profil challenge associé n'est plus disponible. Choisissez un profil avant le lancement.")
            if self.page.profile_combo.currentIndex() != index:
                self.page.profile_combo.setCurrentIndex(index)
        self.page.save_policy_label.setText("Save states : " + {
            "allowed": "autorisés", "forbidden": "interdits (politique seulement)",
            "outside_battle": "hors combat (politique seulement)",
            "read_only": "lecture seule (politique seulement)", "unmanaged": "non géré",
        }[options["save_state_policy"]])
        self._refresh_controls(options["emulator_path"])
        if self.settings_dialog:
            self._set_settings_game(game_id)

    def _refresh_controls(self, executable):
        try:
            snapshot = EmulatorSettingsService(executable).inspect()
            self.page.set_controls({key: key_label(value) for key, value in snapshot.controls.items()}, snapshot.source)
        except (OSError, ValueError) as exc:
            self.page.set_controls({}, "Mapping réel : Non disponible")
            self.page.controls_source.setToolTip(str(exc))

    def _tracking_changed(self, state):
        if self.service.state.running and state.profile_id != self.service.state.profile_id:
            from app.services.tracking_service import TrackingState
            self.page.set_tracking_state(TrackingState(status="mismatch", message="La passerelle suit un autre profil que la session Mode Jeu."))
            return
        self.page.set_tracking_state(state)
        marker = (state.profile_id, state.revision)
        if state.profile_id and marker != self._last_profile_revision:
            self._last_profile_revision = marker
            try:
                profile = self.profiles.load(state.profile_id)
                with QSignalBlocker(self.page.profile_combo):
                    self.page.profile_combo.setCurrentIndex(max(0, self.page.profile_combo.findData(profile.id)))
                self.page.set_profile(profile)
            except (OSError, ValueError):
                pass  # Le service de suivi présente déjà l'erreur ; ne pas changer de profil.
        elif state.profile_id is None:
            with QSignalBlocker(self.page.profile_combo):
                self.page.profile_combo.setCurrentIndex(0)
            self.page.set_profile(None)

    def launch_game(self, game_id):
        if self.play_runner.is_busy:
            return
        if self._setup_service is None:
            from app.services.auto_setup_service import AutoSetupService
            self._setup_service = AutoSetupService(self.base_dir, self._legacy_config)
        if self._setup_service.is_configured(game_id):
            self._preparing_game = game_id
            self.page.status_label.setText("Vérification de votre installation avant le lancement…")
            self.play_runner.start(lambda: self._setup_service.prepare_play(game_id))
            return
        self._launch_process(game_id)

    def _play_busy(self, busy):
        if busy:
            self.page.launch_button.setEnabled(False)
            self.page.game_combo.setEnabled(False)
            self.page.profile_combo.setEnabled(False)
        else:
            self.page.set_run_state(self.service.state)

    def _play_prepared(self, result):
        health = result.get("health", {})
        if not health.get("ready"):
            self.page.status_label.setText("Installation à vérifier : " + "\n".join(health.get("issues", [])))
            self.installation_requested.emit()
            return
        self.service.reload_preferences()
        self._launch_process(self._preparing_game, prepare_lua=True)

    def _play_failed(self, message):
        self.page.status_label.setText("Préparation impossible : " + message + " · Ouvrez Installation & diagnostic.")

    def reconnect_lua(self):
        game_id = self.page.game_combo.currentData()
        self.controller.start(game_id, self.service.config["launch_profiles"][game_id]["rom_path"])
        self.bridge_requested.emit()

    def stop_lua_for_change(self):
        answer = QMessageBox.question(self, "Arrêter la session Lua ?",
            "L'ancienne session Lua sera arrêtée. DeSmuME restera ouvert : fermez sa fenêtre avant de lancer un autre jeu. Continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.stop()

    def _launch_process(self, game_id, *, prepare_lua=False):
        try:
            profile_id = self.page.profile_combo.currentData()
            # Le choix visible est l'association explicite du lancement suivant.
            self.service.save_launch_profile(game_id, {"challenge_profile_id": profile_id})
            process = self.service.launch(game_id, profile_id)
        except (OSError, ValueError) as exc:
            self.page.status_label.setText(str(exc))
            QMessageBox.warning(self, "Lancement impossible", str(exc))
            return
        self.process_launched.emit(process)
        if prepare_lua:
            self.controller.start(game_id, self.service.config["launch_profiles"][game_id]["rom_path"])
            self.bridge_requested.emit()
        self.page.set_run_state(self.service.state)
        self._arrange_pending = self.service.config["interface"]["auto_arrange"]
        self._arrange_attempts = 0
        if self.service.config["launch_profiles"][game_id]["game_mode"]:
            self.showNormal() if not self.isFullScreen() else self.showFullScreen()
            self.raise_()
        else:
            # La fenêtre est masquée ; le suivi et les backups opt-in continuent.
            self.hide()

    def request_speed(self, value):
        try:
            self.page.set_run_state(self.service.request_speed(value))
        except (OSError, ValueError) as exc:
            self.page.status_label.setText(str(exc))

    def backup_now(self):
        try:
            self.service.backup_now(self.page.game_combo.currentData())
            self.page.status_label.setText("Backup manuel créé et vérifié.")
            if self.settings_dialog:
                self.save_settings.refresh()
        except (OSError, ValueError) as exc:
            self.page.status_label.setText("Backup non créé : " + str(exc))

    def refresh_run(self):
        if self.play_runner.is_busy:
            return
        try:
            state = self.service.tick()
            self.page.set_run_state(state)
            if self.settings_dialog:
                self.save_settings.set_emulator_running(state.running)
            if self._arrange_pending and state.running:
                self._arrange_attempts += 1
                if state.window_title or self._arrange_attempts >= 6:
                    self._arrange_pending = False
                    self.arrange_windows()
        except (OSError, ValueError) as exc:
            self.page.status_label.setText(str(exc))

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.page.fullscreen_button.setText("Plein écran")
        else:
            self.showFullScreen()
            self.page.fullscreen_button.setText("Quitter le plein écran")

    def arrange_windows(self):
        name = self.service.config["interface"]["monitor_name"]
        screens = [screen for screen in QApplication.screens() if screen.name() == name]
        if not name or len(screens) != 1:
            self.page.status_label.setText("Choisissez l'écran dans Interface en jeu avant d'organiser les fenêtres.")
            self.open_settings("interface")
            return
        if not self.service.state.running:
            self.page.status_label.setText("Lancez DeSmuME depuis ce Mode Jeu avant d'organiser sa fenêtre.")
            return
        screen = screens[0]
        if screen.devicePixelRatio() != 1:
            self.page.status_label.setText("Organisation indisponible avec cette mise à l'échelle Windows. Positionnez DeSmuME manuellement ; le Mode Jeu reste utilisable.")
            return
        if self.windowHandle():
            self.windowHandle().setScreen(screen)
        self.setGeometry(screen.availableGeometry())
        QApplication.processEvents()
        point = self.page.center.mapToGlobal(QPoint(12, 90))
        rect = (point.x(), point.y(), max(200, self.page.center.width() - 24), max(240, self.page.center.height() - 200))
        try:
            self.service.arrange(rect)
            self.page.status_label.setText("Fenêtre DeSmuME externe positionnée. Ses commandes restent gérées par l'émulateur.")
        except (OSError, ValueError) as exc:
            self.page.status_label.setText(str(exc))

    def set_shortcuts(self, values):
        for shortcut in self._shortcuts.values():
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._shortcuts = {}
        actions = {"speed_x1": lambda: self.request_speed("x1"), "speed_x2": lambda: self.request_speed("x2"),
                   "speed_x4": lambda: self.request_speed("x4"), "speed_max": lambda: self.request_speed("MAX"),
                   "fullscreen": self.toggle_fullscreen, "game_mode": self.show,
                   "manual_backup": self.backup_now, "next_panel": self.page.next_panel,
                   "toggle_panels": self.page.toggle_panels}
        for key, sequence in values.items():
            if sequence and key in actions:
                shortcut = QShortcut(QKeySequence(sequence), self)
                shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
                shortcut.activated.connect(actions[key])
                self._shortcuts[key] = shortcut
        self.page.fullscreen_button.setToolTip("Plein écran de l'application" +
            (f" · {values['fullscreen']}" if values.get("fullscreen") else " · raccourci configurable dans Contrôles"))

    def _create_settings(self):
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("Réglages du Mode Jeu")
        self.settings_dialog.resize(930, 710)
        self.settings_dialog.setMinimumSize(760, 580)
        layout = QVBoxLayout(self.settings_dialog)
        from PySide6.QtWidgets import QPushButton
        self.installation_button = QPushButton("Installation & diagnostic")
        self.installation_button.clicked.connect(self.installation_requested)
        layout.addWidget(self.installation_button)
        self.settings_tabs = QTabWidget()
        layout.addWidget(self.settings_tabs)
        game_id = self.page.game_combo.currentData()
        options = self.service.config["launch_profiles"][game_id]
        adapter = EmulatorSettingsService(options["emulator_path"])
        self.launch_settings = LaunchProfilePage(self.catalog, self.service.config["launch_profiles"])
        self.launch_settings.set_profiles(self.profiles.list_profiles())
        self.controls_settings = ControlsPage(adapter, self.base_dir / "controls.local.json")
        self.controls_settings.set_app_shortcuts(self.service.config["shortcuts"])
        self.graphics_settings = GraphicsPage(adapter)
        self.save_settings = SaveManagerPage(SaveManagerService(Path(options["backup_directory"])), self.catalog.games.values())
        self.save_settings.set_running_probe(lambda: self.service.windows.running_executable(
            self.service.config["launch_profiles"][self._settings_game or game_id]["emulator_path"]))
        self.interface_settings = InterfaceInGamePage(self.service.config["interface"])
        self._tab_ids = {}
        for key, text, page in (("launch", "Lancement", self.launch_settings), ("controls", "Contrôles", self.controls_settings),
                                ("graphics", "Graphismes", self.graphics_settings), ("saves", "Sauvegardes", self.save_settings),
                                ("interface", "Interface en jeu", self.interface_settings)):
            self._tab_ids[key] = self.settings_tabs.addTab(page, text)
        self.launch_settings.settings_changed.connect(self._save_launch_settings)
        self.launch_settings.game_changed.connect(self._set_settings_game)
        self.save_settings.settings_changed.connect(self._save_launch_settings)
        self.save_settings.game_changed.connect(self._set_settings_game)
        self.controls_settings.settings_changed.connect(lambda _: self._refresh_controls(
            self.service.config["launch_profiles"][self._settings_game]["emulator_path"]))
        self.graphics_settings.settings_changed.connect(lambda _: self._refresh_controls(
            self.service.config["launch_profiles"][self._settings_game]["emulator_path"]))
        self.controls_settings.app_shortcuts_changed.connect(self._save_shortcuts)
        self.interface_settings.settings_changed.connect(self._save_interface)
        self._set_settings_game(game_id)

    def _set_settings_game(self, game_id):
        if not self.settings_dialog or self._settings_game == game_id:
            return
        self._settings_game = game_id
        options = self.service.config["launch_profiles"][game_id]
        self.launch_settings.set_context(game_id, self.service.config["launch_profiles"])
        self.controls_settings.set_executable(options["emulator_path"])
        self.graphics_settings.set_executable(options["emulator_path"])
        self.save_settings.set_context(game_id, options)
        self.save_settings.set_emulator_running(self.service.state.running)

    def open_settings(self, tab="interface"):
        if tab == "installation":
            self.installation_requested.emit()
            return
        if tab == "bridge":
            self.bridge_requested.emit()
            return
        if self.settings_dialog is None:
            self._create_settings()
        self.settings_tabs.setCurrentIndex(self._tab_ids.get("controls" if tab == "controls_reset" else tab, 0))
        if tab == "controls_reset":
            self.controls_settings.reset_controls()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _save_launch_settings(self, game_id, values):
        try:
            self.service.save_launch_profile(game_id, values)
            self._settings_game = None
            self._set_settings_game(game_id)
            self.launch_settings.feedback.setText("Profil de lancement enregistré sur cet ordinateur.")
            self.page.status_label.setText("Préférences de lancement enregistrées.")
            if game_id == self.page.game_combo.currentData():
                self._game_changed(game_id)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.settings_dialog, "Réglages non enregistrés", str(exc))

    def _save_interface(self, values):
        try:
            settings = self.service.save_interface(values)
            self.page.set_interface(settings)
            self.interface_settings.feedback.setText("Interface enregistrée et appliquée.")
        except (OSError, ValueError) as exc:
            self.interface_settings.feedback.setText(str(exc))

    def _save_shortcuts(self, values):
        try:
            saved = self.service.save_shortcuts(values)
            self.set_shortcuts(saved)
            self.shortcuts_changed.emit(saved)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.settings_dialog, "Raccourcis non enregistrés", str(exc))

    def showEvent(self, event):
        if hasattr(self, "timer"):
            self.timer.start()
        super().showEvent(event)

    def closeEvent(self, event):
        if self.play_runner.is_busy:
            event.ignore()
            self.page.status_label.setText("Attendez la fin de la préparation avant de fermer le Mode Jeu.")
            return
        self.timer.stop()
        self.service.stop_tracking()
        if self.settings_dialog:
            self.settings_dialog.close()
        super().closeEvent(event)
