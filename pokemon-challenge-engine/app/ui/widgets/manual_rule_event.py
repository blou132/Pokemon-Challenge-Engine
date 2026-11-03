"""Manual action declarations, kept separate from automatic observations."""

from copy import deepcopy

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QSpinBox, QTextEdit, QVBoxLayout, QWidget

from app.core.manual_rule_event import ACTIONS, ENCOUNTER_KINDS, ENCOUNTER_OUTCOMES, active_declarations, available_actions
from app.ui.widgets.common import label


class ManualRuleEventDialog(QDialog):
    def __init__(self, run, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Déclarer ou corriger une action / rencontre")
        self.resize(650, 610)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Saisie manuelle uniquement. Aucun événement n'est déduit des PV ou du lieu. "
                               "Une déclaration reste dans l'historique après correction.", "muted"))
        form = QFormLayout()
        self.previous_combo = QComboBox()
        self.previous_combo.addItem("Nouvelle déclaration", None)
        for event in active_declarations(run.history).values():
            self.previous_combo.addItem(event["timestamp"][:16].replace("T", " ") + " · "
                                        + ACTIONS[event["payload"]["kind"]].label, event["event_id"])
        form.addRow("Déclaration à corriger", self.previous_combo)
        self.kind_combo = QComboBox()
        for kind, action in available_actions(run.active_rules).items():
            self.kind_combo.addItem(action.label, kind)
        self.kind_combo.addItem("Retirer la déclaration sélectionnée", None)
        form.addRow("Action réellement effectuée", self.kind_combo)
        self.zone_edit = QLineEdit()
        self._zone = deepcopy(run.current_zone)
        self._zone_text = self._zone_label(self._zone)
        self.zone_edit.setText(self._zone_text)
        self.zone_edit.setPlaceholderText("Zone inconnue si vide")
        form.addRow("Zone de l'action", self.zone_edit)
        layout.addLayout(form)
        self.encounter_fields = QWidget()
        encounter_form = QFormLayout(self.encounter_fields)
        self.species_spin = QSpinBox()
        self.species_spin.setRange(1, 649)
        encounter_form.addRow("Espèce (numéro Pokédex national)", self.species_spin)
        self.encounter_kind_combo = QComboBox()
        for kind, text in ENCOUNTER_KINDS.items():
            self.encounter_kind_combo.addItem(text, kind)
        encounter_form.addRow("Type de rencontre", self.encounter_kind_combo)
        self.outcome_combo = QComboBox()
        for outcome, text in ENCOUNTER_OUTCOMES.items():
            if outcome != "duplicate_ignored" or "species_clause" in run.active_rules:
                self.outcome_combo.addItem(text, outcome)
        self.outcome_combo.setCurrentIndex(self.outcome_combo.findData("unknown"))
        encounter_form.addRow("Résultat confirmé", self.outcome_combo)
        encounter_form.addRow(label("Une capture saisie ici figure déjà dans les compteurs : ne la déclarez pas une seconde fois avec « Capture ».", "muted"))
        layout.addWidget(self.encounter_fields)
        layout.addWidget(label("Les Poké Balls et objets tenus sont autorisés par No Items. "
                               "Les soins scénarisés ne constituent pas un soin volontaire No Healing.", "muted"))
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("Contexte facultatif ; raison obligatoire pour une correction.")
        layout.addWidget(self.note_edit)
        self.confirmation = QCheckBox("Je confirme cette déclaration ou cette correction manuelle.")
        layout.addWidget(self.confirmation)
        self.error_label = label("", "error")
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Enregistrer la déclaration")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._run = run
        self.previous_combo.currentIndexChanged.connect(self._load_previous)
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)
        self.zone_edit.textChanged.connect(lambda: self.confirmation.setChecked(False))
        self.species_spin.valueChanged.connect(lambda: self.confirmation.setChecked(False))
        self.encounter_kind_combo.currentIndexChanged.connect(lambda: self.confirmation.setChecked(False))
        self.outcome_combo.currentIndexChanged.connect(lambda: self.confirmation.setChecked(False))
        self._kind_changed()

    @staticmethod
    def _zone_label(zone):
        if isinstance(zone, dict):
            return str(zone.get("name") or zone.get("zone_name") or zone.get("capture_zone_id") or zone.get("zone_id") or zone.get("id") or "")
        return zone or ""

    def _kind_changed(self):
        self.confirmation.setChecked(False)
        self.encounter_fields.setVisible(self.kind_combo.currentData() == "wild_encounter")

    def _load_previous(self):
        self.confirmation.setChecked(False)
        previous = active_declarations(self._run.history).get(self.previous_combo.currentData())
        self._zone = deepcopy(previous["payload"]["zone"] if previous else self._run.current_zone)
        self._zone_text = self._zone_label(self._zone)
        self.zone_edit.setText(self._zone_text)
        if previous:
            payload = previous["payload"]
            self.kind_combo.setCurrentIndex(self.kind_combo.findData(payload["kind"]))
            if payload["kind"] == "wild_encounter":
                details = payload["details"]
                self.species_spin.setValue(details["species_id"])
                self.encounter_kind_combo.setCurrentIndex(self.encounter_kind_combo.findData(details["encounter_kind"]))
                self.outcome_combo.setCurrentIndex(self.outcome_combo.findData(details["outcome"]))

    def payload(self):
        zone = self.zone_edit.text().strip()
        result = {"kind": self.kind_combo.currentData(), "note": self.note_edit.toPlainText().strip(),
                  "corrects_event_id": self.previous_combo.currentData(), "confirmed": self.confirmation.isChecked(),
                  "zone": deepcopy(self._zone) if zone == self._zone_text else zone or None}
        if result["kind"] == "wild_encounter":
            result["details"] = {"species_id": self.species_spin.value(), "outcome": self.outcome_combo.currentData(),
                                 "encounter_kind": self.encounter_kind_combo.currentData()}
        return result

    def accept(self):
        from app.core.manual_rule_event import validate_declaration
        data = self.payload()
        if not data.pop("confirmed"):
            self.error_label.setText("Confirmez la déclaration manuelle avant de l'enregistrer.")
            return
        try:
            validate_declaration(data, self._run.active_rules,
                                 active_declarations(self._run.history))
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        super().accept()
