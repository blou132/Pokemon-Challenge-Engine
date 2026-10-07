"""Préférences de présentation et profils de lancement locaux du Mode Jeu."""

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout,
    QHBoxLayout, QLineEdit, QPushButton, QWidget,
)

from app.services.game_mode_config import BLOCKS
from app.ui.game_mode_page import BLOCK_LABELS
from app.ui.widgets.common import card, label, page_layout


class InterfaceInGamePage(QWidget):
    settings_changed = Signal(dict)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        layout = page_layout(self, "Interface en jeu", "Choisissez les informations affichées autour de votre jeu.")
        appearance, box = card("Disposition")
        self.density_combo = QComboBox()
        for name, value in (("Compact · 1366 × 768", "compact"), ("Standard", "standard"), ("Large · 1920 × 1080", "large")):
            self.density_combo.addItem(name, value)
        self.monitor_combo = QComboBox()
        self.monitor_combo.addItem("Choisir un écran…", "")
        for index, screen in enumerate(QApplication.screens(), 1):
            rect = screen.availableGeometry()
            self.monitor_combo.addItem(f"Écran {index} · {screen.name()} · {rect.width()} × {rect.height()}", screen.name())
        form = QFormLayout()
        form.addRow("Taille du panneau", self.density_combo)
        form.addRow("Écran du Mode Jeu", self.monitor_combo)
        box.addLayout(form)
        self.auto_arrange = QCheckBox("Organiser automatiquement les fenêtres après le lancement")
        self.auto_arrange.setToolTip("Option explicite. Aucun écran n'est choisi automatiquement sur une installation multi-écrans.")
        box.addWidget(self.auto_arrange)
        box.addWidget(label("DeSmuME reste externe. L'organisation déplace sa fenêtre sans intégrer le jeu ni modifier les entrées clavier.", "muted"))
        layout.addWidget(appearance)
        panels, box = card("Blocs visibles")
        grid = QGridLayout()
        grid.addWidget(label("Afficher", "muted"), 0, 0)
        grid.addWidget(label("Emplacement", "muted"), 0, 1)
        self.visible_checks, self.side_combos = {}, {}
        for row, key in enumerate(BLOCKS, 1):
            check = QCheckBox(BLOCK_LABELS[key])
            side = QComboBox()
            side.addItem("Gauche", "left")
            side.addItem("Droite", "right")
            side.setAccessibleName(f"Emplacement du bloc {BLOCK_LABELS[key]}")
            self.visible_checks[key], self.side_combos[key] = check, side
            grid.addWidget(check, row, 0)
            grid.addWidget(side, row, 1)
        box.addLayout(grid)
        layout.addWidget(panels)
        self.feedback = label("", "muted")
        layout.addWidget(self.feedback)
        self.save_button = QPushButton("Enregistrer l'interface")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(lambda: self.settings_changed.emit(self.values()))
        layout.addWidget(self.save_button)
        layout.addStretch()
        self.set_settings(settings)

    def set_settings(self, settings):
        self.density_combo.setCurrentIndex(max(0, self.density_combo.findData(settings.get("density", "standard"))))
        self.monitor_combo.setCurrentIndex(max(0, self.monitor_combo.findData(settings.get("monitor_name", ""))))
        self.auto_arrange.setChecked(settings.get("auto_arrange", False))
        for key in BLOCKS:
            self.visible_checks[key].setChecked(settings.get("visible", {}).get(key, key not in {"logs", "debug"}))
            side = settings.get("sides", {}).get(key, "left" if key in {"controls", "speed", "saves"} else "right")
            self.side_combos[key].setCurrentIndex(self.side_combos[key].findData(side))

    def values(self):
        return {"density": self.density_combo.currentData(), "monitor_name": self.monitor_combo.currentData(),
                "auto_arrange": self.auto_arrange.isChecked(),
                "visible": {key: check.isChecked() for key, check in self.visible_checks.items()},
                "sides": {key: combo.currentData() for key, combo in self.side_combos.items()}}


