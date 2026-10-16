"""Explicit Randomizer settings, separate from local tools and execution."""
from PySide6.QtCore import QSignalBlocker, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
    QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from app.services.rom_transformation_service import CATEGORIES, SUPPORTED_CODES, RandomizerOptions, ZX_VERSION
from app.ui.setup_tasks import SetupTaskRunner
from app.ui.widgets.common import label


CATEGORY_LABELS = {
    "wild": "Pokémon sauvages", "starters": "Starters",
    "trainers": "Dresseurs, champions compris", "movesets": "Capacités apprises",
    "abilities": "Talents", "field_items": "Objets de terrain",
    "evolutions": "Évolutions", "types": "Types des Pokémon",
}
CATEGORY_NOTES = {
    "trainers": "Inclut les champions ; aucun mode champions seuls.",
    "movesets": "Capacités apprises par niveau, pas toutes les CT ni les tuteurs.",
    "field_items": "Objets de terrain ordinaires, pas tous les objets du jeu.",
}


class RandomizerConfiguration(QWidget):
    changed = Signal()
    verify_tool_requested = Signal(str, str)
    discover_tools_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._tool_state = "unverified"
        self._game_supported = False
        self._auto_discovery_enabled = False
        self._auto_discovery_attempted = False
        self._discovery_timer = QTimer(self)
        self._discovery_timer.setSingleShot(True)
        self._discovery_timer.timeout.connect(self._auto_discover)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(label(f"Randomizer · ZX {ZX_VERSION}", "subtitle"))
        self.enabled_check = QCheckBox("Créer une ROM randomisée dédiée à cette nouvelle partie")
        self.enabled_check.setChecked(True)
        box.addWidget(self.enabled_check)
        self.options_widget = QWidget()
        grid = QGridLayout(self.options_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        self.category_checks = {}
        defaults = RandomizerOptions()
        for index, category in enumerate(CATEGORIES):
            check = QCheckBox(CATEGORY_LABELS[category])
            check.setChecked(category in defaults.categories)
            check.setToolTip(CATEGORY_NOTES.get(category, ""))
            check.toggled.connect(self._options_changed)
            self.category_checks[category] = check
            grid.addWidget(check, index // 2, index % 2)
        self.balanced_check = QCheckBox("Privilégier une puissance similaire")
        self.balanced_check.setToolTip("Pour les sauvages, dresseurs et évolutions sélectionnés ; ne garantit pas l'équilibre du challenge.")
        self.balanced_check.toggled.connect(self._options_changed)
        grid.addWidget(self.balanced_check, 4, 0, 1, 2)
        box.addWidget(self.options_widget)
        self.seed_label = label("Seed du challenge : à définir", "muted")
        self.compatibility_label = label("", "muted")
        self.safety_label = label("Nouvelle aventure sans import de sauvegarde. La ROM source reste intacte ; "
            "la copie dédiée sera créée après confirmation. Taux shiny original conservé.", "muted")
        box.addWidget(self.seed_label)
        box.addWidget(self.compatibility_label)
        box.addWidget(self.safety_label)
        form = QFormLayout()
        self.java_edit, self.jar_edit = QLineEdit(), QLineEdit()
        self.java_edit.setPlaceholderText("Exécutable java du JDK 11 ou supérieur")
        self.jar_edit.setPlaceholderText(f"PokeRandoZX.jar officiel, version {ZX_VERSION}")
        self.browse_buttons = []
        for title, edit, pattern in (("Java (local)", self.java_edit, "Exécutable Java (java.exe);;Tous les fichiers (*)"),
                                     ("ZX (local)", self.jar_edit, "Archive Java (*.jar)")):
            edit.setMaxLength(4096)
            edit.textChanged.connect(self._tools_changed)
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            browse = QPushButton("Parcourir…")
            browse.clicked.connect(lambda _checked=False, target=edit, file_filter=pattern:
                                   self._browse(target, file_filter))
            row.addWidget(browse)
            self.browse_buttons.append(browse)
            form.addRow(title, row)
        box.addLayout(form)
        self.verify_button = QPushButton("Vérifier et enregistrer les outils locaux")
        self.verify_button.clicked.connect(self._request_verification)
        self.discover_button = QPushButton("Détecter les outils présents")
        self.discover_button.clicked.connect(self._request_discovery)
        self.tool_status_label = label("Outils non vérifiés. Aucun téléchargement automatique.", "muted")
        box.addWidget(self.discover_button)
        box.addWidget(self.verify_button)
        box.addWidget(self.tool_status_label)
        box.addWidget(label("Ces chemins restent sur cet ordinateur et ne sont jamais ajoutés au modèle de challenge.", "muted"))
        self.enabled_check.toggled.connect(self._options_changed)
        self.set_context(None, None)
        self._options_changed()
        self._tools_changed()

    def _browse(self, edit, file_filter):
        filename, _ = QFileDialog.getOpenFileName(self, "Choisir l'outil local", edit.text(), file_filter)
        if filename:
            edit.setText(filename)

    def _options_changed(self, *_args):
        self.options_widget.setEnabled(self.enabled_check.isChecked() and self._game_supported)
        eligible = any(self.category_checks[key].isChecked() for key in ("wild", "trainers", "evolutions"))
        self.balanced_check.setEnabled(eligible)
        if not eligible:
            with QSignalBlocker(self.balanced_check):
                self.balanced_check.setChecked(False)
        if not self._loading:
            self.changed.emit()
        self._schedule_discovery()

    def _tools_changed(self, *_args):
        self.set_tool_status("unverified", "Outils non vérifiés. La présence d'un chemin ne prouve pas sa compatibilité.")

    def _request_verification(self):
        paths = self.tool_paths()
        self.verify_tool_requested.emit(paths["java_path"], paths["jar_path"])

    def set_auto_discovery_enabled(self, enabled: bool):
        self._auto_discovery_enabled = enabled
        self._schedule_discovery()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_discovery()

    def _schedule_discovery(self):
        if self._auto_discovery_enabled and not self._auto_discovery_attempted and self.isVisible():
            self._discovery_timer.start(0)

    def _auto_discover(self):
        if self._auto_discovery_enabled and self.isVisible() and self.enabled_check.isChecked() and \
                not self._auto_discovery_attempted and not all(self.tool_paths().values()):
            self._request_discovery()

    def _request_discovery(self):
        if self._tool_state == "checking":
            return
        self._auto_discovery_attempted = True
        self._discovery_timer.stop()
        paths = self.tool_paths()
        self.discover_tools_requested.emit(paths["java_path"], paths["jar_path"])

    def options(self) -> RandomizerOptions:
        return RandomizerOptions(tuple(key for key in CATEGORIES if self.category_checks[key].isChecked()),
                                 self.balanced_check.isChecked())

    def set_options(self, options: RandomizerOptions, *, enabled=True):
        if not isinstance(options, RandomizerOptions) or type(enabled) is not bool:
            raise ValueError("Configuration Randomizer invalide.")
        self._loading = True
        try:
            for key, check in self.category_checks.items():
                check.setChecked(key in options.categories)
            self.balanced_check.setChecked(options.balanced)
            self.enabled_check.setChecked(enabled)
            self._options_changed()
        finally:
            self._loading = False

    def configuration(self) -> dict | None:
        if self.enabled_check.isChecked() and not self._game_supported:
            raise ValueError("Jeu non pris en charge par cet adaptateur Randomizer.")
        return {"kind": "zx", **self.options().to_dict()} if self.enabled_check.isChecked() else None

    def tool_paths(self) -> dict:
        return {"java_path": self.java_edit.text().strip(), "jar_path": self.jar_edit.text().strip()}

    def set_tool_paths(self, java_path: str, jar_path: str):
        self.java_edit.setText(java_path)
        self.jar_edit.setText(jar_path)

    def set_context(self, game_id, seed):
        code = SUPPORTED_CODES.get(game_id) if isinstance(game_id, str) else None
        self._game_supported = code is not None
        self.compatibility_label.setText(
            f"ROM requise : {code} · FR · révision 0. Compatibilité de la ROM à vérifier avant transformation. "
            "Le lancement et la lecture Lua nécessitent leur propre validation."
            if code else "Jeu non pris en charge par cet adaptateur Randomizer.")
        self.enabled_check.setEnabled(code is not None)
        self.options_widget.setEnabled(self.enabled_check.isChecked() and self._game_supported)
        valid_seed = type(seed) is int and 0 <= seed <= 2**63 - 1
        self.seed_label.setText(f"Seed du challenge : {seed} · utilisée aussi pour la ROM" if valid_seed else
                                "Seed du challenge : à définir (entier entre 0 et 9223372036854775807)")

    def set_tool_status(self, state: str, message: str):
        if state not in {"unverified", "checking", "verified", "error"}:
            raise ValueError("État de vérification Randomizer inconnu.")
        self._tool_state = state
        self.tool_status_label.setText(message)
        busy = state == "checking"
        for widget in (self.java_edit, self.jar_edit, *self.browse_buttons):
            widget.setEnabled(not busy)
        self.verify_button.setEnabled(not busy and all(self.tool_paths().values()))
        self.discover_button.setEnabled(not busy)


class RandomizerToolVerificationDialog(QDialog):
    """Bounded tool verification in the existing worker, guarded during closure."""
    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vérification des outils Randomizer")
        self.error = ""
        self.result_data = None
        self.operation = operation
        box = QVBoxLayout(self)
        self.status_label = label("Vérification du JAR officiel et de Java en cours…")
        box.addWidget(self.status_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        self.buttons.setEnabled(False)
        box.addWidget(self.buttons)
        self.runner = SetupTaskRunner(self)
        self.runner.succeeded.connect(self._succeeded)
        self.runner.failed.connect(self._failed)

    def begin(self):
        self.runner.start(self.operation)

    def _succeeded(self, result):
        self.result_data = result
        self.accept()

    def _failed(self, message):
        self.error = message
        self.status_label.setText(message)
        self.buttons.setEnabled(True)

    def reject(self):
        if not self.runner.is_busy:
            super().reject()

    def closeEvent(self, event):
        if self.runner.is_busy:
            event.ignore()
        else:
            super().closeEvent(event)
