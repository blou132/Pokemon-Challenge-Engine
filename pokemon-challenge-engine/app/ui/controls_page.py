"""Explicit keyboard import/export and local control profiles."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QInputDialog,
                              QKeySequenceEdit, QPushButton, QWidget)

from app.services.emulator_settings_service import (CONTROL_LABELS, DEFAULT_CONTROLS,
    DEFAULT_HOTKEYS, ControlProfileStore, EmulatorSettingsService, control_conflicts, key_label)
from app.ui.widgets.common import card, label, page_layout


APP_SHORTCUTS = {"speed_x1": "Vitesse x1", "speed_x2": "Vitesse x2", "speed_x4": "Vitesse x4",
                 "speed_max": "Vitesse MAX", "fullscreen": "Plein écran PCE", "game_mode": "Mode Jeu",
                 "manual_backup": "Backup manuel", "next_panel": "Changer de panneau",
                 "toggle_panels": "Afficher / masquer les panneaux"}
KEY_CODES = [0, 9, 13, 19, 27, 32, 34, 35, 37, 38, 39, 40, *range(48, 58),
             *range(65, 91), *range(112, 124), 160, 161, 162, 163, 164, 165, 187, 189]


class ControlsPage(QWidget):
    settings_changed = Signal(object)
    app_shortcuts_changed = Signal(dict)

    def __init__(self, service: EmulatorSettingsService, profiles_path: Path, parent=None):
        super().__init__(parent)
        self.service = service
        self.store = ControlProfileStore(profiles_path)
        self._loaded_hotkeys: dict[str, int] = {}
        self._all_hotkeys: dict[str, int] = {}
        layout = page_layout(self, "Contrôles", "Profils locaux et synchronisation explicite avec DeSmuME fermé.")
        self.status = label("Configurez le chemin DeSmuME dans les paramètres.", "subtitle")
        layout.addWidget(self.status)
        panel, body = card("Clavier Nintendo DS")
        form = QFormLayout()
        self.key_boxes = {}
        for key, title in CONTROL_LABELS.items():
            box = self._key_box()
            self.key_boxes[key] = box
            box.currentIndexChanged.connect(self._show_conflicts)
            form.addRow(title, box)
        body.addLayout(form)
        buttons = QHBoxLayout()
        self.import_button = QPushButton("Importer depuis DeSmuME")
        self.import_button.clicked.connect(self.refresh)
        reset = QPushButton("Réinitialiser le brouillon")
        reset.clicked.connect(self.reset_controls)
        self.export_button = QPushButton("Exporter vers DeSmuME")
        self.export_button.setToolTip("Sauvegarde le fichier INI avant modification. DeSmuME doit être fermé.")
        self.export_button.clicked.connect(self._export)
        for button in (self.import_button, reset, self.export_button):
            buttons.addWidget(button)
        body.addLayout(buttons)
        self.conflicts = label("", "warning")
        body.addWidget(self.conflicts)
        layout.addWidget(panel)
        panel, body = card("Profils de contrôles")
        row = QHBoxLayout()
        self.profile_box = QComboBox()
        load = QPushButton("Charger le brouillon")
        load.clicked.connect(self._load_profile)
        save = QPushButton("Enregistrer un profil")
        save.clicked.connect(self._save_profile)
        for widget in (self.profile_box, load, save):
            row.addWidget(widget)
        body.addLayout(row)
        body.addWidget(label("Manette : détection et remappage non disponibles. Les codes importés restent visibles ; configurez la manette dans DeSmuME."))
        layout.addWidget(panel)
        panel, body = card("Raccourcis DeSmuME")
        body.addWidget(label("Modification des raccourcis simples ci-dessous. Les combinaisons avec modificateur restent gérées par DeSmuME. Le maintien de FastForward accélère tant que la touche est pressée."))
        form = QFormLayout()
        self.hotkey_boxes = {}
        for key in DEFAULT_HOTKEYS:
            box = self._key_box()
            self.hotkey_boxes[key] = box
            box.currentIndexChanged.connect(self._show_conflicts)
            form.addRow(key, box)
        body.addLayout(form)
        layout.addWidget(panel)
        panel, body = card("Raccourcis de l'application")
        body.addWidget(label("Actifs quand PCE a le focus. Aucune touche globale n'est capturée dans DeSmuME."))
        form = QFormLayout()
        self.shortcut_edits = {}
        for key, title in APP_SHORTCUTS.items():
            edit = QKeySequenceEdit()
            edit.setMaximumSequenceLength(1)
            self.shortcut_edits[key] = edit
            form.addRow(title, edit)
        body.addLayout(form)
        apply = QPushButton("Enregistrer les raccourcis PCE")
        apply.clicked.connect(self._save_shortcuts)
        body.addWidget(apply)
        layout.addWidget(panel)
        layout.addStretch()
        self._refresh_profiles()
        self.refresh()

    @staticmethod
    def _key_box():
        box = QComboBox()
        for code in KEY_CODES:
            box.addItem(key_label(code), code)
        return box

    @staticmethod
    def _set_code(box, code):
        index = box.findData(code)
        if index < 0:
            box.addItem(key_label(code), code)
            index = box.count() - 1
        box.setCurrentIndex(index)

    def set_executable(self, path: str):
        self.service.set_executable(path)
        self.refresh()

    def controls(self) -> dict[str, int]:
        return {key: box.currentData() for key, box in self.key_boxes.items()}

    def _show_conflicts(self):
        if not hasattr(self, "conflicts"):
            return
        hotkeys = self._all_hotkeys | {key: box.currentData() for key, box in getattr(self, "hotkey_boxes", {}).items() if box.isEnabled()}
        problems = control_conflicts(self.controls(), hotkeys)
        self.conflicts.setText("Conflits : " + "; ".join(problems) if problems else "Aucun conflit dans les touches simples affichées.")

    def reset_controls(self):
        for key, code in DEFAULT_CONTROLS.items():
            self._set_code(self.key_boxes[key], code)
        self.status.setText("Brouillon réinitialisé aux touches DeSmuME documentées. Export nécessaire pour les appliquer.")

    def refresh(self):
        try:
            snapshot = self.service.inspect()
            known = snapshot.capabilities.known_build and bool(snapshot.controls)
            self.export_button.setEnabled(known)
            self.import_button.setEnabled(snapshot.capabilities.known_build)
            if not known:
                self.status.setText("Version DeSmuME non vérifiée : import et export indisponibles. Profils locaux disponibles.")
                self.reset_controls()
                self.status.setText("Version DeSmuME non vérifiée. Le brouillon affiche les valeurs documentées, pas une configuration détectée.")
                return
            for key, code in snapshot.controls.items():
                self._set_code(self.key_boxes[key], code)
            self._loaded_hotkeys = snapshot.hotkeys
            self._all_hotkeys = snapshot.hotkeys
            for key, box in self.hotkey_boxes.items():
                enabled = key in snapshot.hotkeys
                box.setEnabled(enabled)
                self._set_code(box, snapshot.hotkeys.get(key, 0))
                box.setToolTip("Combinaison avec modificateur : modification dans DeSmuME." if not enabled else "Code clavier simple.")
            self.status.setText(f"Importé depuis {snapshot.ini_path}. {snapshot.source}.")
            self._show_conflicts()
        except (ValueError, OSError) as exc:
            self.export_button.setEnabled(False)
            self.status.setText(str(exc))

    def _export(self):
        try:
            changed = {key: box.currentData() for key, box in self.hotkey_boxes.items()
                       if box.isEnabled() and box.currentData() != self._loaded_hotkeys.get(key)}
            change = self.service.apply(controls=self.controls(), hotkeys=changed or None)
            self.refresh()
            self.status.setText(f"Configuration enregistrée. Backup : {change.backup_path.name}. Relancez DeSmuME.")
            self.settings_changed.emit(change)
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def _refresh_profiles(self):
        self.profile_box.clear()
        try:
            self.profile_box.addItems(sorted(self.store.load()))
        except ValueError as exc:
            self.status.setText(str(exc))

    def _save_profile(self):
        name, ok = QInputDialog.getText(self, "Profil de contrôles", "Nom du profil")
        if ok:
            try:
                self.store.save(name, self.controls())
                self._refresh_profiles()
                self.status.setText("Profil local enregistré. La configuration DeSmuME n'a pas été modifiée.")
                self.settings_changed.emit(None)
            except ValueError as exc:
                self.status.setText(str(exc))

    def _load_profile(self):
        try:
            controls = self.store.load().get(self.profile_box.currentText())
            if controls:
                for key, code in controls.items():
                    self._set_code(self.key_boxes[key], code)
                self.status.setText("Profil chargé dans le brouillon. Export nécessaire pour l'appliquer.")
        except ValueError as exc:
            self.status.setText(str(exc))

    def set_app_shortcuts(self, shortcuts: dict):
        for key, edit in self.shortcut_edits.items():
            edit.setKeySequence(QKeySequence(shortcuts.get(key, "")))

    def _save_shortcuts(self):
        shortcuts = {key: edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                     for key, edit in self.shortcut_edits.items()}
        assigned = [value for value in shortcuts.values() if value]
        if len(assigned) != len(set(assigned)):
            self.status.setText("Conflit : deux raccourcis PCE utilisent la même touche.")
            return
        simple = {*self.controls().values(), *self._all_hotkeys.values()} - {0, 27}
        specials = {Qt.Key.Key_Up: 38, Qt.Key.Key_Down: 40, Qt.Key.Key_Left: 37, Qt.Key.Key_Right: 39,
                    Qt.Key.Key_Return: 13, Qt.Key.Key_Enter: 13, Qt.Key.Key_Tab: 9, Qt.Key.Key_Space: 32,
                    Qt.Key.Key_Pause: 19, Qt.Key.Key_End: 35, Qt.Key.Key_PageDown: 34}
        collisions = []
        for value in assigned:
            combination = QKeySequence(value)[0]
            if combination.keyboardModifiers() != Qt.KeyboardModifier.NoModifier:
                continue
            key = combination.key()
            code = specials.get(key, int(key))
            if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
                code = 112 + int(key) - int(Qt.Key.Key_F1)
            if code in simple:
                collisions.append(value)
        if collisions:
            self.status.setText("Conflit avec DeSmuME : " + ", ".join(collisions) + ". Choisissez une combinaison avec modificateur.")
            return
        self.app_shortcuts_changed.emit(shortcuts)
        self.status.setText("Raccourcis PCE enregistrés pour les fenêtres de l'application.")
