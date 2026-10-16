"""Explicit individual choice; no inference from species, slot or team order."""

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QTextEdit, QVBoxLayout,
)

from app.core.allowed_pokemon import designation_purpose, eligible_individuals, latest_designation
from app.ui.widgets.common import label
from app.ui.widgets.nuzlocke import species_name


class AllowedPokemonDialog(QDialog):
    def __init__(self, run, parent=None):
        super().__init__(parent)
        self.purpose = designation_purpose(run.active_rules)
        if self.purpose is None:
            raise ValueError("Cette partie ne demande pas de désignation individuelle.")
        self.previous = latest_designation(run)
        self.candidates = eligible_individuals(run)
        self.setWindowTitle("Désigner le starter" if self.purpose == "starter" else "Désigner l'individu Solo Run")
        self.resize(560, 390)
        box = QVBoxLayout(self)
        box.addWidget(label("DÉCLARATION MANUELLE · données de cette partie uniquement", "eyebrow"))
        box.addWidget(label("Choisissez un individu identifié dans la dernière équipe enregistrée. "
            "Ni son espèce ni son emplacement ne prouvent qu'il est votre starter. "
            "La présence sera comparée à votre déclaration ; l'utilisation en combat reste inconnue.", "muted"))
        current = self.previous["payload"].get("pokemon") if self.previous else None
        box.addWidget(label("Désignation actuelle : " + species_name(current["species_id"]) + " · déclaration manuelle"
                            if current else "Aucun individu actuellement désigné.", "muted"))
        form = QFormLayout()
        self.pokemon_combo = QComboBox()
        self.pokemon_combo.addItem("Choisir un individu…", "")
        for number, (key, pokemon) in enumerate(self.candidates.items(), 1):
            self.pokemon_combo.addItem(f"{species_name(pokemon['species_id'])} · N{pokemon['level']} · "
                f"emplacement {pokemon['slot']} · individu {number}", key)
        if current:
            self.pokemon_combo.addItem("Retirer la désignation actuelle", None)
            index = self.pokemon_combo.findData(self.previous["payload"]["pokemon_key"])
            if index >= 0:
                self.pokemon_combo.setCurrentIndex(index)
        form.addRow("Individu", self.pokemon_combo)
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("Note ou motif de correction facultatif")
        self.note_edit.setMaximumHeight(100)
        form.addRow("Note", self.note_edit)
        box.addLayout(form)
        if not self.candidates:
            box.addWidget(label("Aucun individu fiable disponible. Faites observer l'équipe ; les identités faibles "
                                "ou ambiguës ne peuvent pas être désignées.", "muted"))
        self.confirm_check = QCheckBox()
        self.pokemon_combo.currentIndexChanged.connect(self._choice_changed)
        self._choice_changed()
        box.addWidget(self.confirm_check)
        box.addWidget(label("Chaque choix, correction ou retrait reste dans l'historique. "
                            "Les règles figées de la partie et les fichiers Pokémon restent inchangés.", "muted"))
        self.error_label = label("", "error")
        self.error_label.hide()
        box.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        box.addWidget(self.buttons)

    def _choice_changed(self, *_args):
        self.confirm_check.setChecked(False)
        self.confirm_check.setText("Je confirme le retrait de cette désignation."
            if self.pokemon_combo.currentData() is None else
            "Je déclare que cet individu est le starter reçu dans cette aventure."
            if self.purpose == "starter" else "Je désigne cet individu comme Pokémon autorisé de cette partie Solo Run.")

    def payload(self):
        key = self.pokemon_combo.currentData()
        if key == "" or key is not None and key not in self.candidates:
            raise ValueError("Sélectionnez un individu fiable ou le retrait de la désignation actuelle.")
        if key is None and (self.previous is None or self.previous["payload"]["pokemon_key"] is None):
            raise ValueError("Aucune désignation active à retirer.")
        if not self.confirm_check.isChecked():
            raise ValueError("Confirmez explicitement votre déclaration manuelle.")
        note = self.note_edit.toPlainText().strip()
        if len(note) > 10000:
            raise ValueError("La note doit contenir au plus 10 000 caractères.")
        return {"pokemon_key": key, "note": note, "confirmed": True,
                "previous_event_id": self.previous["event_id"] if self.previous else None}

    def accept(self):
        try:
            self.payload()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()
            return
        super().accept()
