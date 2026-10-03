"""Persistent run library, independent from reusable challenge profiles."""

from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from app.ui.run_dialogs import (
    RunDetailsDialog, STATUS_LABELS, active_deaths, badges_text, display_date,
    display_duration, rule_names, zone_name,
)
from app.ui.widgets.common import card, label, page_layout


class RunCard(QWidget):
    resume_requested = Signal(str)
    details_requested = Signal(str)

    def __init__(self, run, catalog, *, active=False, parent=None):
        super().__init__(parent)
        self.run_id = run.run_id
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame, box = card()
        outer.addWidget(frame)
        game = catalog.games.get(run.game_id)
        top = QHBoxLayout()
        top.addWidget(label(game.name if game else run.game_id, "eyebrow"), 1)
        self.status_label = label("PARTIE ACTIVE" if active else STATUS_LABELS.get(run.status, run.status).upper(), "badge")
        top.addWidget(self.status_label)
        box.addLayout(top)
        self.name_label = label(run.name, "sectionTitle")
        box.addWidget(self.name_label)
        deaths = active_deaths(run)
        badges = badges_text(run)
        captures = str(len(run.captures)) if run.captures is not None else "Non renseigné"
        mortality = str(len(deaths)) if deaths is not None else "Non renseigné"
        self.stats_label = label(f"Temps : {display_duration(run.total_play_seconds)}   ·   Badges : {badges} (manuel)\n"
                                 f"Captures : {captures} (manuel)   ·   Morts : {mortality}\n"
                                 f"Zone : {zone_name(run.current_zone)}   ·   Dernière session : {display_date(run.last_played_at)}", "muted")
        box.addWidget(self.stats_label)
        self.rules_label = label(" · ".join(rule_names(run, catalog)) or "Classique · aucune règle", "muted")
        box.addWidget(self.rules_label)
        actions = QHBoxLayout()
        self.resume_button = QPushButton("Reprendre")
        self.resume_button.setObjectName("primary")
        self.resume_button.setEnabled(run.status in ("preparing", "active"))
        self.resume_button.setToolTip("Reprend cette partie et vérifie son environnement de jeu." if self.resume_button.isEnabled()
                                      else "Modifiez d'abord le statut dans Détails pour reprendre cette partie.")
        self.resume_button.clicked.connect(lambda: self.resume_requested.emit(self.run_id))
        details = QPushButton("Détails")
        details.clicked.connect(lambda: self.details_requested.emit(self.run_id))
        actions.addWidget(self.resume_button)
        actions.addWidget(details)
        actions.addStretch()
        box.addLayout(actions)


