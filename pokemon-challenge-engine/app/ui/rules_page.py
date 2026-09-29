"""Catalogue des règles, de leurs dépendances et de leur disponibilité."""

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QWidget

from app.core.catalog import Catalog
from app.ui.widgets.common import STATUS_LABELS, card, label, page_layout


class RulesPage(QWidget):
    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        layout = page_layout(self, "Le catalogue des règles", "Comprendre les contraintes avant de composer votre challenge.")
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher une règle…")
        self.search.setAccessibleName("Rechercher une règle")
        self.game = QComboBox()
        for game in catalog.games.values():
            if game.status == "supported":
                self.game.addItem(game.name, game.id)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.game)
        layout.addLayout(bar)
        layout.addWidget(label("V0.1 • Toutes les règles sont déclaratives. Aucun blocage ni modification du jeu.", "badge"))
        self.entries: list[tuple[QWidget, str, tuple[str, ...]]] = []
        for rule in catalog.rules.values():
            frame, box = card(rule.name)
            box.addWidget(label(rule.description, "subtitle"))
            box.addWidget(label(f"{rule.category}  ·  Difficulté {rule.difficulty}/5  ·  {STATUS_LABELS.get(rule.implementation_status, rule.implementation_status)}", "muted"))
            if rule.requires:
                box.addWidget(label("Nécessite : " + ", ".join(catalog.rules[r].name for r in rule.requires)))
            if rule.conflicts_with:
                box.addWidget(label("Incompatible avec : " + ", ".join(catalog.rules[r].name for r in rule.conflicts_with), "muted"))
            self.entries.append((frame, (rule.name + " " + rule.description).casefold(), rule.supported_games))
            layout.addWidget(frame)
        layout.addStretch()
        self.search.textChanged.connect(self.filter_rules)
        self.game.currentIndexChanged.connect(self.filter_rules)

    def filter_rules(self) -> None:
        term = self.search.text().casefold().strip()
        game_id = self.game.currentData()
        for frame, text, games in self.entries:
            frame.setVisible(term in text and (not games or game_id in games))
