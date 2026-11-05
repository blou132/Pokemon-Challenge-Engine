"""Bibliothèque privée : inventaire et opérations disque hors du thread Qt."""

from collections.abc import Iterable, Mapping
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.models.game import Game


DS_GAMES = (
    ("diamond", "Pokémon Diamant", 4), ("pearl", "Pokémon Perle", 4),
    ("platinum", "Pokémon Platine", 4), ("heartgold", "Pokémon HeartGold", 4),
    ("soulsilver", "Pokémon SoulSilver", 4), ("black", "Pokémon Noir", 5),
    ("white", "Pokémon Blanc", 5), ("black2", "Pokémon Noir 2", 5),
    ("white2", "Pokémon Blanc 2", 5),
)


class _LibraryTask(QThread):
    """Un seul travail à la fois, conservé jusqu'à sa terminaison normale."""

    def __init__(self, service, operation: str, folder: Path | None, parent):
        super().__init__(parent)
        self.service = service
        self.operation = operation
        self.folder = folder
        self.result = {}
        self.setObjectName("PCE bibliothèque privée")

    def run(self) -> None:
        result = {"operation": self.operation, "entries": (), "present": {},
                  "verified": {}, "imported": 0, "existing": 0, "error": ""}
        try:
            if self.operation == "import":
                imported = tuple(self.service.import_directory(self.folder))
                result["imported"] = sum(item.imported for item in imported)
                result["existing"] = sum(not item.imported for item in imported)
            if self.operation in {"verify", "import"}:
                result["verified"] = {
                    item.entry.game_id: {"sha256": item.entry.sha256,
                                         "valid": item.valid, "error": item.error}
                    for item in self.service.verify()
                }
        except Exception as exc:
            result["error"] = str(exc) or "L'opération n'a pas pu être terminée."
        try:
            # Une erreur peut survenir après un import réussi : relire les copies
            # effectivement publiées sans prétendre avoir annulé l'opération.
            result["entries"] = tuple(self.service.list_entries())
            result["present"] = {
                entry.game_id: self.service.master_path(entry).is_file()
                for entry in result["entries"]
            }
        except Exception as exc:
            result["error"] = result["error"] or str(exc) or "Inventaire inaccessible."
        self.result = result


