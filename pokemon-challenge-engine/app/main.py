"""Point d'entrée Windows : python -m app.main (ou pythonw sans console)."""

import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.catalog import Catalog
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
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Pokemon Challenge Engine")
    app.setOrganizationName("Pokemon Challenge Engine")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(application_icon())
    try:
        configure_logging(PROJECT_DIR, args.debug)
        logging.info("Démarrage de Pokemon Challenge Engine V0.1.0")
        catalog = Catalog.load(PROJECT_DIR / "data")
        window = MainWindow(catalog, PROJECT_DIR)
    except (ValueError, OSError) as exc:
        logging.error("Initialisation impossible : %s", type(exc).__name__)
        QMessageBox.critical(None, "Démarrage impossible", f"Les données de l'application ne peuvent pas être chargées.\n\n{exc}\n\nVérifiez les fichiers JSON et les droits d'accès au dossier.")
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
