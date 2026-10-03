"""Run forms and read-only details; all mutations go through the owner controller."""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QLineEdit, QListWidget, QListWidgetItem,
    QInputDialog, QMessageBox, QPushButton, QScrollArea, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from app.ui.widgets.common import label
from app.ui.widgets.nuzlocke import species_name
from app.services.save_manager_service import SaveManagerService


STATUS_LABELS = {"preparing": "Préparation", "active": "En cours", "finished": "Terminée",
                 "abandoned": "Abandonnée", "archived": "Archivée"}
SOURCE_LABELS = {"automatic": "Automatique", "manual": "Manuel", "system": "Système"}
EVENT_LABELS = {
    "run_created": "Partie créée", "run_started": "Partie commencée", "run_resumed": "Partie reprise",
    "session_started": "Session commencée", "session_ended": "Session terminée",
    "zone_changed": "Zone modifiée", "party_changed": "Équipe mise à jour",
    "pokemon_fainted": "Pokémon K.O.", "pokemon_marked_dead": "Mort permanente enregistrée",
    "manual_capture": "Capture enregistrée", "manual_badge": "Badges renseignés",
    "badge_added": "Badge ajouté", "manual_death": "Mort enregistrée manuellement",
    "note_added": "Note ajoutée", "status_changed": "Statut modifié",
    "backup_created": "Backup créé", "death_corrected": "Mort corrigée",
    "pokemon_evolved": "Évolution observée", "death_confirmation_required": "Mort à confirmer",
}


def display_date(value):
    if not value:
        return "Non renseignée"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError, AttributeError):
        return str(value)


def display_duration(seconds):
    total = max(0, int(seconds or 0))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def zone_name(zone):
    if isinstance(zone, dict):
        return str(zone.get("name") or zone.get("zone_name") or zone.get("zone_id") or zone.get("id") or "Non renseignée")
    return str(zone) if zone else "Non renseignée"


def pokemon_name(pokemon):
    if isinstance(pokemon, str):
        return pokemon
    return str(pokemon.get("name") or pokemon.get("species_name") or species_name(pokemon.get("species_id")))


def active_deaths(run):
    return None if run.deaths is None else [death for death in run.deaths if not death.get("corrected", False)]


def rule_names(run, catalog):
    names = []
    for key in run.rules_snapshot.get("active_rules", []):
        name = catalog.rules[key].name if key in catalog.rules else key
        if key == "monotype" and run.rules_snapshot.get("monotype"):
            chosen = run.rules_snapshot["monotype"]["type_id"]
            name += " " + next((item["name"] for item in catalog.types if item["id"] == chosen), chosen)
        names.append(name)
    return names


def badge_limit(run):
    return 8 if run.generation == 5 else 99


def badges_text(run):
    if run.badges is None:
        return "Non renseigné"
    return f"{run.badges} / 8" if run.generation == 5 else str(run.badges)


def prompt_run_action(parent, catalog, run, action):
    """Reusable explicit input for library details and Mode Jeu quick actions."""
    if action in ("manual_capture", "manual_death", "add_note"):
        dialog = ManualRunEventDialog(action, run, parent)
        return dialog.payload() if dialog.exec() == QDialog.DialogCode.Accepted else None
    if action == "set_badges":
        count, accepted = QInputDialog.getInt(parent, "Badges — saisie manuelle", "Nombre de badges renseignés pour cette partie", run.badges or 0, 0, badge_limit(run))
        return {"count": count} if accepted else None
    raise ValueError("Action de partie inconnue.")


