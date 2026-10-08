"""Accueil sobre : jeux disponibles et accès aux parcours principaux."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPushButton, QWidget

from app import __version__
from app.core.catalog import Catalog
from app.ui.widgets.common import INSTALLATION_LABELS, card, label, page_layout


class HomePage(QWidget):
    create_requested = Signal(str)
    runs_requested = Signal()

    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.game_states = {}
        layout = page_layout(self, "À vous de jouer", "Un point de départ pour toutes vos prochaines aventures.")
        hero, box = card()
        hero.setObjectName("hero")
        box.setContentsMargins(30, 28, 30, 28)
        box.addWidget(label(f"POKEMON CHALLENGE ENGINE   /   V{__version__}", "eyebrow"))
        box.addSpacing(8)
        box.addWidget(label("Votre prochaine aventure,\nvos propres règles.", "heroTitle"))
        box.addWidget(label("Créez une partie classique, utilisez un modèle de challenge\nou composez vos propres règles.", "subtitle"))
        box.addSpacing(12)
        actions = QHBoxLayout()
        create = QPushButton("Nouvelle partie  →")
        create.setObjectName("primary")
        create.clicked.connect(lambda: self.create_requested.emit("black"))
        saved = QPushButton("Mes parties")
        saved.clicked.connect(self.runs_requested)
        actions.addWidget(create)
        actions.addWidget(saved)
        actions.addStretch()
        box.addLayout(actions)
        layout.addWidget(hero)
        layout.addWidget(label("Choisissez votre terrain de jeu", "sectionTitle"))
        games_row = QGridLayout()
        games_row.setSpacing(18)
        for index, game in enumerate(g for g in catalog.games.values() if g.status == "supported"):
            frame, game_box = card()
            game_box.addWidget(label(f"0{index + 1}   /   NINTENDO DS", "eyebrow"))
            game_box.addWidget(label(game.name, "sectionTitle"))
            game_box.addWidget(label(f"Génération {game.generation}  ·  {game.type_count} types  ·  Prêt à configurer", "muted"))
            status = label("Installation · À vérifier", "muted")
            self.game_states[game.id] = status
            game_box.addWidget(status)
            button = QPushButton("Préparer une partie  →")
            button.clicked.connect(lambda _checked=False, game_id=game.id: self.create_requested.emit(game_id))
            game_box.addWidget(button)
            games_row.addWidget(frame, index // 2, index % 2)
        layout.addLayout(games_row)
        stats = QHBoxLayout()
        for value, title, description in [(str(len(catalog.rules)), "Règles configurables", "Obligatoires, possibles ou interdites."), (str(len(catalog.types)), "Types pour votre Monotype", "Une roue animée, un tirage reproductible."), ("100 %", "Préparation locale", "Vos parties restent sur cet ordinateur.")]:
            frame, stat_box = card()
            stat_box.addWidget(label(value, "title"))
            stat_box.addWidget(label(title, "sectionTitle"))
            stat_box.addWidget(label(description, "muted"))
            stats.addWidget(frame, 1)
        layout.addLayout(stats)
        self.model_count = label("", "subtitle")
        layout.addWidget(self.model_count)
        layout.addWidget(label(f"V{__version__} · Les règles restent à respecter manuellement dans le jeu. La page Connexion DeSmuME affiche les données transmises par Lua.", "badge"))
        layout.addStretch()

    def set_detection_state(self, report):
        for game_id, widget in self.game_states.items():
            state = report.get("game_states", {}).get(game_id, {})
            widget.setText(INSTALLATION_LABELS.get(state.get("status"), "À vérifier"))
            widget.setToolTip(state.get("message", report.get("error", "")))