class RomLibraryPanel(QFrame):
    """Affiche les neuf jeux DS sans déduire leurs capacités de la ROM présente."""

    library_changed = Signal()
    busy_changed = Signal(bool)

    def __init__(self, games: Iterable[Game], service=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.service = service
        self._games = {game.id: game for game in games}
        self._task: _LibraryTask | None = None
        self._closing = False
        self._melonds_available: bool | None = None
        self._run_counts: dict[str, int] = {}
        self._entries = {}
        self._present = {}
        self._verified = {}
        self._pending_refresh: bool | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(12)
        title = QLabel("Bibliothèque de jeux")
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        layout.addWidget(title)
        description = QLabel(
            "Vos jeux personnels sont conservés dans une bibliothèque privée, hors ligne. "
            "Chaque aventure utilise sa propre copie ; les ROM maîtresses et les originaux sont conservés."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.directory_label = QLabel(str(service.root) if service is not None else "Bibliothèque non connectée")
        self.directory_label.setWordWrap(True)
        self.directory_label.setObjectName("muted")
        layout.addWidget(self.directory_label)

        actions = QHBoxLayout()
        self.verify_button = QPushButton("Vérifier ma bibliothèque")
        self.verify_button.clicked.connect(self.verify_library)
        self.import_button = QPushButton("Importer un dossier local…")
        self.import_button.clicked.connect(self._choose_directory)
        actions.addWidget(self.verify_button)
        actions.addWidget(self.import_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.status_label = QLabel("Bibliothèque non connectée" if service is None else "Chargement de la bibliothèque…")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.rows: dict[str, dict[str, QLabel]] = {}
        for game_id, name, generation in DS_GAMES:
            game = self._games.get(game_id)
            row = QFrame()
            row.setObjectName("libraryGame")
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 8, 0, 8)
            row_layout.setSpacing(4)
            labels = {}
            for field in ("name", "source", "integrity", "emulator", "modes", "runs"):
                label = QLabel()
                label.setWordWrap(True)
                label.setObjectName(f"library_{game_id}_{field}")
                labels[field] = label
                row_layout.addWidget(label)
            labels["name"].setText(f"{game.name if game else name} · Génération {generation}")
            labels["name"].setStyleSheet("font-weight: 600;")
            labels["modes"].setText(self._compatible_modes(game))
            self.rows[game_id] = labels
            layout.addWidget(row)
        self._render()
        self._set_busy(False)
        if service is not None:
            self.refresh()

    @staticmethod
    def _compatible_modes(game: Game | None) -> str:
        if game is None or game.status not in {"supported", "classic_only"}:
            return "Modes compatibles · Adaptation non disponible"
        if game.status == "classic_only":
            return "Modes compatibles · " + game.compatibility_summary
        return (
            "Modes compatibles · Classique et challenges avec suivi selon les événements disponibles. "
            "Randomizer et Monotype : ROM françaises révision 0. "
            + ("Taux shiny personnalisés : patch expérimental Blanc FR0 reconnu, herbe normale vérifiée."
               if game.id == "white" else "Taux shiny original uniquement.")
        )

    @property
    def is_busy(self) -> bool:
        return self._task is not None

    def set_context(self, *, melonds_available: bool | None = None,
                    run_counts: Mapping[str, int] | None = None) -> None:
        """Reçoit l'état vérifié de l'émulateur et les comptes du gestionnaire de parties."""
        self._melonds_available = melonds_available
        if run_counts is not None:
            self._run_counts = dict(run_counts)
        self._render()

    def apply_verification(self, results: Mapping[str, Mapping]) -> None:
        """Affiche un contrôle externe uniquement pour l'empreinte qu'il concerne."""
        self._verified = {game_id: dict(result) for game_id, result in results.items()}
        self._render()

    def _render(self) -> None:
        for game_id, labels in self.rows.items():
            entry = self._entries.get(game_id)
            present = bool(self._present.get(game_id))
            labels["source"].setText("ROM source · " + (
                "Présente dans la bibliothèque privée" if present else
                "Copie maîtresse introuvable" if entry else "Absente de la bibliothèque privée"))
            verification = self._verified.get(game_id)
            if verification is not None and (entry is None or verification.get("sha256") != entry.sha256):
                verification = None
            if not entry:
                integrity = "Sans ROM source"
            elif verification is None:
                integrity = "À vérifier" if present else "Échec : copie maîtresse introuvable"
            elif verification.get("valid") is True:
                integrity = "Dernier contrôle conforme · SHA-256 vérifié" if present else "Échec : copie maîtresse introuvable"
            else:
                integrity = "Échec · " + (verification.get("error") or "empreinte ou identité non conforme")
            labels["integrity"].setText("Intégrité · " + integrity)
            labels["integrity"].setToolTip(f"SHA-256 de référence : {entry.sha256}" if entry else "")
            labels["emulator"].setText("melonDS · " + (
                "Disponible" if self._melonds_available is True else
                "Indisponible" if self._melonds_available is False else "Disponibilité à vérifier"))
            count = self._run_counts.get(game_id)
            labels["runs"].setText("Parties créées · " + (str(count) if count is not None else "À vérifier"))

    def refresh(self, *, verify: bool = False) -> bool:
        if self.is_busy and not self._closing:
            self._pending_refresh = bool(verify or self._pending_refresh)
            return False
        return self._start("verify" if verify else "refresh")

    @Slot()
    def verify_library(self) -> None:
        self.refresh(verify=True)

    def import_directory(self, folder: Path | str) -> bool:
        return self._start("import", Path(folder))

    @Slot()
    def _choose_directory(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Importer vos ROM personnelles")
        if folder:
            self.import_directory(folder)

    def _start(self, operation: str, folder: Path | None = None) -> bool:
        if self.service is None or self.is_busy or self._closing:
            return False
        self.status_label.setText({
            "refresh": "Lecture de la bibliothèque…",
            "verify": "Vérification des empreintes des ROM maîtresses…",
            "import": "Import des fichiers locaux et vérification des copies…",
        }[operation])
        task = _LibraryTask(self.service, operation, folder, self)
        self._task = task
        task.finished.connect(self._finished)
        self._set_busy(True)
        task.start()
        return True

    def _set_busy(self, busy: bool) -> None:
        enabled = self.service is not None and not busy and not self._closing
        self.verify_button.setEnabled(enabled)
        self.import_button.setEnabled(enabled)
        self.busy_changed.emit(busy)

    @Slot()
    def _finished(self) -> None:
        task = self._task
        if task is None:
            return
        result = task.result
        pending_refresh, self._pending_refresh = self._pending_refresh, None
        self._task = None
        task.deleteLater()
        self._entries = {entry.game_id: entry for entry in result["entries"]}
        self._present = result["present"]
        if result["operation"] != "refresh":
            self._verified = result["verified"]
        self._render()
        self._set_busy(False)
        if result["error"]:
            self.status_label.setText("Bibliothèque à vérifier · " + result["error"])
        elif result["operation"] == "import":
            self.status_label.setText(
                f"Import terminé · {result['imported']} copie(s) ajoutée(s), "
                f"{result['existing']} déjà présente(s). Les fichiers originaux sont conservés."
            )
        elif result["operation"] == "verify":
            invalid = sum(value.get("valid") is not True for value in self._verified.values())
            self.status_label.setText(
                f"Vérification terminée · {len(self._verified) - invalid} source(s) conforme(s), "
                f"{invalid} erreur(s)."
            )
        else:
            self.status_label.setText(f"{sum(self._present.values())} jeu(x) présent(s) sur 9 dans la bibliothèque privée.")
        if result["operation"] != "refresh":
            self.library_changed.emit()
        if pending_refresh is not None and not self._closing:
            self.refresh(verify=pending_refresh)

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        """Attend une opération en cours sans interrompre une copie de fichier."""
        self._closing = True
        self._set_busy(self.is_busy)
        task = self._task
        if task is not None and not task.wait(max(0, timeout_ms)):
            self.status_label.setText("Une opération de bibliothèque se termine. Fermez l'application après sa fin.")
            self._closing = False
            return False
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self.shutdown():
            event.ignore()
            return
        super().closeEvent(event)