class NewRunDialog(QDialog):
    """Select a source and file references, without creating or altering a save."""

    def __init__(self, catalog, profiles, launch_profiles, parent=None, *, profile=None):
        super().__init__(parent)
        self.catalog = catalog
        self.profiles = list(profiles)
        self.launch_profiles = deepcopy(launch_profiles)
        self.setWindowTitle("Nouvelle partie")
        self.resize(640, 540)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Commencer une partie", "title"))
        layout.addWidget(label("Chaque partie conserve ses propres règles et sa progression PCE. Un profil reste une configuration réutilisable.", "muted"))
        form = QFormLayout()
        self.game_combo = QComboBox()
        for game in catalog.games.values():
            if game.status == "supported":
                self.game_combo.addItem(game.name, game.id)
        self.profile_combo = QComboBox()
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(100)
        self.save_edit = QLineEdit()
        self.save_edit.setPlaceholderText("Facultatif : fichier .dsv déjà existant")
        save_row = QHBoxLayout()
        save_row.addWidget(self.save_edit, 1)
        browse = QPushButton("Choisir…")
        browse.clicked.connect(self._browse_save)
        save_row.addWidget(browse)
        form.addRow("Jeu", self.game_combo)
        form.addRow("Configuration", self.profile_combo)
        form.addRow("Nom de la partie", self.name_edit)
        form.addRow("Sauvegarde Pokémon", save_row)
        layout.addLayout(form)
        self.environment_label = label("", "muted")
        self.rules_label = label("", "muted")
        layout.addWidget(self.rules_label)
        layout.addWidget(self.environment_label)
        layout.addWidget(label("L'environnement enregistré sera repris. La sauvegarde Pokémon est seulement liée : PCE n'en crée pas une nouvelle et ne force aucune sauvegarde en jeu.", "muted"))
        self.error_label = label("", "error")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        layout.addStretch()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Créer la partie")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.game_combo.currentIndexChanged.connect(self._game_changed)
        self.profile_combo.currentIndexChanged.connect(self._source_changed)
        self._game_changed()
        if profile is not None:
            index = self.game_combo.findData(profile.challenge.game_id)
            if index >= 0:
                self.game_combo.setCurrentIndex(index)
                self.profile_combo.setCurrentIndex(self.profile_combo.findData(profile.id))
                self.name_edit.setText(profile.name)

    def _game_changed(self):
        game_id = self.game_combo.currentData()
        self.profile_combo.clear()
        self.profile_combo.addItem("Classique · aucune règle", None)
        for profile in self.profiles:
            if profile.challenge.game_id == game_id:
                self.profile_combo.addItem(profile.name, profile.id)
        settings = self.launch_profiles.get(game_id, {})
        self.save_edit.setText(settings.get("save_path", ""))
        configured = bool(settings.get("rom_path") and settings.get("emulator_path"))
        self.environment_label.setText("Environnement : configuration enregistrée pour ce jeu ; vérification avant lancement."
                                       if configured else "Environnement : à préparer dans Installation & Diagnostic avant le lancement.")
        self._source_changed()

    def _source_changed(self):
        selected = next((item for item in self.profiles if item.id == self.profile_combo.currentData()), None)
        names = [self.catalog.rules[key].name if key in self.catalog.rules else key
                 for key in selected.challenge.active_rules] if selected else []
        self.rules_label.setText("Copie des règles du profil : " + (", ".join(names) or "aucune règle")
                                 if selected else "Classique : 0 règle active. Temps, équipe, zone et événements restent disponibles.")
        if not self.name_edit.isModified():
            self.name_edit.setText(selected.name if selected else self.game_combo.currentText() + " — Classique")

    def _browse_save(self):
        path, _ = QFileDialog.getOpenFileName(self, "Lier une sauvegarde existante", self.save_edit.text(), "Sauvegardes DeSmuME (*.dsv)")
        if path:
            self.save_edit.setText(path)

    def selection(self):
        game_id = self.game_combo.currentData()
        launch = deepcopy(self.launch_profiles.get(game_id))
        save = self.save_edit.text().strip() or None
        if launch is not None:
            launch["save_path"] = save or ""
        return {"name": self.name_edit.text().strip(), "game_id": game_id,
                "profile_id": self.profile_combo.currentData(), "save_path": save,
                "launch_profile": launch}

    def accept(self):
        if not self.selection()["name"] or not self.selection()["game_id"]:
            self.error_label.setText("Choisissez un jeu et donnez un nom à cette partie.")
            self.error_label.show()
            return
        if "\0" in self.save_edit.text():
            self.error_label.setText("Le chemin de sauvegarde est invalide.")
            self.error_label.show()
            return
        super().accept()


