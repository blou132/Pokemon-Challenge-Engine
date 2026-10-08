"""Fenêtre frontend indépendante ; DeSmuME conserve sa fenêtre et ses entrées."""

from pathlib import Path
from copy import deepcopy
from dataclasses import asdict

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
    run_action_requested = Signal(str, str, object)
    process_context_changed = Signal(bool, object)
    installation_changed = Signal()
    run_mismatch = Signal(object)

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
        self.persistent_run = None
        self._run_launch_options = None
        self._persistent_notice = ""
        self._pending_run_launch = None
        self._pending_reference_save = False
        self.requested_run_id = None
        self._run_guard = None
        self._launch_generation = 0
        self._lua_pipeline = None
        self._connection_session = None
        self._lua_message = ""
        from app.services.lua_autoload_service import LuaAutoLoadService
        self.autoload = LuaAutoLoadService(base_dir, running_probe=self.service.windows.running_executable)
        self.autoload_runner = SetupTaskRunner(self)
        self.autoload_runner.succeeded.connect(self._autoload_prepared)
        self.autoload_runner.failed.connect(self._autoload_failed)
        self.lua_timeout = QTimer(self)
        self.lua_timeout.setSingleShot(True)
        self.lua_timeout.setInterval(8000)
        self.lua_timeout.timeout.connect(self._lua_timed_out)
        self.service.backup_observer = self._record_backup
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
        self.page.run_action_requested.connect(self._quick_run_action)
        self.controller.state_changed.connect(self._bridge_state_changed)
        self.controller.prepared_for_request.connect(self._bridge_prepared)
        self.controller.preparation_failed.connect(self._bridge_failed)
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
        if self.persistent_run is not None:
            return
        if self.controller.state.status != "stopped" or self.service.state.running:
            self.page.set_profiles(self.profiles.list_profiles(), self.controller.tracking_state.profile_id)
            self.page.status_label.setText("Terminez la session et arrêtez la connexion Lua avant de changer de profil.")
            return
        self.controller.select_profile(profile_id)
        self.profile_selected.emit(profile_id)
        self._game_changed(self.page.game_combo.currentData(), select_associated=False)
        self.page.set_bridge_state(self.controller.state)

    def _game_changed(self, game_id, *, select_associated=True):
        if self.persistent_run is not None:
            self.page.set_persistent_run(self.persistent_run, self.page._autosave)
            self._refresh_controls(self.launch_options(self.persistent_run.game_id)["emulator_path"])
            return
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
            self.page.controls_source.setToolTip("")
        except (OSError, ValueError) as exc:
            self.page.set_controls({}, "Mapping réel : Non disponible")
            self.page.controls_source.setToolTip(str(exc))

    def _tracking_changed(self, state):
        if self.persistent_run is not None:
            return
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
        if self.launch_busy or self.service.state.running or not self.validate_requested_run():
            return
        self._launch_generation += 1
        self.page.set_session_phase("preparing", "Vérification de l'environnement et du support Lua…", busy=True)
        if self.persistent_run is not None:
            from app.services.run_launch_service import RunLaunchService
            self._preparing_game = self.persistent_run.game_id
            self.page.status_label.setText("Vérification de l'environnement lié à cette partie…")
            self._persistent_notice = ""
            run = deepcopy(self.persistent_run)
            self.play_runner.start(lambda: RunLaunchService(self.base_dir, self._legacy_config, setup=self._setup_service).prepare(run))
            return
        if self._setup_service is None:
            from app.services.auto_setup_service import AutoSetupService
            self._setup_service = AutoSetupService(self.base_dir, self._legacy_config)
        self._preparing_game = game_id
        self.page.status_label.setText("Recherche et vérification de ce jeu avant le lancement…")
        self.play_runner.start(lambda: self._prepare_local_game(game_id))

    def _prepare_local_game(self, game_id):
        report = self._setup_service.automatic_setup(game_id=game_id)
        state = report["game_states"][game_id]
        if state["status"] not in {"ready", "lua_required"}:
            return {"game_id": game_id, "health": {"ready": False, "launch_ready": False,
                                                     "issues": [state["message"]]}}
        return self._setup_service.prepare_play(game_id)

    @property
    def launch_busy(self):
        return (self.play_runner.is_busy or self.autoload_runner.is_busy or self._lua_pipeline is not None
                or self._pending_reference_save or self._pending_run_launch is not None)

    def set_run_guard(self, callback):
        self._run_guard = callback

    def validate_requested_run(self):
        if self.persistent_run is None and self.requested_run_id is None:
            return True
        valid = (self.persistent_run is not None and self.requested_run_id == self.persistent_run.run_id
                 and (self._run_guard is None or self._run_guard(self.requested_run_id)))
        if not valid:
            self.set_run_notice("La partie active ne correspond pas à celle demandée. Réessayez depuis Mes parties.")
            self.page.set_session_phase("error", self._persistent_notice)
            self.run_mismatch.emit(self.requested_run_id)
        return valid

    def bind_requested_run(self, run, autosave=None):
        if self.requested_run_id != run.run_id:
            self._launch_generation += 1
            self._lua_pipeline = None
            self._pending_run_launch = None
            self._pending_reference_save = False
            self._connection_session = None
            self.lua_timeout.stop()
            self._persistent_notice = ""
            self.page.set_session_phase("ready")
        self.requested_run_id = run.run_id
        self.set_persistent_run(run, autosave, requested_run_id=run.run_id)

    def _play_busy(self, busy):
        if busy:
            self.page.launch_button.setEnabled(False)
            self.page.game_combo.setEnabled(False)
            self.page.profile_combo.setEnabled(False)
        else:
            self.page.set_run_state(self.service.state)

    def _play_prepared(self, result):
        if not self.validate_requested_run():
            return
        health = result.get("health", {})
        if not health.get("ready") and not health.get("launch_ready"):
            self.page.status_label.setText("Installation à vérifier : " + "\n".join(health.get("issues", [])))
            if self.persistent_run is not None:
                self._persistent_notice = self.page.status_label.text()
            self.page.set_session_phase("error", self.page.status_label.text())
            self.installation_requested.emit()
            return
        if self.persistent_run is not None:
            if result.get("run_id") != self.persistent_run.run_id:
                self.page.status_label.setText("La partie a changé pendant la préparation ; relancez la vérification.")
                return
            self._run_launch_options = result["profile"]
            self._resolve_lua_choice(self._run_launch_options)
            snapshot = deepcopy(result["profile"])
            source = result.get("source", self.persistent_run.launch_profile.get("_source"))
            if source:
                snapshot["_source"] = deepcopy(source)
            self._pending_run_launch = {"snapshot": snapshot, "result": result}
            self.page.launch_button.setEnabled(False)
            self.run_action_requested.emit(self.persistent_run.run_id, "update_launch_reference",
                {"profile": snapshot, "rom_fingerprint": result["rom_fingerprint"]})
            return
        self.service.reload_preferences()
        options = deepcopy(self.launch_options(self._preparing_game))
        self._resolve_lua_choice(options)
        self.service.save_launch_profile(self._preparing_game, {"lua_connection": options.get("lua_connection", "ask")})
        self._launch_process(self._preparing_game, prepare_lua=True)

    def _play_failed(self, message):
        self.page.status_label.setText("Préparation impossible : " + message + " · Ouvrez Installation & diagnostic.")
        if self.persistent_run is not None:
            self._persistent_notice = self.page.status_label.text()
        self.page.set_session_phase("error", self.page.status_label.text())

    def reconnect_lua(self):
        if self.launch_busy or not self.validate_requested_run():
            return
        game_id = self.page.game_combo.currentData()
        self._begin_lua(game_id, reconnect=True)

    def stop_lua_for_change(self):
        answer = QMessageBox.question(self, "Arrêter la session Lua ?",
            "L'ancienne session Lua sera arrêtée. DeSmuME restera ouvert : fermez sa fenêtre avant de lancer un autre jeu. Continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.lua_timeout.stop()
            self.controller.stop()
            if self._lua_pipeline is not None:
                self._cancel_lua_pipeline()

    def _resolve_lua_choice(self, options):
        from app.services.emulator_capabilities import detect_capabilities
        choice = options.get("lua_connection", "ask")
        if choice == "manual" or not detect_capabilities(options["emulator_path"]).known_build:
            return
        try:
            consent = self.autoload.consent_status(options["emulator_path"])
            if consent is None or (choice == "auto" and consent is False):
                consent = self._ask_lua_consent()
                self.autoload.record_consent(options["emulator_path"], consent)
            options["lua_connection"] = "auto" if consent else "manual"
        except (OSError, ValueError) as exc:
            self._lua_message = "Mode manuel : " + str(exc)

    def _ask_lua_consent(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Connexion Lua automatique")
        dialog.setText("PCE peut configurer l'autoload Lua de DeSmuME afin que la connexion démarre automatiquement avec le jeu.")
        dialog.setInformativeText("Les deux réglages existants seront sauvegardés. Vos scripts personnels seront conservés.")
        activate = dialog.addButton("Activer", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton("Conserver le mode manuel", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        return dialog.clickedButton() is activate

    def _begin_lua(self, game_id, *, reconnect=False):
        if not self.validate_requested_run():
            return
        options = deepcopy(self.launch_options(game_id))
        if self.persistent_run is None and not reconnect:
            previous_choice = options.get("lua_connection", "ask")
            self._resolve_lua_choice(options)
            if options.get("lua_connection", "ask") != previous_choice:
                try:
                    self.service.save_launch_profile(game_id, {"lua_connection": options["lua_connection"]})
                except (OSError, ValueError) as exc:
                    self._play_failed(str(exc))
                    return
        self._launch_generation += 1
        self.lua_timeout.stop()
        self._connection_session = None
        self._lua_message = ""
        self._lua_pipeline = {"generation": self._launch_generation, "game_id": game_id,
            "run_id": self.requested_run_id, "options": options,
            "reconnect": reconnect, "request": None}
        self.page.set_session_phase("preparing", "Création d'une nouvelle session Lua…", busy=True)
        self._lua_pipeline["request"] = self.controller.start(game_id, self._lua_pipeline["options"]["rom_path"])

    def _pipeline_matches(self, pipeline):
        return (pipeline is not None and pipeline is self._lua_pipeline
                and pipeline["generation"] == self._launch_generation
                and pipeline["run_id"] == self.requested_run_id
                and pipeline["request"] == self.controller.request_id
                and self.validate_requested_run())

    def _bridge_prepared(self, request_id, script):
        pending = self._lua_pipeline
        if pending is None or request_id != pending["request"]:
            return
        if not self._pipeline_matches(pending):
            self._cancel_lua_pipeline()
            return
        path = Path(script)
        bridge = self.controller.bridge
        if path.parent != bridge.session_dir or path.parent.name != bridge.session_id or (path.parent / "stop").exists():
            self._bridge_failed(request_id, "Le script ne correspond pas à la nouvelle session Lua.")
            return
        self._connection_session = bridge.session_id
        pending["session_id"] = bridge.session_id
        options = pending["options"]
        self.page.set_session_phase("preparing", "Préparation de l'autoload Lua…", busy=True)
        def prepare():
            automatic = options.get("lua_connection", "ask") == "auto" and not pending["reconnect"]
            try:
                if not automatic and not pending["reconnect"]:
                    self.autoload.restore(options["emulator_path"])
                result = self.autoload.prepare(options["emulator_path"], options["rom_path"], path,
                    pending["session_id"], configure_ini=automatic)
                return {"pipeline": pending, "enabled": result.enabled, "message": result.message}
            except (OSError, ValueError) as exc:
                return {"pipeline": pending, "enabled": False, "message": "Mode manuel : " + str(exc)}
        self.autoload_runner.start(prepare)

    def _autoload_prepared(self, result):
        pending = result["pipeline"]
        if pending is not self._lua_pipeline:
            return
        if not self._pipeline_matches(pending):
            self._cancel_lua_pipeline()
            return
        if pending.get("session_id") is not None:
            bridge = self.controller.bridge
            if (bridge.session_id != pending["session_id"] or bridge.session_dir is None
                    or (bridge.session_dir / "stop").exists()):
                self._cancel_lua_pipeline()
                return
        self._lua_pipeline = None
        self._lua_message = "" if result["enabled"] else result["message"] + (
            " Ouvrez le mode manuel et exécutez le nouveau connect.lua."
            " L'autoload ne s'exécute qu'au chargement de la ROM ; aucun réglage INI n'a été modifié dans le processus ouvert."
            if pending["reconnect"] else " Ouvrez le mode manuel pour charger le connect.lua de cette session.")
        if pending["reconnect"]:
            self.page.set_session_phase("waiting_script", self._lua_message)
            self.lua_timeout.start()
        else:
            self.page.set_session_phase("waiting_emulator", self._lua_message or "Autoload prêt. Lancement de DeSmuME…", busy=True)
            self._launch_process(pending["game_id"])

    def _autoload_failed(self, message):
        pending = self._lua_pipeline
        if pending is not None:
            self._autoload_prepared({"pipeline": pending, "enabled": False, "message": "Mode manuel : " + message})

    def _bridge_failed(self, request_id, message):
        pending = self._lua_pipeline
        if pending is not None and pending["request"] == request_id:
            self._autoload_prepared({"pipeline": pending, "enabled": False,
                                    "message": "Session Lua à réparer : " + message})

    def _cancel_lua_pipeline(self):
        self._lua_pipeline = None
        self.page.set_session_phase("error", "La session a changé pendant la préparation. Réessayez depuis Mes parties.")

    def _bridge_state_changed(self, state):
        if state.connected and self._connection_session is not None and state.session_id != self._connection_session:
            return
        self.page.set_bridge_state(state)
        if state.status == "stopped":
            self.lua_timeout.stop()
        if state.status == "stopped" and self._lua_pipeline is not None:
            self._cancel_lua_pipeline()
            return
        if self._lua_pipeline is not None or self.play_runner.is_busy or self._pending_run_launch is not None:
            return
        game = self.persistent_run.game_id if self.persistent_run else self.page.game_combo.currentData()
        matching = state.connected and state.game_id == game and (
            self._connection_session is None or state.session_id == self._connection_session)
        if matching:
            self.lua_timeout.stop()
            self._lua_message = ""
            self.page.set_session_phase("connected", "Connexion Lua confirmée par le jeu.")
        elif state.status in {"stopped", "disconnected", "error"}:
            self.page.set_session_phase("error" if state.status == "error" else "disconnected",
                state.last_error or ("Jeu lancé, suivi Lua indisponible." if self.service.state.running else ""))
        elif state.status == "waiting" and self.page._session_phase != "error":
            self.page.set_session_phase("waiting_script", self._lua_message or "En attente du script Lua de cette session…")

    def _lua_timed_out(self):
        state = self.controller.state
        game = self.persistent_run.game_id if self.persistent_run else self.page.game_combo.currentData()
        if (state.connected and state.game_id == game and self._connection_session is not None
                and state.session_id == self._connection_session):
            self._bridge_state_changed(state)
            return
        message = ("DeSmuME a démarré mais Lua ne s'est pas connecté." if self.service.state.running else
                   "Aucun heartbeat Lua reçu pour cette session.")
        self.page.set_session_phase("error", message + " " + self._lua_message)

    def _launch_process(self, game_id, *, prepare_lua=False):
        if not self.validate_requested_run():
            return
        if prepare_lua:
            self._begin_lua(game_id)
            return
        try:
            if self.persistent_run is not None:
                process = self.service.launch(game_id, options_override=self._run_launch_options)
            else:
                profile_id = self.page.profile_combo.currentData()
                # Le choix visible est l'association explicite du lancement suivant.
                self.service.save_launch_profile(game_id, {"challenge_profile_id": profile_id})
                process = self.service.launch(game_id, profile_id)
        except (OSError, ValueError) as exc:
            self.page.status_label.setText(str(exc))
            self.page.set_session_phase("error", str(exc))
            QMessageBox.warning(self, "Lancement impossible", str(exc))
            return
        self.process_launched.emit(process)
        self._persistent_notice = ""
        self.process_context_changed.emit(True, game_id)
        self.page.set_run_state(self.service.state)
        self.page.set_session_phase("waiting_script", self._lua_message or "DeSmuME a démarré. Attente du heartbeat Lua…")
        self.lua_timeout.start()
        self._arrange_pending = self.service.config["interface"]["auto_arrange"]
        self._arrange_attempts = 0
        if self.launch_options(game_id)["game_mode"]:
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
            if self.persistent_run is not None and not self.service.state.running:
                self.service._backup(self.launch_options(self.persistent_run.game_id), "manual")
            else:
                self.service.backup_now(self.page.game_combo.currentData())
            self.page.status_label.setText("Backup manuel créé et vérifié.")
            if self.settings_dialog:
                self.save_settings.refresh()
        except (OSError, ValueError) as exc:
            self.page.status_label.setText("Backup non créé : " + str(exc))

    def refresh_run(self):
        if self.play_runner.is_busy or self.autoload_runner.is_busy:
            return
        try:
            state = self.service.tick()
            self.process_context_changed.emit(state.running, state.game_id)
            self.page.set_run_state(state)
            if self.launch_busy:
                self.page.launch_button.setEnabled(False)
            if self._persistent_notice:
                self.page.status_label.setText(self._persistent_notice)
            if self.settings_dialog:
                self.save_settings.set_emulator_running(state.running)
            if self._arrange_pending and state.running:
                self._arrange_attempts += 1
                if state.window_title or self._arrange_attempts >= 6:
                    self._arrange_pending = False
                    self.arrange_windows()
        except (OSError, ValueError) as exc:
            self.page.status_label.setText(str(exc))

    def launch_options(self, game_id):
        if self.persistent_run is not None:
            return self._run_launch_options or {key: value for key, value in self.persistent_run.launch_profile.items()
                                                if not key.startswith("_")}
        return self.service.config["launch_profiles"][game_id]

    def set_run_notice(self, message):
        self._persistent_notice = message
        self.page.status_label.setText(message)

    def run_action_saved(self, run_id, action, run):
        if (self.persistent_run is None or run_id != self.persistent_run.run_id or run_id != self.requested_run_id
                or action != "update_launch_reference" or not self.validate_requested_run()):
            return
        self._pending_reference_save = False
        pending = self._pending_run_launch
        if pending is not None:
            if run.launch_profile != pending["snapshot"] or run.rom_fingerprint != pending["result"]["rom_fingerprint"]:
                return
            self._pending_run_launch = None
            self._run_launch_options = pending["result"]["profile"]
            self.set_persistent_run(run, self.page._autosave)
            self._run_launch_options = pending["result"]["profile"]
            self._launch_process(run.game_id, prepare_lua=True)
        else:
            self.set_persistent_run(run, self.page._autosave)
            self.page.launch_button.setEnabled(not self.service.state.running)

    def run_action_failed(self, message):
        if self._pending_run_launch is not None or self._pending_reference_save:
            self._pending_run_launch = None
            self._pending_reference_save = False
            self._run_launch_options = None
            self.set_run_notice("Références de partie non enregistrées ; lancement annulé : " + message)
            self.page.set_session_phase("error", self._persistent_notice)
            self.page.launch_button.setEnabled(not self.service.state.running)

    def set_persistent_run(self, run, autosave=None, *, requested_run_id=None):
        expected = requested_run_id or self.requested_run_id or run.run_id
        if run.run_id != expected or (self.requested_run_id is not None and expected != self.requested_run_id):
            return False
        self.requested_run_id = expected
        changed = self.persistent_run is None or self.persistent_run.run_id != run.run_id
        environment_changed = self.persistent_run is not None and self.persistent_run.launch_profile != run.launch_profile
        self.persistent_run = deepcopy(run)
        if changed:
            self._run_launch_options = None
            if self.settings_dialog:
                self.settings_dialog.close()
                self.settings_dialog.deleteLater()
                self.settings_dialog = None
                self._settings_game = None
        if environment_changed:
            self._run_launch_options = None
            self._settings_game = None
            self._set_settings_game(run.game_id)
        self.page.set_persistent_run(run, autosave)
        if changed or environment_changed:
            self._refresh_controls(self.launch_options(run.game_id)["emulator_path"])
        return True

    def _record_backup(self, record):
        if self.persistent_run is not None:
            self.run_action_requested.emit(self.persistent_run.run_id, "record_backup", {"payload": asdict(record)})

    def _quick_run_action(self, action):
        run = self.persistent_run
        if run is None:
            return
        from app.ui.run_dialogs import prompt_run_action
        if action in {"badge_increment", "badge_decrement"}:
            if run.badges is None:
                payload = prompt_run_action(self, self.catalog, run, "set_badges")
                action = "set_badges"
            else:
                payload = {"delta": 1 if action == "badge_increment" else -1}
                action = "adjust_badges"
        else:
            payload = prompt_run_action(self, self.catalog, run, action)
        if payload is not None:
            self.run_action_requested.emit(run.run_id, action, payload)

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
        options = self.launch_options(game_id)
        adapter = EmulatorSettingsService(options["emulator_path"])
        self.launch_settings = LaunchProfilePage(self.catalog, self._settings_profiles())
        self.launch_settings.set_profiles(self.profiles.list_profiles())
        self.controls_settings = ControlsPage(adapter, self.base_dir / "controls.local.json")
        self.controls_settings.set_app_shortcuts(self.service.config["shortcuts"])
        self.graphics_settings = GraphicsPage(adapter)
        self.save_settings = SaveManagerPage(SaveManagerService(Path(options["backup_directory"])), self.catalog.games.values())
        self.save_settings.set_running_probe(lambda: self.service.windows.running_executable(
            self.launch_options(self._settings_game or game_id)["emulator_path"]))
        self.save_settings.backup_created.connect(self._record_backup)
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
            self.launch_options(self._settings_game)["emulator_path"]))
        self.graphics_settings.settings_changed.connect(lambda _: self._refresh_controls(
            self.launch_options(self._settings_game)["emulator_path"]))
        self.controls_settings.app_shortcuts_changed.connect(self._save_shortcuts)
        self.interface_settings.settings_changed.connect(self._save_interface)
        self._set_settings_game(game_id)
        if self.persistent_run is not None:
            self.launch_settings.game_combo.setEnabled(False)
            self.save_settings.game_combo.setEnabled(False)

    def _settings_profiles(self):
        profiles = deepcopy(self.service.config["launch_profiles"])
        if self.persistent_run is not None:
            profiles[self.persistent_run.game_id] = self.launch_options(self.persistent_run.game_id)
        return profiles

    def _set_settings_game(self, game_id):
        if not self.settings_dialog or self._settings_game == game_id:
            return
        self._settings_game = game_id
        options = self.launch_options(game_id)
        self.launch_settings.set_context(game_id, self._settings_profiles())
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
            if self.persistent_run is not None:
                if self.service.state.running or self.controller.state.status != "stopped":
                    raise ValueError("Fermez DeSmuME et arrêtez Lua avant de modifier l'environnement de cette partie.")
                from app.services.game_mode_config import validate_config
                snapshot = deepcopy(self.persistent_run.launch_profile)
                source = snapshot.pop("_source", None)
                old_rom = snapshot.get("rom_path")
                snapshot.update(values)
                snapshot["challenge_profile_id"] = None
                snapshot = validate_config({"launch_profiles": {game_id: snapshot}}, self._legacy_config,
                                           self.base_dir)["launch_profiles"][game_id]
                if source and snapshot["rom_path"] == old_rom:
                    snapshot["_source"] = source
                self._pending_reference_save = True
                self.page.launch_button.setEnabled(False)
                self.run_action_requested.emit(self.persistent_run.run_id, "update_launch_reference", {"profile": snapshot})
                self._run_launch_options = None
                self.launch_settings.feedback.setText("Enregistrement des références de cette partie…")
                return
            self.service.save_launch_profile(game_id, values)
            self._settings_game = None
            self._set_settings_game(game_id)
            self.launch_settings.feedback.setText("Profil de lancement enregistré sur cet ordinateur.")
            self.page.status_label.setText("Préférences de lancement enregistrées.")
            if game_id == self.page.game_combo.currentData():
                self._game_changed(game_id)
            self.installation_changed.emit()
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
            self._refresh_controls(self.launch_options(self.page.game_combo.currentData())["emulator_path"])
        super().showEvent(event)

    def shutdown_tracking(self):
        self.timer.stop()
        self.lua_timeout.stop()
        self.service.stop_tracking()
        self.process_context_changed.emit(False, self.service.state.game_id)

    def closeEvent(self, event):
        if self.launch_busy:
            event.ignore()
            self.page.status_label.setText("Attendez la fin de la préparation et de l'enregistrement avant de fermer le Mode Jeu.")
            return
        # Closing this view does not end a persistent run while PCE and its
        # owned emulator remain alive. The main window ends tracking on exit.
        if self.persistent_run is None:
            self.shutdown_tracking()
        if self.settings_dialog:
            self.settings_dialog.close()
        super().closeEvent(event)
