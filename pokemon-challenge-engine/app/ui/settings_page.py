"""État de l'installation locale et réglages manuels de secours."""

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
from app.ui.widgets.common import INSTALLATION_LABELS


class SettingsPage(QWidget):
    """Présente la découverte automatique avant les chemins avancés."""

    config_changed = Signal(object)
    installation_requested = Signal()
    detection_requested = Signal()

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
        subtitle = QLabel("Votre bibliothèque locale est détectée automatiquement. Les réglages manuels restent disponibles en cas de besoin.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("subtitle")
        content.addWidget(subtitle)

        installation_card, installation_layout = self._card("Installation")
        content.addWidget(installation_card)
        self.installation_state = QLabel("Recherche automatique en cours…")
        self.installation_state.setWordWrap(True)
        installation_layout.addWidget(self.installation_state)
        self.installation_summary: dict[str, QLabel] = {}
        for key, label in (("retrobat", "RetroBat"), ("emulator", "DeSmuME"),
                           ("lua", "Support Lua"), ("games", "Jeux"), ("saves", "Sauvegardes")):
            widget = QLabel(f"{label} · Recherche en cours…")
            widget.setWordWrap(True)
            self.installation_summary[key] = widget
            installation_layout.addWidget(widget)
        self.game_states: dict[str, QLabel] = {}
        for game in self.games:
            widget = QLabel(f"{game.name} · Recherche en cours…")
            widget.setWordWrap(True)
            self.game_states[game.id] = widget
            installation_layout.addWidget(widget)

        self.installation_button = QPushButton("Installation && diagnostic")
        self.installation_button.setObjectName("primary")
        self.installation_button.setToolTip("Détecter les jeux locaux, préparer les archives et vérifier le support Lua.")
        self.installation_button.clicked.connect(self.installation_requested)
        installation_layout.addWidget(self.installation_button)

        self.warning_label = QLabel("\n".join(config_service.warnings))
        self.warning_label.setWordWrap(True)
        self.warning_label.setObjectName("muted")
        self.warning_label.setVisible(bool(config_service.warnings))
        content.addWidget(self.warning_label)

        self.advanced_toggle = QPushButton("Afficher les chemins manuels · Avancé")
        self.advanced_toggle.setCheckable(True)
        content.addWidget(self.advanced_toggle)
        self.advanced_panel = QWidget()
        advanced = QVBoxLayout(self.advanced_panel)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.setSpacing(18)
        self.advanced_panel.hide()
        self.advanced_toggle.toggled.connect(self.advanced_panel.setVisible)
        content.addWidget(self.advanced_panel)
        self.detection_button = QPushButton("Relancer la détection")
        self.detection_button.clicked.connect(self.detection_requested)
        advanced.addWidget(self.detection_button)

        emulator_card, emulator_layout = self._card("Émulateur et bibliothèque")
        advanced.addWidget(emulator_card)
        description = QLabel("DeSmuME standalone est lancé directement. Le chemin RetroBat est conservé comme repère pour votre installation.")
        description.setWordWrap(True)
        description.setObjectName("muted")
        emulator_layout.addWidget(description)
        self.retrobat_edit = self._path_row(emulator_layout, "RetroBat — dossier ou exécutable (facultatif)",
                                            config.retrobat_path, "Le dossier d'installation RetroBat ou retrobat.exe.", "retrobat")
        self.desmume_edit = self._path_row(emulator_layout, "DeSmuME standalone — exécutable .exe", config.desmume_path,
                                          "Choisissez le fichier .exe de DeSmuME standalone, compatible avec votre installation.", "emulator")

        games_card, games_layout = self._card("Jeux Nintendo DS")
        advanced.addWidget(games_card)
        self.rom_edits: dict[str, QLineEdit] = {}
        for game in self.games:
            self.rom_edits[game.id] = self._path_row(games_layout, f"{game.name} — ROM .nds", config.rom_paths.get(game.id, ""),
                                                    "Le launcher vérifie l'existence du fichier sans lire ni modifier la ROM.", "rom")

        saves_card, saves_layout = self._card("Sauvegardes")
        advanced.addWidget(saves_card)
        self.save_edit = self._path_row(saves_layout, "Dossier des sauvegardes (facultatif)", config.save_path,
                                       "Dossier utilisé par le diagnostic. Les copies et restaurations passent par le gestionnaire de sauvegardes et ses confirmations.", "directory")
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
        advanced.addLayout(actions)
        content.addStretch()

    def set_detection_state(self, report: dict) -> None:
        """Affiche le résultat partagé sans relancer la recherche ni modifier les champs."""
        states = report.get("game_states", {})
        ready = any(state.get("status") == "ready" for state in states.values())
        self.installation_state.setText("Installation PCE · Prête" if ready else
                                       "Ajoutez un jeu local ou consultez le diagnostic pour terminer l'installation.")
        installations, emulators = report.get("installations", []), report.get("emulators", [])
        self.installation_summary["retrobat"].setText("RetroBat · " + (
            "Détecté automatiquement" if installations else "Non trouvé · Installation indépendante possible"))
        self.installation_summary["emulator"].setText("DeSmuME · " + (
            "Détecté automatiquement" if emulators else "Non trouvé · Choix manuel disponible dans le diagnostic"))
        lua_ready = any(item.get("lua_status") in {"ready", "verified", "installed"} for item in emulators)
        self.installation_summary["lua"].setText("Support Lua · " + (
            "Prêt" if lua_ready else "Requis · Installation disponible dans le diagnostic" if emulators else "En attente de DeSmuME"))
        found = {item.get("game_id") for item in report.get("games", [])}
        self.installation_summary["games"].setText(f"Jeux · {len(found & set(self.game_states))} / {len(self.games)} trouvés")
        associated = sum(bool(state.get("save_path")) for state in states.values())
        saves_found = any(game.get("saves") for game in report.get("games", []))
        ambiguous = any("sauvegarde" in state.get("message", "").lower() and state.get("status") == "needs_choice"
                        for state in states.values())
        self.installation_summary["saves"].setText("Sauvegardes · " + (
            "Plusieurs candidates · Choix nécessaire dans le diagnostic" if ambiguous else
            f"{associated} association(s) détectée(s)" if associated else
            "Fichiers détectés · Aucune sauvegarde associée" if saves_found else "Aucune sauvegarde existante trouvée"))
        for game in self.games:
            state = states.get(game.id, {})
            status = state.get("status", "not_found")
            message = state.get("message", "")
            if status == "not_found":
                message = f"Veuillez ajouter {game.name} à votre bibliothèque RetroBat."
            self.game_states[game.id].setText(f"{game.name} · {INSTALLATION_LABELS.get(status, 'À vérifier')}" +
                                             (f"\n{message}" if message and status != "ready" else ""))

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