class LaunchProfilePage(QWidget):
    settings_changed = Signal(str, dict)
    game_changed = Signal(str)

    def __init__(self, catalog, profiles, parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self._launch_profiles = profiles
        self._profiles = []
        layout = page_layout(self, "Profil de lancement", "Un ensemble de chemins et de préférences par jeu.")
        self.game_combo = QComboBox()
        for game in catalog.games.values():
            if game.status == "supported":
                self.game_combo.addItem(game.name, game.id)
        layout.addWidget(self.game_combo)
        paths, box = card("Jeu et émulateur")
        self.path_edits = {}
        for key, text, filter_text in (("rom_path", "ROM Nintendo DS", "ROM Nintendo DS (*.nds)"),
                                      ("emulator_path", "Exécutable DeSmuME", "Exécutable Windows (*.exe)"),
                                      ("ini_path", "Configuration DeSmuME (facultatif)", "Configuration (*.ini)")):
            box.addWidget(label(text))
            row = QHBoxLayout()
            edit = QLineEdit()
            edit.setPlaceholderText("Aucun chemin configuré")
            edit.setAccessibleName(text)
            self.path_edits[key] = edit
            browse = QPushButton("Parcourir…")
            browse.clicked.connect(lambda checked=False, field=edit, filters=filter_text: self._browse(field, filters))
            row.addWidget(edit, 1)
            row.addWidget(browse)
            box.addLayout(row)
        layout.addWidget(paths)
        preferences, box = card("Préférences au lancement")
        form = QFormLayout()
        self.controls_profile = QLineEdit("default")
        self.controls_profile.setToolTip("Nom d'un profil enregistré dans l'onglet Contrôles.")
        self.graphics_preset = QComboBox()
        # Les noms désignent des ensembles de clés documentées ; disponibilité
        # et export sont vérifiés par EmulatorSettingsService avant application.
        for text, value in (("Original", "original"), ("Net", "sharp"), ("HD", "hd"), ("Performance", "performance")):
            self.graphics_preset.addItem(text, value)
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["x1", "x2", "x4", "MAX"])
        self.challenge_combo = QComboBox()
        self.challenge_combo.addItem("Sans profil", None)
        form.addRow("Profil de contrôles", self.controls_profile)
        form.addRow("Preset graphique demandé", self.graphics_preset)
        form.addRow("Vitesse demandée", self.speed_combo)
        form.addRow("Challenge associé", self.challenge_combo)
        box.addLayout(form)
        self.apply_settings = QCheckBox("Exporter ces réglages DeSmuME au lancement, avec backup de sa configuration")
        self.apply_settings.setToolTip("Export uniquement pour un build reconnu, émulateur arrêté, après sauvegarde de son INI.")
        box.addWidget(self.apply_settings)
        self.auto_lua = QCheckBox("Connecter automatiquement Lua avec Jouer")
        self.auto_lua.setToolTip("Une confirmation est demandée avant la première configuration de l'autoload DeSmuME.")
        box.addWidget(self.auto_lua)
        self.game_mode = QCheckBox("Revenir au Mode Jeu après le lancement")
        box.addWidget(self.game_mode)
        box.addWidget(label("Sans export, ces choix restent configurés. Les données Pokémon et les sauvegardes ne sont jamais modifiées par ces réglages.", "muted"))
        layout.addWidget(preferences)
        self.feedback = label("", "muted")
        layout.addWidget(self.feedback)
        self.save_button = QPushButton("Enregistrer le profil de lancement")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save)
        layout.addWidget(self.save_button)
        layout.addStretch()
        self.game_combo.currentIndexChanged.connect(self._selected)
        self._selected()

    def set_profiles(self, profiles):
        self._profiles = profiles
        self._fill_challenges(self._launch_profiles[self.game_combo.currentData()].get("challenge_profile_id"))

    def _fill_challenges(self, selected):
        with QSignalBlocker(self.challenge_combo):
            self.challenge_combo.clear()
            self.challenge_combo.addItem("Sans profil", None)
            for profile in self._profiles:
                if profile.challenge.game_id == self.game_combo.currentData():
                    self.challenge_combo.addItem(profile.name, profile.id)
            self.challenge_combo.setCurrentIndex(max(0, self.challenge_combo.findData(selected)))

    def set_context(self, game_id, profiles=None):
        if profiles is not None:
            self._launch_profiles = profiles
        with QSignalBlocker(self.game_combo):
            self.game_combo.setCurrentIndex(self.game_combo.findData(game_id))
        self._selected()

    def _selected(self, *_):
        game_id = self.game_combo.currentData()
        values = self._launch_profiles[game_id]
        for key, edit in self.path_edits.items():
            edit.setText(values[key])
        self.controls_profile.setText(values["controls_profile"])
        self.graphics_preset.setCurrentIndex(max(0, self.graphics_preset.findData(values["graphics_preset"])))
        self.speed_combo.setCurrentText(values["speed"])
        self.apply_settings.setChecked(values["apply_settings"])
        self.auto_lua.setChecked(values.get("lua_connection", "ask") != "manual")
        self.game_mode.setChecked(values["game_mode"])
        self._fill_challenges(values.get("challenge_profile_id"))
        self.game_changed.emit(game_id)

    def _browse(self, field, filters):
        path, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier", field.text(), filters)
        if path:
            field.setText(path)

    def _save(self):
        values = {key: edit.text().strip() for key, edit in self.path_edits.items()}
        values.update(controls_profile=self.controls_profile.text().strip(), graphics_preset=self.graphics_preset.currentData(),
                      speed=self.speed_combo.currentText(), apply_settings=self.apply_settings.isChecked(),
                      lua_connection="auto" if self.auto_lua.isChecked() else "manual",
                      challenge_profile_id=self.challenge_combo.currentData(), game_mode=self.game_mode.isChecked())
        self.settings_changed.emit(self.game_combo.currentData(), values)
