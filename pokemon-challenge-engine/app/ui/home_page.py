"""Accueil sobre : jeux disponibles et accès aux parcours principaux."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from app import __version__
from app.core.catalog import Catalog
from app.ui.widgets.common import card, label, page_layout


class HomePage(QWidget):
    create_requested = Signal(str)
    profiles_requested = Signal()

    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = page_layout(self, "À vous de jouer", "Un point de départ pour toutes vos prochaines aventures.")
        hero, box = card()
        hero.setObjectName("hero")
        box.setContentsMargins(30, 28, 30, 28)
        box.addWidget(label(f"POKEMON CHALLENGE ENGINE   /   V{__version__}", "eyebrow"))
        box.addSpacing(8)
        box.addWidget(label("Votre prochaine aventure,\nvos propres règles.", "heroTitle"))
        box.addWidget(label("De la première idée au profil prêt à lancer : composez un Nuzlocke,\ntentez un Monotype ou laissez le hasard décider.", "subtitle"))
        box.addSpacing(12)
        actions = QHBoxLayout()
        create = QPushButton("Créer un challenge  →")
        create.setObjectName("primary")
        create.clicked.connect(lambda: self.create_requested.emit("black"))
        saved = QPushButton("Mes profils")
        saved.clicked.connect(self.profiles_requested)
        actions.addWidget(create)
        actions.addWidget(saved)
        actions.addStretch()
        box.addLayout(actions)
        layout.addWidget(hero)
        layout.addWidget(label("Choisissez votre terrain de jeu", "sectionTitle"))
        games_row = QHBoxLayout()
        games_row.setSpacing(18)
        for index, game in enumerate(g for g in catalog.games.values() if g.status == "supported"):
            frame, game_box = card()
            game_box.addWidget(label(f"0{index + 1}   /   NINTENDO DS", "eyebrow"))
            game_box.addWidget(label(game.name, "sectionTitle"))
            game_box.addWidget(label(f"Génération {game.generation}  ·  {game.type_count} types  ·  Prêt à configurer", "muted"))
            button = QPushButton("Préparer une partie  →")
            button.clicked.connect(lambda _checked=False, game_id=game.id: self.create_requested.emit(game_id))
            game_box.addWidget(button)
            games_row.addWidget(frame, 1)
        layout.addLayout(games_row)
        stats = QHBoxLayout()
        for value, title, description in [(str(len(catalog.rules)), "Règles configurables", "Obligatoires, possibles ou interdites."), (str(len(catalog.types)), "Types pour votre Monotype", "Une roue animée, un tirage reproductible."), ("100 %", "Préparation locale", "Vos profils restent sur cet ordinateur.")]:
            frame, stat_box = card()
            stat_box.addWidget(label(value, "title"))
            stat_box.addWidget(label(title, "sectionTitle"))
            stat_box.addWidget(label(description, "muted"))
            stats.addWidget(frame, 1)
        layout.addLayout(stats)
        self.profile_count = label("", "subtitle")
        layout.addWidget(self.profile_count)
        layout.addWidget(label(f"V{__version__} · Les règles restent à respecter manuellement dans le jeu. La page Connexion DeSmuME affiche les données transmises par Lua.", "badge"))
        layout.addStretch()

