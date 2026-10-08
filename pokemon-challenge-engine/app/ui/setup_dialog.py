"""État de l'installation automatique et choix de secours explicites."""

import json
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QTabWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from app.ui.setup_tasks import SetupTaskRunner
from app.ui.widgets.common import INSTALLATION_LABELS
from app.services.auto_setup_service import GAME_LABELS


def _text(value):
    widget = QLabel(value)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


class InstallationDialog(QDialog):
    configuration_ready = Signal(str)
    play_requested = Signal(str)
    detection_completed = Signal(object)

    def __init__(self, service, parent=None, *, first_run=False, active_session=None):
        super().__init__(parent)
        self.service = service
        self.first_run = first_run
        self.active_session = active_session or (lambda: "")
        self.snapshot = {}
        self._operation = ""
        self._last_ready_game = None
        self._play_after_complete = None
        self._overrides = {"retrobat_path": "", "emulator_path": "", "rom_path": ""}
        self._started = False
        self._displaying_snapshot = False
        self.setWindowTitle("Installation & diagnostic · Pokemon Challenge Engine")
        self.resize(980, 720)
        self.setMinimumSize(760, 560)
        self.setObjectName("page")
        self.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #303b52; background: #0d111b; }
            QTabBar::tab { background: #1a2232; color: #a8b3ca; padding: 10px 16px; }
            QTabBar::tab:selected { background: #32304f; color: #e4dfff; }
            QToolButton { background: #252e43; color: #e9ecf5; border: 1px solid #38435e;
                          border-radius: 6px; padding: 7px 10px; }
            QToolButton:hover { background: #303c56; }
            QPlainTextEdit { background: #101724; color: #e9ecf5; border: 1px solid #35415a;
                             border-radius: 6px; padding: 7px; }
        """)
        self.runner = SetupTaskRunner(self)
        self.runner.succeeded.connect(self._completed)
        self.runner.failed.connect(self._failed)
        self.runner.busy_changed.connect(self._busy_changed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        title = _text("Bienvenue dans Pokemon Challenge Engine" if first_run else "Installation & diagnostic")
        title.setObjectName("title")
        layout.addWidget(title)
        layout.addWidget(_text("Votre installation et vos jeux locaux sont détectés automatiquement. Les originaux restent à leur place."))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_installation()
        self._build_storage()
        self.tabs.currentChanged.connect(self._tab_changed)
        self.status_label = _text("Recherche automatique de votre installation…")
        self.status_label.setObjectName("subtitle")
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(5)
        self.progress.hide()
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        self.continue_button = QPushButton("Continuer" if first_run else "Fermer")
        self.continue_button.clicked.connect(self._continue)
        actions.addWidget(self.continue_button)
        actions.addStretch()
        self.prepare_button = QPushButton("Préparer et enregistrer")
        self.prepare_button.clicked.connect(self.prepare_selected)
        self.repair_button = QPushButton("Installer automatiquement le support Lua")
        self.repair_button.clicked.connect(self.repair_selected)
        self.play_button = QPushButton("Jouer")
        self.play_button.setObjectName("primary")
        self.play_button.clicked.connect(self._play)
        actions.addWidget(self.prepare_button)
        actions.addWidget(self.repair_button)
        actions.addWidget(self.play_button)
        layout.addLayout(actions)
        self._refresh_actions()

    def _build_installation(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("page")
        scroll.setWidget(body)
        content = QVBoxLayout(body)
        content.setContentsMargins(16, 18, 16, 18)
        row = QHBoxLayout()
        self.scan_button = QPushButton("Relancer la recherche")
        self.scan_button.clicked.connect(lambda: self.scan(force=True))
        row.addWidget(self.scan_button)
        row.addStretch()
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Choix manuels · Avancé")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        row.addWidget(self.advanced_toggle)
        content.addLayout(row)
        self.manual_controls = QWidget()
        manual_row = QHBoxLayout(self.manual_controls)
        manual_row.setContentsMargins(0, 0, 0, 0)
        self.folder_button = QPushButton("Autre dossier…")
        self.folder_button.clicked.connect(self._choose_folder)
        manual_row.addWidget(self.folder_button)
        self.emulator_button = QPushButton("Choisir DeSmuME…")
        self.emulator_button.clicked.connect(self._choose_emulator)
        manual_row.addWidget(self.emulator_button)
        self.rom_button = QPushButton("Ajouter un jeu…")
        self.rom_button.clicked.connect(self._choose_rom)
        manual_row.addWidget(self.rom_button)
        self.manual_controls.hide()
        content.addWidget(self.manual_controls)
        form = QFormLayout()
        self.choice_form = form
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.installation_combo = QComboBox()
        self.emulator_combo = QComboBox()
        self.game_combo = QComboBox()
        self.save_combo = QComboBox()
        for title, combo in (("Installation", self.installation_combo), ("Émulateur", self.emulator_combo),
                             ("Jeu", self.game_combo), ("Sauvegarde", self.save_combo)):
            combo.setMinimumWidth(0)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(20)
            form.addRow(title, combo)
        self.installation_combo.currentIndexChanged.connect(self._installation_changed)
        self.emulator_combo.currentIndexChanged.connect(self._emulator_changed)
        self.game_combo.currentIndexChanged.connect(self._game_changed)
        self.save_combo.currentIndexChanged.connect(self._selection_changed)
        content.addLayout(form)
        self.summary = {}
        summary = QFormLayout()
        for key, title in (("retrobat", "RetroBat"), ("emulator", "DeSmuME"), ("lua", "Support Lua"),
                           ("game", "Jeu sélectionné"), ("save", "Sauvegarde"), ("ini", "Configuration DeSmuME")):
            widget = _text("Recherche non effectuée")
            self.summary[key] = widget
            summary.addRow(title, widget)
        content.addLayout(summary)
        self.game_states = {}
        for game_id, label in GAME_LABELS.items():
            widget = _text(f"{label} · Recherche en cours…")
            self.game_states[game_id] = widget
            content.addWidget(widget)
        self.notice = _text("En cas de plusieurs installations, jeux ou sauvegardes, choisissez celui que vous souhaitez utiliser.")
        self.notice.setObjectName("muted")
        content.addWidget(self.notice)
        self.details_toggle = QToolButton()
        self.details_toggle.setText("Détails techniques")
        self.details_toggle.setCheckable(True)
        self.details_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.details_toggle.toggled.connect(self._toggle_details)
        content.addWidget(self.details_toggle)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(190)
        self.details.hide()
        content.addWidget(self.details)
        content.addStretch()
        self.tabs.addTab(scroll, "Installation")

    def _build_storage(self):
        self.storage_page = QWidget()
        self.storage_page.setObjectName("page")
        layout = QVBoxLayout(self.storage_page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(_text("Stockage local PCE"))
        layout.addWidget(_text("Les nettoyages concernent uniquement les caches et anciennes sessions gérés par PCE. Les originaux, profils, sauvegardes et backups sont conservés."))
        self.storage_label = _text("Ouvrez cet onglet pour mesurer le stockage.")
        layout.addWidget(self.storage_label)
        self.storage_buttons = {}
        for kind, title in (("extracted_roms", "Nettoyer les ROM extraites"), ("downloads", "Nettoyer le cache de téléchargement"),
                             ("sessions", "Nettoyer les anciennes sessions Lua")):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, value=kind: self.cleanup(value))
            layout.addWidget(button)
            self.storage_buttons[kind] = button
        layout.addStretch()
        self.tabs.addTab(self.storage_page, "Stockage local PCE")

    @property
    def is_busy(self):
        return self.runner.is_busy

    def start(self):
        if not self._started:
            self._started = True
            self.scan()

    def set_detection_state(self, report):
        """Réutilise le résultat du démarrage sans créer un second worker."""
        self._started = True
        self._display_snapshot(report)

    def _run(self, operation, action, message):
        if self.is_busy:
            return
        self._operation = operation
        self.status_label.setText(message)
        self.runner.start(action)

    def scan(self, *, force=False):
        options = dict(self._overrides)
        self._last_ready_game = None
        if any(options.values()):
            self._run("manual_scan", lambda: self.service.scan(**options), "Vérification de votre choix local…")
        else:
            self._run("scan", lambda: self.service.automatic_setup(force=force), "Recherche de votre installation en cours…")

    def _choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Choisir le dossier RetroBat")
        if path:
            self._overrides["retrobat_path"] = path
            self.scan()

    def _choose_emulator(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choisir DeSmuME", "", "Exécutables Windows (*.exe)")
        if path:
            self._overrides["emulator_path"] = path
            self.scan()

    def _choose_rom(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choisir un jeu local", "", "Jeux Nintendo DS (*.nds *.zip)")
        if path:
            self._overrides["rom_path"] = path
            self.scan()

    @staticmethod
    def _fill(combo, values, placeholder, current=None):
        with QSignalBlocker(combo):
            combo.clear()
            combo.addItem(placeholder, None)
            for text, value in values:
                combo.addItem(text, value)
            index = combo.findData(current) if current is not None else -1
            combo.setCurrentIndex(index if index > 0 else 1 if len(values) == 1 else 0)

    def _display_snapshot(self, snapshot):
        self._displaying_snapshot = True
        self.snapshot = snapshot
        def path_choice(items, key, requested):
            # QFileDialog uses forward slashes on Windows; discovery returns
            # native paths. An explicit choice must win over the old selection.
            return next((item[key] for item in items if requested and Path(item[key]) == Path(requested)), None)

        installations = snapshot.get("installations", [])
        emulators = snapshot.get("emulators", [])
        self._fill(self.installation_combo, [(item["root"], item["root"]) for item in snapshot.get("installations", [])],
                   "Choisir une installation…", path_choice(installations, "root", self._overrides["retrobat_path"] or self.installation_combo.currentData()))
        states = snapshot.get("game_states", {})
        selected_candidate = self._candidate()
        selected_game = selected_candidate.get("game_id") if selected_candidate else None
        state = states.get(selected_game, {})
        if not state:
            state = next((item for item in states.values() if item.get("status") == "ready"), {})
        self._fill(self.emulator_combo, [(f"DeSmuME {item.get('version') or ''} · {item.get('architecture') or 'architecture non identifiée'} · {Path(item['path']).parent.name}", item["path"])
                   for item in emulators], "Choisir un émulateur…",
                   path_choice(emulators, "path", self._overrides["emulator_path"] or state.get("emulator_path") or self.emulator_combo.currentData()))
        if self._overrides["emulator_path"] and not path_choice(emulators, "path", self._overrides["emulator_path"]):
            with QSignalBlocker(self.emulator_combo):
                self.emulator_combo.setCurrentIndex(0)
        games = snapshot.get("games", [])
        explicit_games = [item for item in games if self._overrides["rom_path"] and
                          Path(item["source_path"]) == Path(self._overrides["rom_path"])]
        selected_id = (explicit_games[0]["id"] if len(explicit_games) == 1 and not explicit_games[0].get("requires_choice")
                       else self.game_combo.currentData() or state.get("candidate_id"))
        self._fill(self.game_combo, [(f"{item['label']} · {'archive locale' if item.get('source_kind') == 'zip' else 'fichier local'}" +
                    (f" · {Path(item.get('archive_member') or item['source_path']).name}" if len(games) > 1 else ""), item["id"])
                   for item in games], "Choisir un jeu…", selected_id)
        if len(games) == 1 and games[0].get("requires_choice") and not state.get("candidate_id"):
            with QSignalBlocker(self.game_combo):
                self.game_combo.setCurrentIndex(0)
        self._game_changed()
        self._displaying_snapshot = False
        self.details.setPlainText(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))
        ready = any(item.get("status") == "ready" for item in states.values())
        self.status_label.setText("Installation PCE prête. Choisissez votre partie et jouez." if ready else
                                 "Recherche terminée. Les éléments à compléter sont indiqués ci-dessus.")
        self.notice.setText("\n".join(snapshot.get("warnings", [])) or
                           "L'absence des autres jeux ne bloque pas celui que vous possédez. Aucun fichier original n'est déplacé.")
        for game_id, widget in self.game_states.items():
            item = states.get(game_id, {})
            status = item.get("status")
            found = any(game.get("game_id") == game_id for game in games)
            message = item.get("message", "")
            if status == "not_found" or not status and not found:
                message = f"Veuillez ajouter {GAME_LABELS[game_id]} à votre bibliothèque RetroBat."
            widget.setText(f"{GAME_LABELS[game_id]} · {INSTALLATION_LABELS.get(status, 'Trouvé' if found else 'Jeu non trouvé')}" +
                           (f"\n{message}" if message and status != "ready" else ""))
        self._refresh_actions()

    def _candidate(self):
        return next((item for item in self.snapshot.get("games", []) if item["id"] == self.game_combo.currentData()), None)

    def _emulator(self):
        return next((item for item in self.snapshot.get("emulators", []) if item["path"] == self.emulator_combo.currentData()), None)

    def _installation_changed(self):
        value = self.installation_combo.currentData()
        if value:
            self._overrides["retrobat_path"] = value
            self.scan()
        else:
            self._selection_changed()

    def _emulator_changed(self):
        value = self.emulator_combo.currentData()
        if value:
            self._overrides["emulator_path"] = value
            self.scan()
        else:
            self._selection_changed()

    def _game_changed(self):
        candidate = self._candidate()
        state = self.snapshot.get("game_states", {}).get(candidate.get("game_id"), {}) if candidate else {}
        if state.get("emulator_path") and not self._overrides["emulator_path"]:
            with QSignalBlocker(self.emulator_combo):
                self.emulator_combo.setCurrentIndex(self.emulator_combo.findData(state["emulator_path"]))
        with QSignalBlocker(self.save_combo):
            self.save_combo.clear()
            saves = candidate.get("saves", []) if candidate else []
            self.save_combo.addItem("Choisir une sauvegarde…", None)
            self.save_combo.addItem("Continuer sans sauvegarde associée", "")
            for item in saves:
                self.save_combo.addItem(f"{Path(item['path']).name} · {item.get('size', 0) // 1024} Ko · {item.get('modified_at', '')}", item["path"])
                self.save_combo.setItemData(self.save_combo.count() - 1, item["path"], Qt.ItemDataRole.ToolTipRole)
            if "health" in state:
                proposed = state.get("save_path")
            else:
                proposed = candidate.get("proposed_save") if candidate and len(saves) == 1 else None
                if not proposed:
                    proposed = None
            index = self.save_combo.findData(proposed) if proposed is not None else -1
            self.save_combo.setCurrentIndex(index if index >= 1 else 1 if not saves else 0)
        self._selection_changed()

    def _selection_changed(self):
        self._last_ready_game = None
        emulator, candidate = self._emulator(), self._candidate()
        state = self.snapshot.get("game_states", {}).get(candidate.get("game_id"), {}) if candidate else {}
        selection_matches = bool(candidate and emulator and state.get("candidate_id") == candidate["id"] and
                                 state.get("emulator_path") == emulator["path"] and
                                 state.get("save_path", "") == self.save_combo.currentData())
        if state.get("status") == "ready" and selection_matches:
            self._last_ready_game = candidate["game_id"]
        self.summary["retrobat"].setText(str(self.installation_combo.currentData()) if self.installation_combo.currentData() else "Plusieurs installations · Choix nécessaire" if self.snapshot.get("installations") else "Non trouvé · Installation indépendante possible")
        self.summary["emulator"].setText(f"{emulator.get('version') or 'Détecté'} · {emulator.get('architecture') or 'Architecture à vérifier'}" if emulator else
                                       "Plusieurs installations · Choix nécessaire" if self.snapshot.get("emulators") else "Non trouvé · Choix manuel disponible dans Avancé")
        lua_status = emulator.get("lua_status") if emulator else None
        self.summary["lua"].setText("Prêt · Fichiers vérifiés ; connexion confirmée au lancement" if lua_status in {"ready", "installed", "verified"} else "Support Lua requis" if emulator else "En attente de DeSmuME")
        self.summary["ini"].setText("Détectée" if emulator and emulator.get("ini_path") else "Non détectée")
        self.summary["game"].setText("Prêt" if self._last_ready_game else state.get("message") or
                                   (candidate["label"] + " · Trouvé" if candidate else "Choisissez le jeu à utiliser" if self.snapshot.get("games") else "Jeu non trouvé · Ajoutez une copie locale à RetroBat"))
        self.summary["save"].setText(Path(self.save_combo.currentData()).name if self.save_combo.currentData() else
                                   "Plusieurs sauvegardes possibles · Choix nécessaire" if self.save_combo.currentData() is None else
                                   "Aucune sauvegarde associée" if candidate and candidate.get("saves") else "Aucune sauvegarde existante trouvée")
        self._refresh_actions()
        if not self._displaying_snapshot and not self._last_ready_game and candidate and emulator:
            self._prepare_if_resolved()

    def _prepare_if_resolved(self):
        """Un choix explicite résolu suffit ; aucune étape « Préparer » imposée."""
        try:
            selection = self.selection()
        except ValueError:
            return
        if not self.is_busy:
            self._run("prepare", lambda: self.service.prepare(selection), "Préparation du jeu local et vérification…")

    def selection(self):
        if not self._candidate() or not self._emulator():
            raise ValueError("Choisissez un jeu et un émulateur détectés.")
        if len(self.snapshot.get("installations", [])) > 1 and not self.installation_combo.currentData():
            raise ValueError("Choisissez l'installation RetroBat à utiliser.")
        if self.save_combo.currentData() is None:
            raise ValueError("Plusieurs sauvegardes sont possibles. Choisissez celle à associer ou continuez sans association.")
        return {"retrobat_root": self.installation_combo.currentData() or "", "emulator_path": self.emulator_combo.currentData(),
                "candidate_id": self.game_combo.currentData(), "save_path": self.save_combo.currentData()}

    def prepare_selected(self):
        try:
            selection = self.selection()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._run("prepare", lambda: self.service.prepare(selection), "Préparation du jeu local et vérification…")

    def repair_selected(self, *, replace_confirmed=False):
        try:
            selection = self.selection()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        answer = QMessageBox.question(self, "Installer le support Lua ?",
            "PCE préparera votre jeu dans son cache et installera le support Lua officiel à côté de DeSmuME. "
            "La source est l'archive épinglée du projet officiel TASEmulators/DeSmuME. "
            "Les ROM et sauvegardes originales ne seront pas modifiées. Continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        different = [item for item in self._emulator().get("dlls", [])
                     if item.get("status") not in {"verified", "missing"}]
        if different:
            listed = "\n".join(str(item.get("path") or item.get("name")) for item in different)
            answer = QMessageBox.question(self, "Remplacer les fichiers Lua existants ?",
                "Ces fichiers diffèrent de la version officielle vérifiée :\n\n" + listed +
                "\n\nPCE créera une copie de sauvegarde avant de les remplacer. Autorisez-vous explicitement ce remplacement ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            replace_confirmed = True
        self._run("repair", lambda: self.service.repair(selection, replace_confirmed=replace_confirmed), "Préparation et réparation du support Lua…")

    def _refresh_actions(self):
        available = bool(self._candidate() and self._emulator()) and not self.is_busy
        self.prepare_button.setEnabled(available)
        self.repair_button.setEnabled(available)
        self.play_button.setEnabled(bool(self._last_ready_game) and not self.is_busy)
        advanced = self.advanced_toggle.isChecked()
        self.prepare_button.setVisible(advanced)
        emulator = self._emulator()
        needs_lua = emulator and emulator.get("lua_status") not in {"ready", "installed", "verified"}
        self.repair_button.setVisible(bool(needs_lua) or advanced)
        for combo, needed in ((self.installation_combo, len(self.snapshot.get("installations", [])) > 1 and not self.installation_combo.currentData()),
                              (self.emulator_combo, len(self.snapshot.get("emulators", [])) > 1 and not self.emulator_combo.currentData()),
                              (self.game_combo, len(self.snapshot.get("games", [])) > 1 or
                               any(item.get("requires_choice") for item in self.snapshot.get("games", []))),
                              (self.save_combo, self.save_combo.count() > 2 and self.save_combo.currentData() is None)):
            self.choice_form.setRowVisible(combo, advanced or needed)

    def _toggle_advanced(self, visible):
        self.manual_controls.setVisible(visible)
        self._refresh_actions()

    def _busy_changed(self, busy):
        self.progress.setVisible(busy)
        for widget in (self.scan_button, self.folder_button, self.emulator_button, self.rom_button,
                       self.installation_combo, self.emulator_combo, self.game_combo, self.save_combo, self.continue_button):
            widget.setEnabled(not busy)
        for widget in self.storage_buttons.values():
            widget.setEnabled(not busy)
        self._refresh_actions()

    def _completed(self, result):
        if self._operation in {"scan", "manual_scan"}:
            manual = self._operation == "manual_scan"
            self._display_snapshot(result)
            if not manual:
                self.detection_completed.emit(result)
            else:
                self._prepare_if_resolved()
        elif self._operation in {"prepare", "repair"}:
            health = result.get("health", {})
            self._last_ready_game = result.get("game_id") if health.get("ready") else None
            self.details.appendPlainText("\nPréparation :\n" + json.dumps(result, ensure_ascii=False, indent=2, default=str))
            self.status_label.setText("Prêt à lancer. La connexion au jeu sera confirmée après réception des données." if health.get("ready") else
                                      "Préparation enregistrée. " + "\n".join(health.get("issues", []) or ["Une vérification reste nécessaire."]))
            self.notice.setText("\n".join(health.get("warnings", [])))
            self.summary["game"].setText("Prêt à lancer" if health.get("ready") else "Préparé · vérification nécessaire")
            lua = health.get("lua_status", {})
            if isinstance(lua, dict) and lua.get("status") in {"ready", "verified", "installed"}:
                self.summary["lua"].setText("Fichiers vérifiés · test en jeu requis")
            else:
                self.summary["lua"].setText("Réparation nécessaire" if lua else "Non vérifié")
            if result.get("game_id"):
                self.configuration_ready.emit(result["game_id"])
            self._refresh_actions()
            if health.get("ready"):
                self._overrides = {"retrobat_path": "", "emulator_path": "", "rom_path": ""}
                self.scan(force=True)
        elif self._operation == "storage":
            self.storage_label.setText("\n\n".join(f"{item['label']} : {item['bytes'] / (1024 * 1024):.1f} Mo · {item['count']} élément(s)" for item in result.get("items", [])) or "Aucun cache géré.")
            self.status_label.setText("Stockage local mesuré.")
        elif self._operation == "cleanup":
            self.details.appendPlainText("\nNettoyage :\n" + json.dumps(result, ensure_ascii=False, indent=2, default=str))
            self._run("storage", self.service.storage_summary, "Actualisation du stockage…")
        elif self._operation == "complete":
            if self._play_after_complete:
                self.play_requested.emit(self._play_after_complete)
                self._play_after_complete = None
            self.accept()

    def _failed(self, message):
        self._last_ready_game = None
        self._play_after_complete = None
        if self._operation in {"prepare", "repair"}:
            self.summary["game"].setText("Préparation non confirmée")
            self.summary["lua"].setText("À revérifier")
        self.status_label.setText("Opération non terminée : " + message)
        self.details.appendPlainText("\nErreur : " + message)
        self._refresh_actions()

    def _toggle_details(self, visible):
        self.details.setVisible(visible)
        self.details_toggle.setArrowType(Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow)

    def _tab_changed(self, index):
        if index == 1 and not self.is_busy:
            self._run("storage", self.service.storage_summary, "Mesure du stockage local…")

    def cleanup(self, kind):
        answer = QMessageBox.question(self, "Nettoyer les fichiers gérés ?",
            "Seuls les fichiers de cette catégorie créés et reconnus par PCE seront supprimés. "
            "Les originaux, profils, sauvegardes et backups restent conservés. Confirmer le nettoyage ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            session = self.active_session()
            self._run("cleanup", lambda: self.service.cleanup(kind, confirmed=True, active_session=session), "Nettoyage des fichiers gérés…")

    def _play(self):
        if self._last_ready_game:
            game_id = self._last_ready_game
            if self.first_run:
                self._play_after_complete = game_id
                self._run("complete", self.service.complete_first_run, "Enregistrement du premier démarrage…")
                return
            self.play_requested.emit(game_id)
            self.accept()

    def _continue(self):
        self._play_after_complete = None
        if self.first_run:
            self._run("complete", self.service.complete_first_run, "Enregistrement du premier démarrage…")
        else:
            self.accept()

    def reject(self):
        if self.is_busy:
            self.status_label.setText("L'opération se termine. Vous pourrez fermer cette fenêtre ensuite.")
            return
        super().reject()

    def closeEvent(self, event):
        if self.is_busy:
            event.ignore()
            self.status_label.setText("L'opération se termine. Vous pourrez fermer cette fenêtre ensuite.")
        else:
            super().closeEvent(event)
