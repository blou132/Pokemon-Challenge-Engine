"""Read-only conditions exported by ZX, never reconstructed from target species."""

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from app.ui.widgets.common import label
from app.ui.widgets.nuzlocke import species_name


def evolution_condition_text(row: dict) -> str:
    if "evolution_conditions" not in row:
        return ("Conditions non enregistrées dans cet ancien rapport. Les espèces cibles seules "
                "ne permettent pas de connaître la méthode. La ROM et la partie restent inchangées.")
    conditions = row["evolution_conditions"]
    if not conditions:
        return "Aucune évolution exposée par ZX pour cette espèce et cette forme."
    lines = []
    for condition in conditions:
        target = species_name(condition["species_id"])
        if condition["form"]:
            target += f" · forme {condition['form']}"
        method, parameter = condition["method"], condition["parameter"]
        if method == "LEVEL" and 1 <= parameter <= 100:
            description = f"Gain de niveau à partir du niveau {parameter}."
        else:
            description = f"Condition non interprétée : méthode {method} ; paramètre ROM {parameter}."
        if method == "LEVEL_IS_EXTRA":
            description += " Création d'un individu supplémentaire, pas évolution de l'individu initial."
        lines.append(f"Vers {target}\n{description}")
    return "\n\n".join(lines)


class DerivedEvolutionsDialog(QDialog):
    def __init__(self, transformation: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Évolutions de la ROM dérivée")
        self.resize(620, 380)
        box = QVBoxLayout(self)
        box.addWidget(label("Données relues dans la ROM et liées à cette partie.\n"
                            "Méthodes exposées par ZX ; cela ne prouve pas une évolution observée en jeu.", "muted"))
        self.species_combo = QComboBox()
        self.rows = sorted(transformation["pokemon"], key=lambda row: (row["species_id"], row["form"]))
        for row in self.rows:
            name = f"{row['species_id']:03d} · {species_name(row['species_id'])}"
            if row["form"]:
                name += f" · forme {row['form']}"
            self.species_combo.addItem(name)
        box.addWidget(self.species_combo)
        self.conditions_view = QTextBrowser()
        box.addWidget(self.conditions_view, 1)
        self.species_combo.currentIndexChanged.connect(self._show_conditions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)
        self._show_conditions(self.species_combo.currentIndex())

    def _show_conditions(self, index):
        self.conditions_view.setPlainText(evolution_condition_text(self.rows[index]) if index >= 0 else
                                         "Données d'évolution indisponibles.")
