"""Consultation des profils et suivi manuel explicitement local."""

from copy import deepcopy
from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSpinBox, QTextBrowser, QWidget,
)

from app.core.catalog import Catalog
from app.core.challenge_engine import ChallengeEngine
from app.core.profile_manager import ProfileManager
from app.models.profile import Profile
from app.ui.challenge_page import challenge_summary
from app.ui.widgets.common import card, label, page_layout


class ProfilePage(QWidget):
    open_requested = Signal(object)
    launch_requested = Signal(object)
    changed = Signal()

    def __init__(self, catalog: Catalog, manager: ProfileManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.manager = manager
        self.selected_profile: Profile | None = None
        layout = page_layout(self, "Vos profils", "Reprenez vos réglages et gardez une trace de votre progression.")
        top = QHBoxLayout()
        self.summary = label("", "subtitle")
        top.addWidget(self.summary, 1)
        refresh = QPushButton("Actualiser")
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
        layout.addLayout(top)
        self.warning = label("", "error")
        self.warning.hide()
        layout.addWidget(self.warning)
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(125)
        self.list_widget.setMaximumHeight(190)
        self.list_widget.currentItemChanged.connect(self.select_profile)
        layout.addWidget(self.list_widget)
        detail, box = card("Configuration sauvegardée")
        self.preview = QTextBrowser()
        self.preview.setMinimumHeight(220)
        box.addWidget(self.preview)
        actions = QHBoxLayout()
        self.open_button = QPushButton("Reprendre les réglages")
        self.open_button.clicked.connect(self.open_selected)
        self.launch_button = QPushButton("Lancer dans DeSmuME")
        self.launch_button.setObjectName("primary")
        self.launch_button.clicked.connect(self.launch_selected)
        actions.addWidget(self.open_button)
        actions.addWidget(self.launch_button)
        actions.addStretch()
        box.addLayout(actions)
        layout.addWidget(detail)
        progress, progress_box = card("Progression manuelle")
        progress_box.addWidget(label("Ces valeurs sont saisies par vous. La V0.1 ne lit pas les données de DeSmuME.", "muted"))
        form = QFormLayout()
        self.badges = QSpinBox()
        self.badges.setRange(0, 8)
        self.captures = QSpinBox()
        self.captures.setRange(0, 9999)
        self.deaths = QSpinBox()
        self.deaths.setRange(0, 9999)
        self.level_cap = QSpinBox()
        self.level_cap.setRange(0, 100)
        self.level_cap.setSpecialValueText("Non défini")
        self.zones = QLineEdit()
        self.zones.setPlaceholderText("Route 1, Arabelle… (séparer par des virgules)")
        for title, field in [("Badges", self.badges), ("Captures", self.captures), ("Morts", self.deaths), ("Level cap courant", self.level_cap), ("Zones", self.zones)]:
            form.addRow(title, field)
        progress_box.addLayout(form)
        self.progress_button = QPushButton("Enregistrer la progression")
        self.progress_button.clicked.connect(self.save_progress)
        progress_box.addWidget(self.progress_button)
        layout.addWidget(progress)
        layout.addStretch()
        self.refresh()

    def refresh(self, *_args: object) -> None:
        previous = self.selected_profile.id if self.selected_profile else None
        self.list_widget.clear()
        profiles = self.manager.list_profiles()
        self.summary.setText(f"{len(profiles)} profil(s) enregistré(s)" if profiles else "Aucun profil pour le moment. Créez et sauvegardez votre premier challenge.")
        self.warning.setText("\n".join(self.manager.warnings))
        self.warning.setVisible(bool(self.manager.warnings))
        chosen = 0
        for index, profile in enumerate(profiles):
            game = self.catalog.games.get(profile.challenge.game_id)
            item = QListWidgetItem(f"{profile.name}   ·   {game.name if game else profile.challenge.game_id}   ·   Seed {profile.challenge.seed}")
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            item.setToolTip(f"Créé le {profile.challenge.created_at}\n{profile.id}")
            self.list_widget.addItem(item)
            if profile.id == previous:
                chosen = index
        if profiles:
            self.list_widget.setCurrentRow(chosen)
        else:
            self.select_profile(None)

    def select_profile(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        self.selected_profile = None
        for button in (self.open_button, self.launch_button, self.progress_button):
            button.setEnabled(False)
        if current is None:
            self.preview.setPlainText("Sélectionnez un profil pour consulter son challenge.")
            return
        try:
            profile = self.manager.load(current.data(Qt.ItemDataRole.UserRole))
            errors = ChallengeEngine(self.catalog).validate(profile.challenge)
            if errors:
                raise ValueError("Profil incompatible avec le catalogue :\n" + "\n".join(errors))
        except (ValueError, OSError) as exc:
            self.preview.setPlainText(str(exc))
            return
        self.selected_profile = profile
        self.preview.setPlainText(challenge_summary(profile.challenge, self.catalog))
        progress = profile.progress
        self.badges.setValue(len(progress["badges"]))
        self.captures.setValue(len(progress["captures"]))
        self.deaths.setValue(len(progress["deaths"]))
        self.level_cap.setValue(progress["current_level_cap"] or 0)
        self.zones.setText(", ".join(progress["zones"]))
        for button in (self.open_button, self.launch_button, self.progress_button):
            button.setEnabled(True)

    def open_selected(self) -> None:
        if self.selected_profile:
            self.open_requested.emit(self.selected_profile)

    def launch_selected(self) -> None:
        if self.selected_profile:
            self.launch_requested.emit(self.selected_profile.challenge)

    def save_progress(self) -> None:
        if self.selected_profile is None:
            return
        if QMessageBox.question(self, "Enregistrer la progression", "Remplacer la progression de ce profil par les valeurs affichées ?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        profile = deepcopy(self.selected_profile)
        progress = profile.progress
        # Préserver les entrées détaillées existantes lors d'un simple ajustement.
        for key, count in [("badges", self.badges.value()), ("captures", self.captures.value()), ("deaths", self.deaths.value())]:
            values = progress[key][:count]
            while len(values) < count:
                values.append(f"Badge {len(values) + 1}" if key == "badges" else {"manual": True})
            progress[key] = values
        progress["zones"] = list(dict.fromkeys(zone.strip() for zone in self.zones.text().split(",") if zone.strip()))
        progress["current_level_cap"] = self.level_cap.value() or None
        profile.history.append({"event": "manual_progress_update", "at": datetime.now(timezone.utc).isoformat()})
        try:
            self.manager.save(profile)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Progression non enregistrée", str(exc))
            return
        self.refresh()
        self.changed.emit()

