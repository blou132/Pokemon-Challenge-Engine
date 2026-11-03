"""Controls for the single melonDS process owned by the active PCE adventure."""
from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QMessageBox, QPushButton, QWidget
from app.ui.widgets.common import label, page_layout


class MelonDSControlsPage(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        layout = page_layout(self, "Commandes melonDS", "Les commandes s'appliquent uniquement à cette partie lancée depuis PCE.")
        self.status_label = label("Lancez la partie pour connecter les commandes.", "muted")
        layout.addWidget(self.status_label)
        self.buttons = []
        row = QHBoxLayout()
        for text in ("x1", "x2", "x4", "MAX"):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, speed=text: self._speed(speed))
            row.addWidget(button)
            self.buttons.append(button)
        layout.addLayout(row)
        layout.addWidget(label("Vitesse : réglage confirmé par melonDS après application. Le débit réel dépend du jeu et de la machine.", "muted"))
        for text, command in (("Configurer le clavier et la manette…", "input_settings"), ("Configurer les graphismes…", "video_settings")):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, action=command: self._request(action))
            layout.addWidget(button)
            self.buttons.append(button)
        layout.addWidget(label("Les fenêtres de réglages natives s'ouvrent dans melonDS. Les paramètres restent propres à cette aventure.", "muted"))
        form = QFormLayout()
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["Naturelle", "Verticale", "Horizontale", "Hybride"])
        form.addRow("Disposition des deux écrans", self.layout_combo)
        layout.addLayout(form)
        apply = QPushButton("Appliquer la disposition")
        apply.clicked.connect(lambda: self._request("screen_layout", {"value": self.layout_combo.currentIndex()}))
        layout.addWidget(apply)
        self.buttons.append(apply)
        self.slot = QComboBox()
        for number in range(1, 9):
            self.slot.addItem(f"Slot {number}", number)
        layout.addWidget(self.slot)
        row = QHBoxLayout()
        for title, command in (("Enregistrer le slot…", "save_state"), ("Charger le slot…", "load_state")):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, action=command: self._state(action))
            row.addWidget(button)
            self.buttons.append(button)
        layout.addLayout(row)
        layout.addWidget(label("Le chargement rembobine le jeu. L'historique du challenge reste conservé. Les restrictions de save states sont appliquées à ces commandes PCE ; les menus natifs restent accessibles.", "muted"))
        layout.addStretch()
        self.refresh()

    def refresh(self):
        state = self.service.state
        ready = state.running and state.native_controls and not state.command_pending
        for button in self.buttons:
            button.setEnabled(ready)
        self.status_label.setText(state.message if state.running else "Lancez cette partie depuis PCE pour connecter les commandes.")

    def _request(self, command, parameters=None):
        try:
            self.service.request_native(command, parameters)
            self.refresh()
        except (OSError, ValueError) as exc:
            self.status_label.setText(str(exc))

    def _speed(self, value):
        try:
            self.service.request_speed(value)
            self.refresh()
        except (OSError, ValueError) as exc:
            self.status_label.setText(str(exc))

    def _state(self, action):
        text = ("Enregistrer l'état actuel dans ce slot ? Son état précédent sera remplacé."
                if action == "save_state" else "Charger ce slot et revenir à cet état du jeu ? L'historique du challenge sera conservé.")
        if QMessageBox.question(self, "Save state melonDS", text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            # A missing reliable battle reader must never count as 'outside battle'.
            self.service.request_state(action, self.slot.currentData())
            self.refresh()
        except (OSError, ValueError) as exc:
            self.status_label.setText(str(exc))
