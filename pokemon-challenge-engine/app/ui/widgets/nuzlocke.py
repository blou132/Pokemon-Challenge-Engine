"""Présentation réutilisable du suivi ; aucune décision de capture dans l'UI."""

from functools import lru_cache
import json
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QFormLayout, QFrame, QVBoxLayout, QWidget

from app.services.tracking_service import TrackingState
from app.ui.widgets.common import label

UNAVAILABLE = "Non disponible"
RESULT_LABELS = {
    "captured": "Capturé",
    "fainted": "Pokémon sauvage K.O.",
    "escaped": "Le Pokémon sauvage a fui",
    "player_fled": "Le joueur a fui",
    "battle_ended_unknown": "Combat terminé, résultat inconnu",
    "duplicate_ignored": "Doublon ignoré — Species Clause",
    "invalid_encounter": "Rencontre non admissible",
    "special_encounter_ignored": "Rencontre spéciale ignorée",
    "zone_already_used": "Tentative de la zone déjà utilisée",
}
ZONE_STATUS_LABELS = {
    "unused": "Aucune rencontre enregistrée",
    "encounter_started": "Première rencontre valide en cours",
    "captured": "Tentative terminée",
    "failed": "Tentative terminée",
    "ignored_by_clause": "Prochaine rencontre admissible attendue",
}
TRACKING_STATUS_LABELS = {
    "disabled": "Suivi désactivé",
    "waiting": "Suivi en attente",
    "tracking": "Suivi activé",
    "mismatch": "Suivi désactivé : jeu incompatible",
    "error": "Suivi interrompu",
}


@lru_cache(maxsize=1)
def _species_names() -> tuple[str, ...]:
    path = Path(__file__).resolve().parents[3] / "data" / "species_fr.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        names = data["names"]
        if not isinstance(names, list) or len(names) != 650 or any(type(name) is not str for name in names):
            return ()
        return tuple(names)
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def species_name(species_id: object) -> str:
    if type(species_id) is not int or not 1 <= species_id <= 649:
        return UNAVAILABLE
    names = _species_names()
    return names[species_id] if names else f"Espèce n° {species_id}"


class NuzlockeWidget(QFrame):
    """Panneau compact pouvant être réutilisé sans contrôleur ni accès disque profil."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(label("SUIVI NUZLOCKE", "eyebrow"))
        self.status_label = label("Suivi désactivé", "sectionTitle")
        layout.addWidget(self.status_label)
        self.message_label = label("", "muted")
        layout.addWidget(self.message_label)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.profile_label = self._field(form, "Profil actif")
        self.zone_label = self._field(form, "Zone actuelle")
        self.availability_label = self._field(form, "Capture")
        self.encounter_label = self._field(form, "Première rencontre")
        self.encounter_status_label = self._field(form, "Statut de la rencontre")
        self.result_label = self._field(form, "Résultat")
        layout.addLayout(form)
        self.update_state(TrackingState())

    @staticmethod
    def _field(layout: QFormLayout, title: str):
        value = label(UNAVAILABLE)
        value.setMinimumWidth(0)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addRow(title, value)
        return value

    @Slot(object)
    def update_state(self, state: TrackingState) -> None:
        self.status_label.setText(TRACKING_STATUS_LABELS.get(state.status, "Suivi en attente"))
        self.message_label.setText(state.message)
        self.message_label.setVisible(bool(state.message))
        self.message_label.setObjectName("error" if state.status in {"error", "mismatch"} else "muted")
        self.message_label.style().unpolish(self.message_label)
        self.message_label.style().polish(self.message_label)
        self.profile_label.setText(state.profile_name or "Aucun — diagnostic uniquement")
        self.zone_label.setText(state.zone_name or state.current_zone_id or UNAVAILABLE)
        self.availability_label.setText(
            UNAVAILABLE if state.zone_used is None else "Utilisée" if state.zone_used else "Disponible")
        encounter = state.encounter
        if encounter is None:
            self.encounter_label.setText("Aucune" if state.zone_used is not None else UNAVAILABLE)
        else:
            name = species_name(encounter.get("species_id"))
            level = encounter.get("level")
            self.encounter_label.setText(name + (f" · Niveau {level}" if level is not None else " · Niveau non disponible"))
        self.encounter_status_label.setText(ZONE_STATUS_LABELS.get(state.zone_status, UNAVAILABLE))
        result = encounter.get("result") if encounter else None
        self.result_label.setText(RESULT_LABELS.get(result, UNAVAILABLE))
