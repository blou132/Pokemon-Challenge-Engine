"""Point d'entrée Windows : python -m app.main (ou pythonw sans console)."""

import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from app import __version__
from app.core.catalog import Catalog
from app.paths import resolve_app_paths
from app.ui.main_window import MainWindow
from app.ui.theme import STYLESHEET

PROJECT_DIR = Path(__file__).resolve().parent.parent


def configure_logging(base_dir: Path, debug: bool = False) -> None:
    """Limiter la taille des journaux et ne pas activer DEBUG par défaut."""
    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s : %(message)s", force=True)


def application_icon() -> QIcon:
    """Symbole géométrique original, sans ressource Pokémon officielle."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#141b2c"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#b9adff"))
    painter.setBrush(QColor("#8573ea"))
    painter.drawRoundedRect(12, 12, 40, 40, 12, 12)
    painter.setBrush(QColor("#141b2c"))
    painter.drawEllipse(24, 24, 16, 16)
    painter.end()
    return QIcon(pixmap)


def main() -> int:
    parser = argparse.ArgumentParser(description="Préparation locale de challenges Pokémon")
    parser.add_argument("--debug", action="store_true", help="Activer les logs détaillés, dont la commande de lancement")
    parser.add_argument("--data-dir", type=Path, help="Dossier absolu des données personnelles")
    parser.add_argument("--self-test", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.self_test is not None and args.data_dir is None:
        parser.error("--self-test exige --data-dir vers un dossier de validation isolé")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Pokemon Challenge Engine")
    app.setOrganizationName("Pokemon Challenge Engine")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(application_icon())
    try:
        paths = resolve_app_paths(args.data_dir)
        configure_logging(paths.data, args.debug)
        logging.info("Démarrage de Pokemon Challenge Engine V%s", __version__)
        catalog = Catalog.load(paths.resources / "data")
        window = MainWindow(catalog, paths.data)
    except (ValueError, OSError) as exc:
        logging.error("Initialisation impossible : %s", type(exc).__name__)
        QMessageBox.critical(None, "Démarrage impossible", f"Les données de l'application ne peuvent pas être chargées.\n\n{exc}\n\nVérifiez les fichiers JSON et les droits d'accès au dossier.")
        return 1
    def unhandled_exception(kind, value, traceback):
        logging.error("Erreur inattendue dans l'interface", exc_info=(kind, value, traceback))
        QMessageBox.critical(window, "Erreur inattendue", "L'action n'a pas pu être terminée. "
                             f"Consultez le journal dans {paths.data / 'logs'}.")
    sys.excepthook = unhandled_exception
    window.show()
    if args.self_test is not None:
        from app.distribution_check import run_check
        QTimer.singleShot(100, lambda: run_check(app, window, paths, args.self_test))
    else:
        QTimer.singleShot(0, window.start_first_run)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
