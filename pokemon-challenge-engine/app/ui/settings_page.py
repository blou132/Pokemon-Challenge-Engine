"""Page de configuration des chemins locaux, sans accès au contenu des jeux."""

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.models.game import Game
from app.services.config_service import AppConfig, ConfigService
from app.services.launcher_service import LauncherService


class SettingsPage(QWidget):
    """Saisit et teste les chemins ; le lancement reste une action explicite ailleurs."""

    config_changed = Signal(object)

    def __init__(self, config_service: ConfigService, config: AppConfig, games: Iterable[Game],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.config_service = config_service
        self.config = config
        self.games = tuple(game for game in games if game.status == "supported")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll)
        body = QWidget()
        body.setObjectName("page")
        scroll.setWidget(body)
        content = QVBoxLayout(body)
        content.setContentsMargins(30, 24, 30, 28)
        content.setSpacing(18)

        title = QLabel("Paramètres")
        title.setObjectName("title")
        content.addWidget(title)
        subtitle = QLabel("Reliez vos jeux et votre émulateur. Tous les chemins sont choisis sur cet ordinateur.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("subtitle")
        content.addWidget(subtitle)

        self.warning_label = QLabel("\n".join(config_service.warnings))
        self.warning_label.setWordWrap(True)
        self.warning_label.setObjectName("muted")
        self.warning_label.setVisible(bool(config_service.warnings))
        content.addWidget(self.warning_label)

        emulator_card, emulator_layout = self._card("Émulateur et bibliothèque")
        content.addWidget(emulator_card)
        description = QLabel("DeSmuME standalone est lancé directement. Le chemin RetroBat est conservé comme repère pour votre installation.")
        description.setWordWrap(True)
        description.setObjectName("muted")
        emulator_layout.addWidget(description)
        self.retrobat_edit = self._path_row(emulator_layout, "RetroBat — dossier ou exécutable (facultatif)",
                                            config.retrobat_path, "Le dossier d'installation RetroBat ou retrobat.exe.", "retrobat")
        self.desmume_edit = self._path_row(emulator_layout, "DeSmuME standalone — exécutable .exe", config.desmume_path,
                                          "Choisissez le fichier .exe de DeSmuME standalone, compatible avec votre installation.", "emulator")

        games_card, games_layout = self._card("Jeux Nintendo DS")
        content.addWidget(games_card)
        self.rom_edits: dict[str, QLineEdit] = {}
        for game in self.games:
            self.rom_edits[game.id] = self._path_row(games_layout, f"{game.name} — ROM .nds", config.rom_paths.get(game.id, ""),
                                                    "Le launcher vérifie l'existence du fichier sans lire ni modifier la ROM.", "rom")

        saves_card, saves_layout = self._card("Sauvegardes")
        content.addWidget(saves_card)
        self.save_edit = self._path_row(saves_layout, "Dossier des sauvegardes (facultatif)", config.save_path,
                                       "Repère informatif. La V0.1 ne lit, ne déplace et n'écrit aucune sauvegarde du jeu.", "directory")
        note = QLabel("Ce dossier est informatif : DeSmuME conserve ses propres réglages de sauvegarde.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        saves_layout.addWidget(note)

        actions = QHBoxLayout()
        actions.addStretch()
        self.test_button = QPushButton("Tester les chemins")
        self.test_button.setToolTip("Vérifie les chemins saisis, sans lancer l'émulateur et sans enregistrer les paramètres.")
        self.test_button.clicked.connect(self._test)
        actions.addWidget(self.test_button)
        self.save_button = QPushButton("Enregistrer les paramètres")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save)
        actions.addWidget(self.save_button)
        content.addLayout(actions)
        content.addStretch()

    @staticmethod
    def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(12)
        label = QLabel(title)
        label.setStyleSheet("font-size: 17px; font-weight: 600;")
        layout.addWidget(label)
        return card, layout

    def _path_row(self, layout: QVBoxLayout, title: str, value: str, tooltip: str, kind: str) -> QLineEdit:
        label = QLabel(title)
        label.setWordWrap(True)
        layout.addWidget(label)
        row = QHBoxLayout()
        edit = QLineEdit(value)
        edit.setMinimumWidth(0)
        edit.setPlaceholderText("Aucun chemin configuré")
        edit.setToolTip(tooltip)
        edit.setAccessibleName(title)
        label.setBuddy(edit)
        row.addWidget(edit, 1)
        browse = QPushButton("Parcourir…")
        browse.setToolTip(tooltip)
        if kind == "retrobat":
            menu = QMenu(browse)
            menu.addAction("Choisir un dossier…", lambda: self._browse(edit, "directory"))
            menu.addAction("Choisir un exécutable…", lambda: self._browse(edit, "emulator"))
            browse.setMenu(menu)
        else:
            browse.clicked.connect(lambda checked=False, field=edit, selection=kind: self._browse(field, selection))
        row.addWidget(browse)
        layout.addLayout(row)
        return edit

    def _browse(self, field: QLineEdit, kind: str) -> None:
        initial = field.text().strip()
        if kind == "directory":
            chosen = QFileDialog.getExistingDirectory(self, "Choisir un dossier", initial)
        else:
            filters = "ROM Nintendo DS (*.nds)" if kind == "rom" else "Exécutables Windows (*.exe)"
            chosen, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier", initial, filters)
        if chosen:
            field.setText(str(Path(chosen)))

    def _current_config(self) -> AppConfig:
        return AppConfig(
            retrobat_path=self.retrobat_edit.text().strip(), desmume_path=self.desmume_edit.text().strip(),
            rom_paths=self.config.rom_paths | {key: edit.text().strip() for key, edit in self.rom_edits.items()},
            save_path=self.save_edit.text().strip(),
        )

    def _test(self) -> None:
        config = self._current_config()
        launcher = LauncherService(config)
        messages: list[str] = []
        all_valid = True
        for game in self.games:
            errors = launcher.validate(game.id)
            messages.append(f"{game.name} : " + ("chemins prêts pour le lancement." if not errors else "\n  • " + "\n  • ".join(errors)))
            all_valid = all_valid and not errors
        try:
            if config.retrobat_path:
                path = Path(config.retrobat_path)
                valid = path.is_dir() or (path.is_file() and path.suffix.lower() == ".exe")
                messages.append("RetroBat : " + ("chemin trouvé." if valid else "dossier ou exécutable introuvable."))
                all_valid = all_valid and valid
            if config.save_path:
                valid = Path(config.save_path).is_dir()
                messages.append("Sauvegardes : " + ("dossier trouvé." if valid else "dossier introuvable."))
                all_valid = all_valid and valid
        except (OSError, ValueError):
            messages.append("Un des chemins facultatifs est invalide ou inaccessible.")
            all_valid = False
        messages.append("Ce test vérifie les fichiers présents. Aucun jeu n'a été lancé et aucun fichier de jeu n'a été ouvert.")
        show = QMessageBox.information if all_valid else QMessageBox.warning
        show(self, "Vérification des chemins", "\n\n".join(messages))

    def _save(self) -> None:
        config = self._current_config()
        try:
            self.config_service.save(config)
        except ValueError as exc:
            QMessageBox.warning(self, "Paramètres non enregistrés", str(exc))
            return
        self.config = config
        self.warning_label.setText("\n".join(self.config_service.warnings))
        self.warning_label.setVisible(bool(self.config_service.warnings))
        self.config_changed.emit(config)
        message = "Les paramètres ont été enregistrés sur cet ordinateur."
        if self.config_service.warnings:
            message += "\n\n" + "\n".join(self.config_service.warnings)
        QMessageBox.information(self, "Paramètres enregistrés", message)