class RunsPage(QWidget):
    new_requested = Signal()
    resume_requested = Signal(str)
    saves_requested = Signal(str)
    action_requested = Signal(str, str, object)

    def __init__(self, catalog, manager, parent=None):
        super().__init__(parent)
        self.catalog, self.manager = catalog, manager
        self.runs = []
        self.cards = []
        self.visible_run_ids = []
        self.active_run_id = None
        self._dialogs = {}
        layout = page_layout(self, "Mes parties", "Retrouvez chaque aventure avec ses propres règles, son équipe et son historique.")
        row = QHBoxLayout()
        self.summary = label("", "muted")
        row.addWidget(self.summary, 1)
        self.new_button = QPushButton("Nouvelle partie")
        self.new_button.setObjectName("primary")
        self.new_button.clicked.connect(self.new_requested)
        row.addWidget(self.new_button)
        refresh = QPushButton("Actualiser")
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        layout.addLayout(row)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Rechercher une partie par son nom")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._render)
        layout.addWidget(self.search_edit)
        filters = QGridLayout()
        self.generation_combo = QComboBox()
        self.game_combo = QComboBox()
        self.challenge_combo = QComboBox()
        self.status_combo = QComboBox()
        self.sort_combo = QComboBox()
        self.generation_combo.addItem("Toutes les générations", None)
        for generation in sorted({game.generation for game in catalog.games.values()}):
            self.generation_combo.addItem(f"Génération {generation}", generation)
        self.game_combo.addItem("Tous les jeux", None)
        for game in catalog.games.values():
            self.game_combo.addItem(game.name, game.id)
        self.challenge_combo.addItem("Tous les challenges", None)
        self.challenge_combo.addItem("Classique", "classic")
        for key in ("nuzlocke", "monotype", "permanent_death"):
            if key in catalog.rules:
                self.challenge_combo.addItem(catalog.rules[key].name, key)
        self.challenge_combo.addItem("Autres challenges", "other")
        self.status_combo.addItem("Tous les statuts", None)
        for key, text in STATUS_LABELS.items():
            self.status_combo.addItem(text, key)
        for text, key in (("Dernière session", "last_played"), ("Création", "created"), ("Nom", "name"), ("Temps de jeu", "time")):
            self.sort_combo.addItem(text, key)
        for column, combo in enumerate((self.generation_combo, self.game_combo, self.challenge_combo, self.status_combo)):
            filters.addWidget(combo, 0, column)
            combo.currentIndexChanged.connect(self._render)
        filters.addWidget(label("Trier par", "muted"), 1, 2)
        filters.addWidget(self.sort_combo, 1, 3)
        self.sort_combo.currentIndexChanged.connect(self._render)
        layout.addLayout(filters)
        self.warning = label("", "error")
        self.warning.hide()
        layout.addWidget(self.warning)
        self.empty_label = label("", "muted")
        layout.addWidget(self.empty_label)
        self.cards_layout = QVBoxLayout()
        self.cards_layout.setSpacing(12)
        layout.addLayout(self.cards_layout)
        layout.addStretch()
        self.refresh()

    def set_active_run(self, run_id):
        self.active_run_id = run_id
        self._render()

    def refresh(self, *_args):
        try:
            self.runs = self.manager.list_runs()
            warnings = self.manager.warnings
            self.warning.setText("\n".join(warnings))
            self.warning.setVisible(bool(warnings))
            # Include future generations already present in persistent runs.
            for run in self.runs:
                if self.generation_combo.findData(run.generation) < 0:
                    self.generation_combo.addItem(f"Génération {run.generation}", run.generation)
                if self.game_combo.findData(run.game_id) < 0:
                    self.game_combo.addItem(run.game_id, run.game_id)
        except (OSError, ValueError) as exc:
            self.warning.setText(str(exc))
            self.warning.show()
        self._render()
        for dialog in list(self._dialogs.values()):
            if dialog.isVisible():
                dialog.refresh()

    refresh_visible = refresh

    def _matches(self, run):
        if self.search_edit.text().strip().casefold() not in run.name.casefold():
            return False
        if self.generation_combo.currentData() not in (None, run.generation):
            return False
        if self.game_combo.currentData() not in (None, run.game_id):
            return False
        if self.status_combo.currentData() not in (None, run.status):
            return False
        challenge = self.challenge_combo.currentData()
        rules = run.rules_snapshot.get("active_rules", [])
        if challenge == "classic":
            return not rules
        if challenge == "other":
            return bool(rules) and not {"nuzlocke", "monotype", "permanent_death"}.intersection(rules)
        return challenge is None or challenge in rules

    def _render(self, *_args):
        if not hasattr(self, "cards_layout"):
            return
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.cards.clear()
        runs = [run for run in self.runs if self._matches(run)]
        sorting = self.sort_combo.currentData()
        stamp = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() if value else 0
        keys = {"last_played": lambda run: stamp(run.last_played_at), "created": lambda run: stamp(run.created_at),
                "name": lambda run: run.name.casefold(), "time": lambda run: run.total_play_seconds}
        runs.sort(key=keys.get(sorting, keys["last_played"]), reverse=sorting != "name")
        self.visible_run_ids = [run.run_id for run in runs]
        self.summary.setText(f"{len(runs)} partie(s) affichée(s) · {len(self.runs)} enregistrée(s)")
        self.empty_label.setText("Aucune partie pour le moment. Créez une partie Classique ou commencez depuis un profil."
                                 if not self.runs else "Aucune partie ne correspond à ces filtres.")
        self.empty_label.setVisible(not runs)
        for run in runs:
            widget = RunCard(run, self.catalog, active=run.run_id == self.active_run_id)
            widget.resume_requested.connect(self.resume_requested)
            widget.details_requested.connect(self.open_details)
            self.cards_layout.addWidget(widget)
            self.cards.append(widget)

    def open_details(self, run_id):
        dialog = self._dialogs.get(run_id)
        if dialog is None:
            dialog = RunDetailsDialog(self.catalog, self.manager, run_id, self)
            dialog.resume_requested.connect(self.resume_requested)
            dialog.saves_requested.connect(self.saves_requested)
            dialog.action_requested.connect(self.action_requested)
            self._dialogs[run_id] = dialog
        else:
            dialog.refresh()
        dialog.show()
        dialog.raise_()
        return dialog
