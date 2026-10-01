"""Suivi de profil et historique structurés, affichés sans logique Nuzlocke."""

from datetime import datetime

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QFormLayout, QHeaderView, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.tracking_service import TrackingState
from app.ui.widgets.common import card, label
from app.ui.widgets.nuzlocke import NuzlockeWidget, RESULT_LABELS, UNAVAILABLE, species_name

EVENT_LABELS = {
    "zone_entered": "Entrée dans la zone",
    "wild_encounter_started": "Rencontre sauvage",
    "capture_success": "Capture réussie",
    "wild_fainted": "Pokémon sauvage K.O.",
    "encounter_fainted": "Pokémon sauvage K.O.",
    "player_fled": "Fuite du joueur",
    "wild_escaped": "Fuite du Pokémon",
    "encounter_escaped": "Fuite du Pokémon",
    "battle_ended_unknown": "Fin de combat inconnue",
    "encounter_ended": "Fin de rencontre",
    "duplicate_ignored": "Doublon ignoré",
    "invalid_encounter": "Rencontre non admissible",
    "special_encounter_ignored": "Rencontre spéciale ignorée",
    "zone_already_used": "Zone déjà utilisée",
}


def _timestamp(value: object) -> str:
    try:
        if isinstance(value, str):
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif type(value) in (int, float):
            stamp = datetime.fromtimestamp(value).astimezone()
        else:
            return UNAVAILABLE
        return stamp.astimezone().strftime("%d/%m %H:%M:%S")
    except (ValueError, OverflowError, OSError):
        return UNAVAILABLE


class TrackingPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        self.compact = NuzlockeWidget()
        layout.addWidget(self.compact)
        details, content = card("Derniers événements du profil")
        self.history_note = label("Aucun événement automatique enregistré.", "muted")
        content.addWidget(self.history_note)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setAccessibleName("Historique automatique Nuzlocke")
        self.history_table.setHorizontalHeaderLabels(["Heure", "Événement", "Zone", "Rencontre", "Résultat"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.history_table.setMinimumHeight(180)
        content.addWidget(self.history_table)
        form = QFormLayout()
        self.map_label = label(UNAVAILABLE)
        self.zone_id_label = label(UNAVAILABLE)
        form.addRow("Carte détectée (map_id)", self.map_label)
        form.addRow("Zone de capture", self.zone_id_label)
        content.addLayout(form)
        self.validation_note = label(
            "Le suivi observe le jeu sans modifier la partie. "
            "Rencontres automatiques indisponibles : lectures de combat non documentées. "
            "Zone, rencontre et résultat : En attente de validation sur la machine utilisateur.", "muted")
        content.addWidget(self.validation_note)
        layout.addWidget(details)

    @Slot(object)
    def update_state(self, state: TrackingState) -> None:
        self.compact.update_state(state)
        self.map_label.setText(UNAVAILABLE if state.current_map_id is None else str(state.current_map_id))
        self.zone_id_label.setText(state.current_zone_id or UNAVAILABLE)
        events = [event for event in state.history if event.get("event") in EVENT_LABELS][-20:]
        self.history_note.setText(
            "20 derniers événements au maximum ; l'historique complet est conservé dans le profil."
            if events else "Aucun événement automatique enregistré.")
        self.history_table.setRowCount(len(events))
        for row, event in enumerate(reversed(events)):
            encounter = event.get("encounter")
            details = encounter if isinstance(encounter, dict) else event
            species_id = details.get("species_id")
            pokemon = species_name(species_id) if species_id is not None else "—"
            level = details.get("level")
            if level is not None:
                pokemon += f" · Niv. {level}"
            result = details.get("result") or event.get("result")
            values = (
                _timestamp(event.get("timestamp", event.get("at"))),
                EVENT_LABELS[event["event"]],
                str(event.get("zone_name") or event.get("capture_zone_id") or event.get("zone_id") or "—"),
                pokemon,
                RESULT_LABELS.get(result, "—"),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.history_table.setItem(row, column, item)