class ManualRunEventDialog(QDialog):
    """Explicit manual input never claims an observed capture or stable identity."""

    def __init__(self, action, run, parent=None):
        super().__init__(parent)
        if action not in ("manual_capture", "manual_death", "add_note"):
            raise ValueError("Action manuelle inconnue.")
        self.action = action
        self.setWindowTitle({"manual_capture": "Ajouter une capture", "manual_death": "Enregistrer une mort", "add_note": "Ajouter une note"}[action])
        self.resize(540, 390)
        layout = QVBoxLayout(self)
        layout.addWidget(label(self.windowTitle(), "sectionTitle"))
        layout.addWidget(label("SAISIE MANUELLE · données PCE uniquement", "eyebrow"))
        form = QFormLayout()
        self.pokemon_combo = QComboBox()
        self.pokemon_combo.setEditable(True)
        self.pokemon_combo.addItem("", None)
        for number, (key, pokemon) in enumerate(run.known_pokemon.items(), 1):
            suffix = f"N{pokemon['level']}" if pokemon.get("level") is not None else "niveau inconnu"
            slot = pokemon.get("slot")
            suffix += f" · emplacement {slot}" if slot is not None else ""
            self.pokemon_combo.addItem(f"{pokemon_name(pokemon)} · {suffix} · individu {number}", key)
        self.pokemon_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.pokemon_combo.lineEdit().setPlaceholderText("Sélectionnez un individu connu ou saisissez un nom")
        self.zone_edit = QLineEdit("" if run.current_zone is None else zone_name(run.current_zone))
        self.date_edit = QDateTimeEdit(QDateTime.currentDateTime())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("Note ou cause facultative" if action != "add_note" else "Votre note")
        self.note_edit.setMaximumHeight(130)
        if action != "add_note":
            form.addRow("Pokémon", self.pokemon_combo)
            form.addRow("Zone", self.zone_edit)
            form.addRow("Date", self.date_edit)
        form.addRow("Note", self.note_edit)
        layout.addLayout(form)
        self.error_label = label("", "error")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.run = run

    def payload(self):
        if self.action == "add_note":
            return {"text": self.note_edit.toPlainText().strip()}
        values = {"zone": self.zone_edit.text().strip() or None,
                  "date": self.date_edit.dateTime().toPython().astimezone().isoformat(),
                  "note": self.note_edit.toPlainText().strip()}
        index = self.pokemon_combo.currentIndex()
        # Editable combo can retain an old index after the text was replaced.
        known = (index >= 0 and self.pokemon_combo.currentText() == self.pokemon_combo.itemText(index)
                 and self.pokemon_combo.currentData() is not None)
        if known:
            key = self.pokemon_combo.currentData()
            if self.action == "manual_death":
                values["pokemon_key"] = key
            else:
                values["pokemon"] = deepcopy(self.run.known_pokemon[key])
        else:
            values["pokemon"] = self.pokemon_combo.currentText().strip()
        return values

    def accept(self):
        data = self.payload()
        if (self.action == "add_note" and not data["text"]) or (self.action != "add_note" and not data.get("pokemon_key") and not data.get("pokemon")):
            self.error_label.setText("Renseignez la note." if self.action == "add_note" else "Sélectionnez ou nommez le Pokémon concerné.")
            self.error_label.show()
            return
        if len(self.note_edit.toPlainText()) > 10000:
            self.error_label.setText("La note doit contenir au plus 10 000 caractères.")
            self.error_label.show()
            return
        super().accept()


