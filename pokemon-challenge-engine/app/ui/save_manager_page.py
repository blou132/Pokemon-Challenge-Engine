"""Sauvegardes normales, slots DeSmuME et backups explicitement configurés."""

from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QWidget,
)

from app.models.game import Game
from app.services.save_manager_service import (
    BackupRecord, SAVE_STATE_POLICIES, SaveManagerError, SaveManagerService,
)
from app.ui.widgets.common import card, label, page_layout


def _date(value: str | None) -> str:
    return datetime.fromisoformat(value).astimezone().strftime("%d/%m/%Y %H:%M:%S") if value else "—"


def _size(value: int | None) -> str:
    return f"{value:,} octets".replace(",", " ") if value is not None else "—"


class SaveManagerPage(QWidget):
    """Les changements émettent des choix locaux ; aucune déduction depuis le nom de ROM."""

    settings_changed = Signal(str, object)
    game_changed = Signal(str)
    backup_created = Signal(object)

    def __init__(self, service: SaveManagerService, games: Iterable[Game], parent: QWidget | None = None,
                 *, running_probe: Callable[[], bool] | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.default_root = service.root
        self.emulator_running = False
        self.running_probe = running_probe
        self._loading = False
        self._contexts: dict[str, dict] = {}
        layout = page_layout(self, "Sauvegardes", "Les fichiers sont choisis pour chaque jeu. Les backups automatiques sont désactivés par défaut.")
        self.game_combo = QComboBox()
        for game in games:
            if game.status == "supported":
                self.game_combo.addItem(game.name, game.id)
        self.game_combo.currentIndexChanged.connect(self._game_changed)
        layout.addWidget(self.game_combo)

        normal, normal_layout = card("Sauvegarde normale")
        layout.addWidget(normal)
        self.save_edit = self._path_row(normal_layout, "Fichier .dsv associé à ce jeu", "save")
        self.save_info = label("Choisissez explicitement le fichier .dsv utilisé par DeSmuME.", "muted")
        normal_layout.addWidget(self.save_info)
        row = QHBoxLayout()
        self.open_button = QPushButton("Ouvrir le dossier")
        self.open_button.clicked.connect(self._open_folder)
        self.backup_button = QPushButton("Créer un backup manuel")
        self.backup_button.setObjectName("primary")
        self.backup_button.clicked.connect(self.backup_now)
        row.addWidget(self.open_button)
        row.addWidget(self.backup_button)
        row.addStretch()
        normal_layout.addLayout(row)

        backups, backup_layout = card("Backups PCE")
        layout.addWidget(backups)
        self.backup_directory_edit = self._path_row(backup_layout, "Dossier dédié aux backups", "directory")
        self.backup_directory_edit.setText(str(service.root))
        self.on_launch = QCheckBox("Créer un backup au lancement depuis PCE")
        self.on_close = QCheckBox("Créer un backup à la fermeture de l'émulateur lancé par PCE")
        self.periodic = QCheckBox("Créer des backups périodiques pendant une session lancée par PCE")
        for checkbox in (self.on_launch, self.on_close, self.periodic):
            backup_layout.addWidget(checkbox)
        form = QFormLayout()
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setValue(10)
        self.interval_spin.setSuffix(" min")
        form.addRow("Intervalle", self.interval_spin)
        self.retention_combo = QComboBox()
        for number in (5, 10, 20, 50):
            self.retention_combo.addItem(str(number), number)
        self.retention_combo.addItem("Personnalisée", 0)
        self.retention_combo.setCurrentIndex(1)
        self.retention_custom = QSpinBox()
        self.retention_custom.setRange(1, 10000)
        self.retention_custom.setValue(10)
        self.retention_custom.setEnabled(False)
        self.retention_combo.currentIndexChanged.connect(
            lambda: self.retention_custom.setEnabled(self.retention_combo.currentData() == 0))
        retain = QHBoxLayout()
        retain.addWidget(self.retention_combo)
        retain.addWidget(self.retention_custom)
        form.addRow("Backups conservés par jeu", retain)
        backup_layout.addLayout(form)
        backup_layout.addWidget(label("La rétention supprime uniquement les copies créées par PCE et reconnues dans son manifeste. L'original est conservé.", "muted"))
        self.backup_table = self._table(("Date", "Jeu", "Taille", "Fichier"))
        self.backup_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.backup_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        backup_layout.addWidget(self.backup_table)
        self.restore_button = QPushButton("Restaurer le backup sélectionné…")
        self.restore_button.setToolTip("Confirmation obligatoire. Fermez toutes les instances de DeSmuME. Une copie de la sauvegarde actuelle sera créée avant remplacement.")
        self.restore_button.clicked.connect(self._restore_selected)
        backup_layout.addWidget(self.restore_button)

        states, states_layout = card("Save states — inventaire en lecture seule")
        layout.addWidget(states)
        self.states_directory_edit = self._path_row(states_layout, "Dossier StateSlots de DeSmuME", "directory")
        states_layout.addWidget(label("Nom commun des fichiers .ds0 à .ds9, sans cette extension", "muted"))
        self.states_stem_edit = QLineEdit()
        self.states_stem_edit.setPlaceholderText("Nom exact des fichiers, choisi manuellement")
        states_layout.addWidget(self.states_stem_edit)
        self.policy_combo = QComboBox()
        for key, text in SAVE_STATE_POLICIES.items():
            self.policy_combo.addItem(text, key)
        self.policy_combo.setCurrentIndex(self.policy_combo.findData("unmanaged"))
        states_layout.addWidget(label("Politique déclarée du challenge"))
        states_layout.addWidget(self.policy_combo)
        states_layout.addWidget(label("Politique affichée uniquement : PCE ne bloque pas les save states dans DeSmuME. Aucun chargement, enregistrement ou aperçu n'est effectué ici.", "muted"))
        self.states_table = self._table(("Slot", "Présence", "Date", "Taille"), rows=10)
        states_layout.addWidget(self.states_table)

        self.status_label = label("", "muted")
        layout.addWidget(self.status_label)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton("Actualiser l'inventaire")
        self.refresh_button.clicked.connect(self.refresh)
        self.save_button = QPushButton("Enregistrer ces choix")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save_settings)
        actions.addWidget(self.refresh_button)
        actions.addStretch()
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        layout.addStretch()
        self.refresh()

    @staticmethod
    def _table(headers: tuple[str, ...], rows: int = 0) -> QTableWidget:
        table = QTableWidget(rows, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setMinimumHeight(190 if not rows else 320)
        table.setMinimumWidth(0)
        return table

    def _path_row(self, layout, title: str, kind: str) -> QLineEdit:
        layout.addWidget(label(title))
        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setMinimumWidth(0)
        edit.setAccessibleName(title)
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(lambda: self._browse(edit, kind))
        row.addWidget(edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)
        return edit

    def _browse(self, edit: QLineEdit, kind: str) -> None:
        if kind == "save":
            chosen, _ = QFileDialog.getOpenFileName(self, "Choisir la sauvegarde de ce jeu", edit.text(), "Sauvegardes DeSmuME (*.dsv)")
        else:
            chosen = QFileDialog.getExistingDirectory(self, "Choisir le dossier", edit.text())
        if chosen:
            edit.setText(chosen)
            self.refresh()

    def _game_changed(self) -> None:
        if not self._loading:
            game_id = self.game_combo.currentData()
            self.set_context(game_id, self._contexts.get(game_id, {}))
            self.game_changed.emit(game_id)

    def set_context(self, game_id: str, settings: dict) -> None:
        self._contexts[game_id] = dict(settings)
        self._loading = True
        try:
            index = self.game_combo.findData(game_id)
            if index < 0:
                raise SaveManagerError("Jeu inconnu dans le gestionnaire de sauvegardes.")
            self.game_combo.setCurrentIndex(index)
            self.save_edit.setText(settings.get("save_path", ""))
            self.states_directory_edit.setText(settings.get("save_state_directory", ""))
            self.states_stem_edit.setText(settings.get("save_state_stem", ""))
            self.backup_directory_edit.setText(settings.get("backup_directory") or str(self.default_root))
            self.on_launch.setChecked(settings.get("backup_on_launch", False))
            self.on_close.setChecked(settings.get("backup_on_close", False))
            self.periodic.setChecked(settings.get("backup_periodic", False))
            self.interval_spin.setValue(settings.get("backup_interval_minutes", 10))
            retention = settings.get("backup_retention", 10)
            index = self.retention_combo.findData(retention)
            self.retention_combo.setCurrentIndex(index if index >= 0 else self.retention_combo.findData(0))
            self.retention_custom.setValue(retention)
            self.policy_combo.setCurrentIndex(self.policy_combo.findData(settings.get("save_state_policy", "unmanaged")))
        finally:
            self._loading = False
        self.refresh()

    def current_settings(self) -> dict:
        return {
            "save_path": self.save_edit.text().strip(),
            "save_state_directory": self.states_directory_edit.text().strip(),
            "save_state_stem": self.states_stem_edit.text().strip(),
            "backup_directory": self.backup_directory_edit.text().strip() or str(self.default_root),
            "backup_on_launch": self.on_launch.isChecked(), "backup_on_close": self.on_close.isChecked(),
            "backup_periodic": self.periodic.isChecked(), "backup_interval_minutes": self.interval_spin.value(),
            "backup_retention": self.retention_combo.currentData() or self.retention_custom.value(),
            "save_state_policy": self.policy_combo.currentData(),
        }

    def set_emulator_running(self, running: bool) -> None:
        self.emulator_running = running
        self.restore_button.setEnabled(not running)

    def set_running_probe(self, probe: Callable[[], bool]) -> None:
        """Le propriétaire fournit une détection couvrant aussi les instances externes."""
        self.running_probe = probe

    def _any_emulator_running(self) -> bool:
        if self.emulator_running:
            return True
        if self.running_probe is None:
            return False
        try:
            result = self.running_probe()
        except Exception as exc:
            raise SaveManagerError("Impossible de vérifier si DeSmuME est fermé ; restauration refusée.") from exc
        if type(result) is not bool:
            raise SaveManagerError("État de DeSmuME inconnu ; restauration refusée.")
        return result

    def _selected_service(self) -> SaveManagerService:
        root = self.backup_directory_edit.text().strip() or str(self.default_root)
        if Path(root).absolute() != self.service.root:
            self.service = SaveManagerService(Path(root))
        return self.service

    def refresh(self) -> None:
        errors = []
        game = self.game_combo.currentData()
        if self.save_edit.text().strip():
            try:
                info = self.service.inspect_save(self.save_edit.text().strip(), game)
                self.save_info.setText(f"{self.game_combo.currentText()} · {_date(info.modified_at)} · {_size(info.size)}" if info.exists else "Sauvegarde introuvable au chemin choisi.")
            except ValueError as exc:
                self.save_info.setText(str(exc))
        else:
            self.save_info.setText("Aucun fichier .dsv choisi pour ce jeu.")
        self.backup_table.setRowCount(0)
        try:
            for record in self._selected_service().list_backups(game):
                row = self.backup_table.rowCount()
                self.backup_table.insertRow(row)
                for column, value in enumerate((_date(record.created_at), record.game_id, _size(record.size), record.filename)):
                    self.backup_table.setItem(row, column, QTableWidgetItem(value))
        except ValueError as exc:
            errors.append(str(exc))
        slots = None
        if self.states_directory_edit.text().strip() and self.states_stem_edit.text().strip():
            try:
                slots = self.service.inspect_slots(self.states_directory_edit.text().strip(), self.states_stem_edit.text().strip(), game)
            except ValueError as exc:
                errors.append(str(exc))
        for row in range(10):
            slot = slots[row] if slots else None
            values = (f"Slot {row}", ("Existe" if slot.exists else "Vide") if slot else "Non disponible",
                      _date(slot.modified_at) if slot else "—", _size(slot.size) if slot else "—")
            for column, value in enumerate(values):
                self.states_table.setItem(row, column, QTableWidgetItem(value))
        self.status_label.setText("\n".join(errors))

    def backup_now(self) -> BackupRecord | None:
        try:
            settings = self.current_settings()
            record = self._selected_service().backup(settings["save_path"], self.game_combo.currentData(),
                                                      retention=settings["backup_retention"], reason="manual")
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return None
        self.refresh()
        self.status_label.setText(f"Backup créé et vérifié par SHA-256 : {record.filename}")
        self.backup_created.emit(record)
        return record

    def _save_settings(self) -> None:
        settings = self.current_settings()
        try:
            self._selected_service()
            if settings["save_path"]:
                info = self.service.inspect_save(settings["save_path"], self.game_combo.currentData())
                if not info.exists:
                    raise SaveManagerError("Choisissez une sauvegarde existante avant d'enregistrer ce chemin.")
            if any(settings[key] for key in ("backup_on_launch", "backup_on_close", "backup_periodic")) and not settings["save_path"]:
                raise SaveManagerError("Choisissez d'abord le fichier .dsv à copier automatiquement.")
            if bool(settings["save_state_directory"]) != bool(settings["save_state_stem"]):
                raise SaveManagerError("Renseignez le dossier des slots et leur nom commun ensemble.")
            if settings["save_state_directory"]:
                self.service.inspect_slots(settings["save_state_directory"], settings["save_state_stem"], self.game_combo.currentData())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.settings_changed.emit(self.game_combo.currentData(), settings)

    def _open_folder(self) -> None:
        try:
            info = self.service.inspect_save(self.save_edit.text().strip(), self.game_combo.currentData())
            if not info.path.parent.is_dir():
                raise SaveManagerError("Le dossier de cette sauvegarde est introuvable.")
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(info.path.parent))):
                raise SaveManagerError("Impossible d'ouvrir le dossier.")
        except ValueError as exc:
            self.status_label.setText(str(exc))

    def _restore_selected(self) -> None:
        row = self.backup_table.currentRow()
        if row < 0:
            self.status_label.setText("Sélectionnez un backup dans la liste.")
            return
        try:
            if self._any_emulator_running():
                raise SaveManagerError("Fermez toutes les instances de DeSmuME avant toute restauration.")
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        filename = self.backup_table.item(row, 3).text()
        answer = QMessageBox.question(
            self, "Confirmer la restauration",
            f"Restaurer {filename} vers le fichier .dsv choisi ?\n\n"
            "Confirmez que toutes les instances de DeSmuME sont fermées. La sauvegarde actuelle sera remplacée après création d'un backup de sécurité.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            running = self._any_emulator_running()
            self._selected_service().restore(filename, self.save_edit.text().strip(), self.game_combo.currentData(),
                                              confirmed=True, emulator_running=running,
                                              retention=self.current_settings()["backup_retention"])
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
        self.status_label.setText("Restauration terminée. La sauvegarde précédente a été conservée dans un backup de sécurité.")
