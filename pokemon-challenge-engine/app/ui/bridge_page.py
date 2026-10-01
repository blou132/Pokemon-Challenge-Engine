"""État réellement reçu de Lua et instructions pour connecter DeSmuME."""

from datetime import datetime

from PySide6.QtCore import Qt, QSignalBlocker, Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QHeaderView, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QWidget,
)

from app.bridge.protocol import GAME_IDS, PROTOCOL_VERSION
from app.bridge.state import BridgeState
from app.core.catalog import Catalog
from app.models.profile import Profile
from app.services.bridge_controller import BridgeController
from app.services.config_service import AppConfig
from app.ui.tracking_panel import TrackingPanel
from app.ui.widgets.common import card, label, page_layout

UNAVAILABLE = "Non disponible"
STATUS_LABELS = {
    "stopped": "Arrêtée",
    "waiting": "En attente du script Lua",
    "connected": "Connectée au script Lua",
    "receiving": "Données reçues",
    "disconnected": "Déconnectée",
    "error": "Erreur",
}


def _display(value: object) -> str:
    return UNAVAILABLE if value is None else str(value)


class BridgePage(QWidget):
    def __init__(self, catalog: Catalog, controller: BridgeController, config: AppConfig,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.controller = controller
        self.config = config
        self._profile_games: dict[str, str] = {}
        content = page_layout(self, "Connexion DeSmuME", "Connectez le script Lua pour consulter les données reçues du jeu.")

        connection_card, connection = card("Préparer la connexion")
        self.profile_combo = QComboBox()
        self.profile_combo.setAccessibleName("Profil de challenge actif pour le suivi Nuzlocke")
        self.profile_combo.addItem("Aucun profil — diagnostic uniquement", None)
        self.profile_combo.currentIndexChanged.connect(self._select_profile)
        profile_form = QFormLayout()
        profile_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        profile_form.addRow("Profil actif", self.profile_combo)
        connection.addLayout(profile_form)
        connection.addWidget(label(
            "Choisissez le profil avant la connexion. Sans profil, aucune progression n'est enregistrée. "
            "Arrêtez la connexion pour changer de profil.", "muted"))
        self.game_combo = QComboBox()
        self.game_combo.setAccessibleName("Jeu à connecter")
        for game in catalog.games.values():
            if game.id in GAME_IDS and game.status == "supported":
                self.game_combo.addItem(game.name, game.id)
        actions = QHBoxLayout()
        actions.addWidget(self.game_combo, 1)
        self.prepare_button = QPushButton("Préparer la connexion")
        self.prepare_button.setObjectName("primary")
        self.prepare_button.clicked.connect(self._start)
        actions.addWidget(self.prepare_button)
        self.stop_button = QPushButton("Arrêter la connexion")
        self.stop_button.clicked.connect(controller.stop)
        actions.addWidget(self.stop_button)
        connection.addLayout(actions)
        self.instructions = label(
            "1. Choisissez un profil si vous souhaitez suivre un challenge, puis préparez la connexion pour le jeu choisi.\n"
            "2. Dans DeSmuME standalone compatible Lua, ouvrez votre jeu, puis Tools > Lua Scripting > New Lua Script.\n"
            "3. Choisissez le script indiqué ci-dessous, puis cliquez sur Run. Gardez le jeu en cours d'exécution.", "muted")
        connection.addWidget(self.instructions)
        self.script_path = QLineEdit()
        self.script_path.setReadOnly(True)
        self.script_path.setPlaceholderText("Le chemin du script apparaîtra après la préparation")
        self.script_path.setAccessibleName("Chemin exact du script Lua à ouvrir")
        connection.addWidget(self.script_path)
        connection.addWidget(label("Les capacités Lua varient selon le build de DeSmuME. La connexion ne modifie aucune règle dans le jeu.", "muted"))
        content.addWidget(connection_card)

        status_card, status = card("État de la connexion")
        self.status_label = label("", "sectionTitle")
        self.status_label.setAccessibleName("État de la connexion Lua")
        status.addWidget(self.status_label)
        self.error_label = label("", "error")
        status.addWidget(self.error_label)
        identity = QFormLayout()
        identity.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.game_label = self._field(identity, "Dernier jeu identifié")
        self.region_label = self._field(identity, "Région / code du jeu")
        self.revision_label = self._field(identity, "Révision ROM")
        self.party_size_label = self._field(identity, "Pokémon dans l'équipe")
        status.addLayout(identity)
        content.addWidget(status_card)

        self.tracking_panel = TrackingPanel()
        content.addWidget(self.tracking_panel)

        party_card, party = card("Équipe reçue")
        self.validation_note = label(
            "Lecture d'équipe expérimentale : les profils mémoire V0.2 reposent sur des sources documentaires. "
            "Ces sources ne constituent pas une validation sur une équipe réelle dans le jeu.", "muted")
        party.addWidget(self.validation_note)
        self.party_note = label(UNAVAILABLE, "muted")
        party.addWidget(self.party_note)
        self.party_table = QTableWidget(0, 4)
        self.party_table.setAccessibleName("Équipe lue dans le jeu")
        self.party_table.setHorizontalHeaderLabels(["Place", "Niveau", "Espèce (ID)", "PV / PV max"])
        self.party_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.party_table.verticalHeader().setVisible(False)
        self.party_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.party_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.party_table.setMinimumHeight(215)
        party.addWidget(self.party_table)
        content.addWidget(party_card)

        diagnostics_card, diagnostics = card("Diagnostic")
        fields = QFormLayout()
        fields.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.protocol_label = self._field(fields, "Protocole reçu / attendu")
        self.protocol_label.setText(str(PROTOCOL_VERSION))
        self.script_version_label = self._field(fields, "Version du script reçue")
        self.memory_profile_label = self._field(fields, "Profil mémoire reçu")
        self.capabilities_label = self._field(fields, "Capacités reçues")
        self.received_label = self._field(fields, "Instantanés reçus")
        self.event_label = self._field(fields, "Dernier événement Lua")
        self.timestamp_label = self._field(fields, "Horodatage du dernier message")
        self.pid_label = self._field(fields, "PID lancé par l'application")
        diagnostics.addLayout(fields)
        diagnostics.addWidget(label("Le PID indique seulement le dernier processus lancé ici. Seuls les messages Lua confirment la connexion. Les valeurs absentes restent « Non disponible ».", "muted"))
        content.addWidget(diagnostics_card)
        content.addStretch()

        controller.state_changed.connect(self.update_state)
        controller.prepared.connect(self._prepared)
        controller.failed.connect(self._failed)
        controller.tracking_changed.connect(self.tracking_panel.update_state)
        self.tracking_panel.update_state(controller.tracking_state)
        self.update_state(controller.state)

    @staticmethod
    def _field(layout: QFormLayout, title: str) -> QLabel:
        value = label(UNAVAILABLE)
        value.setMinimumWidth(0)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addRow(title, value)
        return value

    def set_config(self, config: AppConfig) -> None:
        self.config = config

    def set_profiles(self, profiles: list[Profile]) -> None:
        """Actualise les choix sans sélectionner implicitement un profil."""
        previous = self.profile_combo.currentData()
        previous_label = self.profile_combo.currentText()
        with QSignalBlocker(self.profile_combo):
            self.profile_combo.clear()
            self.profile_combo.addItem("Aucun profil — diagnostic uniquement", None)
            self._profile_games = {}
            for profile in profiles:
                game = self.catalog.games.get(profile.challenge.game_id)
                game_name = game.name if game else profile.challenge.game_id
                self.profile_combo.addItem(f"{profile.name} · {game_name}", profile.id)
                self._profile_games[profile.id] = profile.challenge.game_id
            index = self.profile_combo.findData(previous)
            # Une session en cours conserve son association, même si la liste a changé.
            if previous is not None and index < 0 and self.controller.state.status != "stopped":
                self.profile_combo.addItem(previous_label + " (indisponible)", previous)
                index = self.profile_combo.count() - 1
            self.profile_combo.setCurrentIndex(max(0, index))
        if self.profile_combo.currentData() != previous:
            self.controller.select_profile(self.profile_combo.currentData())

    @Slot(int)
    def _select_profile(self, _index: int) -> None:
        profile_id = self.profile_combo.currentData()
        game_id = self._profile_games.get(profile_id)
        if game_id is not None and self.controller.state.status == "stopped":
            index = self.game_combo.findData(game_id)
            if index >= 0:
                self.game_combo.setCurrentIndex(index)
        self.controller.select_profile(profile_id)

    def track_process(self, process: object) -> None:
        self.pid_label.setText(_display(getattr(process, "pid", None)))

    @Slot()
    def _start(self) -> None:
        game_id = self.game_combo.currentData()
        if game_id is None:
            return
        self.prepare_button.setEnabled(False)
        self.game_combo.setEnabled(False)
        self.profile_combo.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.script_path.clear()
        self.status_label.setText("Préparation en cours…")
        self.error_label.hide()
        self.controller.start(game_id, self.config.rom_paths.get(game_id, ""))

    @Slot(str)
    def _prepared(self, path: str) -> None:
        self.script_path.setText(path)
        self.script_path.setCursorPosition(0)

    @Slot(str)
    def _failed(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    @Slot(object)
    def update_state(self, state: BridgeState) -> None:
        self.status_label.setText(STATUS_LABELS[state.status])
        self.error_label.setText(state.last_error or "")
        self.error_label.setVisible(bool(state.last_error))
        active = state.status in {"waiting", "connected", "receiving"}
        self.prepare_button.setEnabled(not active)
        # Une session déconnectée peut encore recevoir un message tardif du même jeu.
        self.game_combo.setEnabled(state.status == "stopped")
        self.profile_combo.setEnabled(state.status == "stopped")
        self.stop_button.setEnabled(state.status != "stopped")
        if state.status == "stopped":
            self.script_path.clear()
        game = self.catalog.games.get(state.game_id)
        self.game_label.setText(game.name if game is not None else UNAVAILABLE)
        self.region_label.setText(f"{_display(state.game_region)} / {_display(state.game_code)}")
        self.revision_label.setText(_display(state.rom_revision))
        self.party_size_label.setText(_display(state.party_size if state.connected else None))
        self.script_version_label.setText(_display(state.script_version))
        self.protocol_label.setText(str(state.protocol_version if state.received_count else PROTOCOL_VERSION))
        self.memory_profile_label.setText(_display(state.memory_profile))
        self.capabilities_label.setText(", ".join(state.capabilities) if state.capabilities else UNAVAILABLE)
        self.received_label.setText(str(state.received_count))
        self.event_label.setText(_display(state.last_event))
        try:
            timestamp = datetime.fromtimestamp(state.last_timestamp).astimezone().strftime("%d/%m/%Y %H:%M:%S %Z") if state.last_timestamp is not None else UNAVAILABLE
        except (OverflowError, OSError, ValueError):
            timestamp = "Horodatage non affichable"
        self.timestamp_label.setText(timestamp)

        party = state.party if state.connected else None
        self.party_note.setText(UNAVAILABLE if party is None else ("Équipe vide." if not party else "Valeurs du dernier instantané validé."))
        self.party_table.setRowCount(len(party) if party is not None else 0)
        for index, pokemon in enumerate(party or []):
            hp = f"{pokemon['hp']} / {pokemon['max_hp']}" if pokemon["hp"] is not None and pokemon["max_hp"] is not None else UNAVAILABLE
            for column, value in enumerate((pokemon["slot"], pokemon["level"], pokemon["species_id"], hp)):
                item = QTableWidgetItem(_display(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.party_table.setItem(index, column, item)