class RunDetailsDialog(QDialog):
    action_requested = Signal(str, str, object)
    resume_requested = Signal(str)
    saves_requested = Signal(str)

    def __init__(self, catalog, manager, run_id, parent=None):
        super().__init__(parent)
        self.catalog, self.manager, self.run_id = catalog, manager, run_id
        self.setWindowTitle("Détails de la partie")
        self.resize(930, 670)
        self.setMinimumSize(620, 440)
        layout = QVBoxLayout(self)
        self.title_label = label("", "title")
        layout.addWidget(self.title_label)
        self.error_label = label("", "error")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._tab_layouts = {}
        for name in ("Aperçu", "Progression", "Équipe", "Règles", "Historique", "Sauvegardes"):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            content.setObjectName("page")
            box = QVBoxLayout(content)
            box.setContentsMargins(18, 16, 18, 16)
            scroll.setWidget(content)
            self.tabs.addTab(scroll, name)
            self._tab_layouts[name] = box
        self._build_overview()
        self._build_progress()
        self._build_team()
        self._build_rules()
        self._build_history()
        self._build_saves()
        self.tabs.currentChanged.connect(lambda index: self._refresh_backup(force=True) if index == 5 else None)
        row = QHBoxLayout()
        self.resume_button = QPushButton("Reprendre cette partie")
        self.resume_button.setObjectName("primary")
        self.resume_button.clicked.connect(lambda: self.resume_requested.emit(self.run_id))
        close = QPushButton("Fermer")
        close.clicked.connect(self.close)
        row.addWidget(self.resume_button)
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        self.refresh()

    @staticmethod
    def _table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().hide()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setMinimumHeight(220)
        return table

    def _build_overview(self):
        box = self._tab_layouts["Aperçu"]
        self.overview = label("")
        box.addWidget(self.overview)
        status_row = QHBoxLayout()
        self.status_combo = QComboBox()
        for key, text in STATUS_LABELS.items():
            self.status_combo.addItem(text, key)
        change = QPushButton("Modifier le statut…")
        change.clicked.connect(self._change_status)
        status_row.addWidget(self.status_combo)
        status_row.addWidget(change)
        status_row.addStretch()
        box.addLayout(status_row)
        note = QPushButton("Ajouter une note")
        note.clicked.connect(lambda: self.manual_action("add_note"))
        box.addWidget(note)
        self.notes_view = QTextBrowser()
        box.addWidget(self.notes_view, 1)

    def _build_progress(self):
        box = self._tab_layouts["Progression"]
        self.progress_label = label("")
        box.addWidget(self.progress_label)
        row = QHBoxLayout()
        self.badge_minus = QPushButton("− Badge")
        self.badge_plus = QPushButton("+ Badge")
        self.badge_minus.clicked.connect(lambda: self._badge(-1))
        self.badge_plus.clicked.connect(lambda: self._badge(1))
        row.addWidget(self.badge_minus)
        row.addWidget(self.badge_plus)
        row.addWidget(label("MANUEL", "eyebrow"))
        row.addStretch()
        box.addLayout(row)
        row = QHBoxLayout()
        self.capture_button = QPushButton("Ajouter une capture")
        self.capture_button.clicked.connect(lambda: self.manual_action("manual_capture"))
        self.death_button = QPushButton("Enregistrer une mort")
        self.death_button.clicked.connect(lambda: self.manual_action("manual_death"))
        row.addWidget(self.capture_button)
        row.addWidget(self.death_button)
        box.addLayout(row)
        self.pending_label = label("", "error")
        box.addWidget(self.pending_label)
        self.pending_list = QListWidget()
        self.pending_list.setMaximumHeight(115)
        box.addWidget(self.pending_list)
        self.pending_button = QPushButton("Vérifier / confirmer la mort sélectionnée…")
        self.pending_button.clicked.connect(self._confirm_pending)
        box.addWidget(self.pending_button)
        box.addWidget(label("Cimetière virtuel PCE", "sectionTitle"))
        box.addWidget(label("Un Pokémon mort reste dans cette partie même après un soin ou son départ de l'équipe. Aucune boîte PC ni sauvegarde Pokémon n'est modifiée.", "muted"))
        self.graveyard = QListWidget()
        self.graveyard.setMinimumHeight(150)
        box.addWidget(self.graveyard, 1)
        self.correction_button = QPushButton("Annuler / corriger la mort sélectionnée…")
        self.correction_button.clicked.connect(self._correct_death)
        box.addWidget(self.correction_button)

    def _build_team(self):
        box = self._tab_layouts["Équipe"]
        box.addWidget(label("Dernière équipe observée", "sectionTitle"))
        box.addWidget(label("L'état vivant / mort appartient à la partie PCE. Les PV représentent la dernière observation du jeu.", "muted"))
        self.team_table = self._table(("Pokémon", "Niveau", "PV / max", "Statut PCE"))
        box.addWidget(self.team_table)
        self.team_note = label("", "muted")
        box.addWidget(self.team_note)
        box.addStretch()

    def _build_rules(self):
        box = self._tab_layouts["Règles"]
        self.rules_view = QTextBrowser()
        box.addWidget(self.rules_view, 1)
        self.technical_button = QPushButton("Détails techniques du snapshot")
        self.technical_button.setCheckable(True)
        self.technical_view = QTextBrowser()
        self.technical_view.hide()
        self.technical_button.toggled.connect(self.technical_view.setVisible)
        box.addWidget(self.technical_button)
        box.addWidget(self.technical_view, 1)

    def _build_history(self):
        box = self._tab_layouts["Historique"]
        box.addWidget(label("Chronologie conservée, y compris après correction d'une mort.", "muted"))
        self.history_table = self._table(("Date", "Événement", "Source", "Détails"))
        box.addWidget(self.history_table, 1)

    def _build_saves(self):
        box = self._tab_layouts["Sauvegardes"]
        box.addWidget(label("Progression PCE", "sectionTitle"))
        box.addWidget(label("Règles, temps, équipe, notes et historique sont enregistrés automatiquement dans le stockage persistant des parties. Ils ne sont pas une sauvegarde du jeu.", "muted"))
        box.addWidget(label("Sauvegarde Pokémon DeSmuME", "sectionTitle"))
        self.save_label = label("")
        self.backup_label = label("Dernier backup : Non renseigné", "muted")
        self._backup_context = None
        self._backup_summary = None
        box.addWidget(self.save_label)
        box.addWidget(self.backup_label)
        button = QPushButton("Ouvrir le gestionnaire de sauvegardes")
        button.clicked.connect(lambda: self.saves_requested.emit(self.run_id))
        box.addWidget(button)
        box.addWidget(label("PCE ne déclenche pas de sauvegarde en jeu. Les backups et restaurations utilisent le gestionnaire existant.", "muted"))
        box.addStretch()

    def refresh(self):
        try:
            self.set_run(self.manager.load(self.run_id))
        except (OSError, ValueError) as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()
            self.resume_button.setEnabled(False)

    def set_run(self, run):
        self.run = run
        self.error_label.hide()
        self.title_label.setText(run.name)
        game = self.catalog.games.get(run.game_id)
        rules = rule_names(run, self.catalog)
        challenge = ", ".join(rules) or "Classique"
        self.overview.setText(f"{game.name if game else run.game_id} · Génération {run.generation}\n"
                              f"{challenge}\nStatut : {STATUS_LABELS.get(run.status, run.status)}\n"
                              f"Début : {display_date(run.started_at)}\nDernière session : {display_date(run.last_played_at)}\n"
                              f"Temps de jeu suivi : {display_duration(run.total_play_seconds)}")
        self.status_combo.setCurrentIndex(self.status_combo.findData(run.status))
        self.resume_button.setEnabled(run.status not in ("finished", "abandoned", "archived"))
        notes = [f"{display_date(note.get('timestamp') or note.get('date'))} · {note.get('text', note.get('note', ''))}"
                 if isinstance(note, dict) else str(note) for note in run.notes]
        self.notes_view.setPlainText("\n\n".join(notes) or "Aucune note enregistrée.")
        deaths = active_deaths(run)
        badges = badges_text(run)
        captures = str(len(run.captures)) if run.captures is not None else "Non renseigné"
        death_count = str(len(deaths)) if deaths is not None else "Non renseigné"
        self.progress_label.setText(f"Badges : {badges} · MANUEL\nCaptures : {captures} · MANUEL\n"
                                   f"Morts : {death_count}\nZone : {zone_name(run.current_zone)}")
        self.badge_minus.setEnabled(run.badges is not None and run.badges > 0)
        self.badge_plus.setEnabled(run.badges is None or run.badges < badge_limit(run))
        self.graveyard.clear()
        for death in deaths or []:
            pokemon = death.get("pokemon", {})
            level = pokemon.get("level") if isinstance(pokemon, dict) else None
            text = f"☠ {pokemon_name(pokemon)}" + (f" · N{level}" if level is not None else "")
            text += f" · {zone_name(death.get('zone'))}\n{display_date(death.get('date') or death.get('timestamp'))}"
            if death.get("note"):
                text += f" · {death['note']}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, death.get("death_id"))
            self.graveyard.addItem(item)
        self.correction_button.setEnabled(bool(deaths))
        pending = [entry for entry in getattr(run, "pending_deaths", []) if not entry.get("resolved", False)]
        self.pending_label.setText(f"{len(pending)} observation(s) à confirmer : identité ou transition insuffisante. Vérifiez le Pokémon puis utilisez « Enregistrer une mort »." if pending else "")
        self.pending_label.setVisible(bool(pending))
        self.pending_list.clear()
        for entry in pending:
            pokemon = entry.get("pokemon", {})
            item = QListWidgetItem(f"{pokemon_name(pokemon)} · {zone_name(entry.get('zone'))} · PV observés : {pokemon.get('current_hp', pokemon.get('hp', '?'))}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.pending_list.addItem(item)
        self.pending_list.setVisible(bool(pending))
        self.pending_button.setVisible(bool(pending))
        self.team_table.setRowCount(len(run.current_party))
        for row, pokemon in enumerate(run.current_party):
            hp = pokemon.get("current_hp", pokemon.get("hp"))
            maximum = pokemon.get("max_hp")
            status = {"alive": "Vivant", "dead": "☠ Mort", "unknown": "Non renseigné"}.get(pokemon.get("life_status"), "Non renseigné")
            key = pokemon.get("pokemon_key")
            if key and run.known_pokemon.get(key, {}).get("life_status") == "dead":
                status = "☠ Mort"
            values = (pokemon_name(pokemon), str(pokemon.get("level") or "?"),
                      f"{hp} / {maximum}" if hp is not None and maximum is not None else "Non renseigné", status)
            for col, value in enumerate(values):
                self.team_table.setItem(row, col, QTableWidgetItem(value))
        self.team_note.setText(f"{len(run.known_pokemon)} individu(s) connu(s) de cette partie ; le cimetière reste conservé hors de l'équipe."
                               if run.known_pokemon else "Équipe et identités : en attente d'observation du jeu.")
        self.rules_view.setPlainText("Règles figées à la création de cette partie\n\n" + ("\n".join("• " + text for text in rules) or "Classique · 0 règle active")
                                    + f"\n\nProfil source : {run.profile_id or 'Aucun'}\nPreset d'origine : {run.preset or 'Non renseigné'}\nSeed : {run.seed}"
                                    + "\n\nModifier le profil source ne modifie pas ces règles. Aucune règle ne modifie la RAM ou la sauvegarde Pokémon.")
        self.technical_view.setPlainText(json.dumps(run.rules_snapshot, ensure_ascii=False, indent=2))
        events = list(run.history)  # The store preserves a validated chronological sequence.
        self.history_table.setRowCount(len(events))
        for row, event in enumerate(events):
            payload = event.get("payload", {})
            details = self._event_details(payload)
            values = (display_date(event.get("timestamp")), EVENT_LABELS.get(event.get("type"), event.get("type", "Événement")),
                      SOURCE_LABELS.get(event.get("source"), "Non renseignée"), details)
            for col, value in enumerate(values):
                self.history_table.setItem(row, col, QTableWidgetItem(value))
        self.save_label.setText(run.save_path or "Aucune sauvegarde Pokémon liée.")
        backups = [event for event in events if event.get("type") == "backup_created"]
        self.backup_label.setText("Dernier backup enregistré : " + display_date(backups[-1].get("timestamp")) if backups else "Dernier backup : consulter le gestionnaire")
        if self.tabs.currentIndex() == 5:
            self._refresh_backup()

    def _refresh_backup(self, *, force=False):
        if not hasattr(self, "run"):
            return
        directory = (self.run.launch_profile or {}).get("backup_directory")
        context = (self.run.run_id, self.run.save_path, directory,
                   sum(event.get("type") == "backup_created" for event in self.run.history))
        if context == self._backup_context and not force:
            if self._backup_summary:
                self.backup_label.setText(self._backup_summary)
            return
        self._backup_context = context
        self._backup_summary = None
        if not directory or not self.run.save_path:
            return
        try:
            records = SaveManagerService(Path(directory)).list_backups_for_save(self.run.save_path, self.run.game_id)
            self._backup_summary = ("Dernier backup enregistré pour cette sauvegarde : " + display_date(records[0].created_at)
                                    + "\n" + records[0].filename) if records else "Aucun backup enregistré pour cette sauvegarde dans le dossier choisi."
        except (OSError, ValueError) as exc:
            self._backup_summary = "Inventaire des backups indisponible : " + str(exc)
        self.backup_label.setText(self._backup_summary)

    @staticmethod
    def _event_details(payload):
        """Human summary intentionally excludes raw PID and trainer identifiers."""
        parts = []
        for key in ("text", "note", "name", "reason", "status", "to", "count", "badges", "duration"):
            value = payload.get(key)
            if isinstance(value, (str, int, float)):
                parts.append(str(value))
        if payload.get("zone"):
            parts.append(zone_name(payload["zone"]))
        if payload.get("pokemon"):
            parts.append(pokemon_name(payload["pokemon"]))
        return " · ".join(parts) or "Événement conservé"

    def manual_action(self, action):
        payload = prompt_run_action(self, self.catalog, self.run, action)
        if payload is not None:
            self.action_requested.emit(self.run_id, action, payload)

    def _badge(self, delta):
        count = max(0, min(badge_limit(self.run), (self.run.badges or 0) + delta))
        self.action_requested.emit(self.run_id, "set_badges", {"count": count})

    def _confirm_pending(self):
        current = self.pending_list.currentItem()
        if current is None:
            return
        observation = current.data(Qt.ItemDataRole.UserRole)
        pokemon = observation.get("pokemon", {})
        dialog = ManualRunEventDialog("manual_death", self.run, self)
        key = pokemon.get("pokemon_key")
        index = dialog.pokemon_combo.findData(key) if key else -1
        if index >= 0:
            dialog.pokemon_combo.setCurrentIndex(index)
        else:
            # Unknown identity stays manual: never assign a same-species individual.
            dialog.pokemon_combo.setEditText(pokemon_name(pokemon))
        dialog.zone_edit.setText(zone_name(observation.get("zone")))
        dialog.note_edit.setPlainText("Confirmation manuelle d'une observation de K.O. à vérifier.")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            payload = dialog.payload()
            payload["review_id"] = observation.get("review_id")
            self.action_requested.emit(self.run_id, "manual_death", payload)

    def _change_status(self):
        status = self.status_combo.currentData()
        if status == self.run.status:
            return
        if QMessageBox.question(self, "Modifier le statut", f"Passer cette partie au statut « {STATUS_LABELS[status]} » ? Son historique sera conservé.",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.action_requested.emit(self.run_id, "set_status", {"status": status})

    def _correct_death(self):
        current = self.graveyard.currentItem()
        if current is None:
            return
        if QMessageBox.question(self, "Corriger une mort", "Annuler cette mort dans PCE ? Un événement de correction restera dans l'historique. La sauvegarde Pokémon reste indépendante.",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.action_requested.emit(self.run_id, "correct_death", {"death_id": current.data(Qt.ItemDataRole.UserRole), "confirmed": True, "note": "Correction confirmée depuis la fiche de partie."})
