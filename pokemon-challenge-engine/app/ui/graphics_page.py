"""Only verified INI display options are offered for the recognized binary."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QPushButton, QWidget

from app.services.emulator_settings_service import GRAPHICS_PRESETS, EmulatorSettingsService
from app.ui.widgets.common import card, label, page_layout


class GraphicsPage(QWidget):
    settings_changed = Signal(object)

    def __init__(self, service: EmulatorSettingsService, parent=None):
        super().__init__(parent)
        self.service = service
        layout = page_layout(self, "Graphismes", "Réglages documentés du binaire reconnu. Application au prochain lancement.")
        self.status = label("", "subtitle")
        layout.addWidget(self.status)
        self.panel, body = card("Affichage DeSmuME")
        form = QFormLayout()
        self.options = {}
        definitions = {
            "internal_resolution": ("Résolution interne", [(f"{i}× (3D)", i) for i in (1, 2, 3, 4)]),
            "vsync": ("VSync", [("Désactivée", 0), ("Activée", 1)]),
            "output_filter": ("Interpolation de sortie OpenGL", [("Désactivée", 0), ("Activée", 1)]),
            "aspect_ratio": ("Conserver les proportions", [("Non", 0), ("Oui", 1)]),
            "integer_scaling": ("Mise à l'échelle entière", [("Non", 0), ("Oui", 1)]),
            "layout": ("Disposition DS", [("Verticale", 0), ("Horizontale", 1), ("Un écran", 2)]),
            "rotation": ("Rotation", [(f"{i}°", i) for i in (0, 90, 180, 270)]),
        }
        for key, (title, values) in definitions.items():
            box = QComboBox()
            for text, value in values:
                box.addItem(text, value)
            self.options[key] = box
            form.addRow(title, box)
        body.addLayout(form)
        presets = QHBoxLayout()
        for key, title in (("original", "Original"), ("sharp", "Net"), ("hd", "HD"), ("performance", "Performance")):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, chosen=key: self.set_preset(chosen))
            presets.addWidget(button)
        body.addLayout(presets)
        body.addWidget(label("HD sélectionne une résolution interne 3D ×2. Les sprites 2D conservent leurs détails d'origine. L'interpolation de sortie dépend du moteur OpenGL déjà choisi dans DeSmuME."))
        apply = QPushButton("Enregistrer dans DeSmuME fermé")
        apply.setToolTip("Backup INI obligatoire, conservé avec un numéro unique avant chaque changement.")
        apply.clicked.connect(self._apply)
        body.addWidget(apply)
        layout.addWidget(self.panel)
        layout.addWidget(label("Les shaders et le plein écran DeSmuME ne sont pas pilotés ici. Le plein écran de PCE reste indépendant."))
        layout.addStretch()
        self.refresh()

    def set_executable(self, path: str):
        self.service.set_executable(path)
        self.refresh()

    def refresh(self):
        try:
            snapshot = self.service.inspect()
            self.panel.setVisible(snapshot.capabilities.known_build and bool(snapshot.graphics))
            if not snapshot.graphics:
                self.status.setText("Version DeSmuME non vérifiée : aucune option graphique proposée.")
                return
            for key, value in snapshot.graphics.items():
                box = self.options[key]
                index = box.findData(value)
                if index < 0:
                    box.addItem(str(value), value)
                    index = box.count() - 1
                box.setCurrentIndex(index)
            self.status.setText("Valeurs du fichier DeSmuME. Le rendu et la cadence en cours ne sont pas mesurés.")
        except (ValueError, OSError) as exc:
            self.panel.hide()
            self.status.setText(str(exc))

    def set_preset(self, preset: str):
        for key, value in GRAPHICS_PRESETS[preset].items():
            self.options[key].setCurrentIndex(self.options[key].findData(value))
        self.status.setText("Preset préparé. Enregistrez pour le prochain lancement.")

    def _apply(self):
        try:
            change = self.service.apply(graphics={key: box.currentData() for key, box in self.options.items()})
            self.status.setText(f"Configuration enregistrée. Backup : {change.backup_path.name}. Relancez DeSmuME.")
            self.settings_changed.emit(change)
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
