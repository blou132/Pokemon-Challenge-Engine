"""Previewed migration of an old local installation, started only on explicit request."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QMessageBox, QProgressBar, QVBoxLayout

from app.services.user_data_import import execute_import, plan_import
from app.ui.setup_tasks import SetupTaskRunner


class _ImportProgress(QDialog):
    def __init__(self, plan, parent):
        super().__init__(parent)
        self.setWindowTitle("Import des anciennes données")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Copie et vérification en cours. Les données sources sont conservées."))
        progress = QProgressBar()
        progress.setRange(0, 0)
        layout.addWidget(progress)
        self.result_data = None
        self.error = ""
        self.runner = SetupTaskRunner(self)
        self.runner.succeeded.connect(self._success)
        self.runner.failed.connect(self._failure)
        self.runner.start(lambda: execute_import(plan))

    def _success(self, result):
        self.result_data = result
        self.accept()

    def _failure(self, error):
        self.error = error
        self.accept()

    def reject(self):
        if not self.runner.is_busy:
            super().reject()


def import_old_data(parent, destination: Path) -> None:
    source = QFileDialog.getExistingDirectory(parent, "Ancien dossier PCE contenant runs et profiles")
    if not source:
        return
    try:
        plan = plan_import(Path(source), destination)
        message = (f"Copier {len(plan.runs)} partie(s), {len(plan.profiles)} modèle(s) et "
                   f"{len(plan.preferences)} préférence(s) vers :\n{destination}\n\n"
                   "Les fichiers sources sont conservés. Les préférences déjà présentes restent inchangées.\n"
                   "Fermez l'ancien PCE et tous les émulateurs avant de continuer.\n"
                   "Après l'import, redémarrez cette application pour recharger les préférences.")
        if QMessageBox.question(parent, "Importer les anciennes données", message,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        progress = _ImportProgress(plan, parent)
        progress.exec()
        if progress.error:
            raise ValueError(progress.error)
        result = progress.result_data
    except (OSError, ValueError, TypeError, KeyError) as exc:
        QMessageBox.warning(parent, "Import interrompu", f"{exc}\n\nLes données sources sont conservées.")
        return
    QMessageBox.information(parent, "Import terminé", f"{result['runs']} partie(s) et {result['profiles']} modèle(s) importés.\n"
                            "Fermez puis relancez PCE pour retrouver vos données.")
