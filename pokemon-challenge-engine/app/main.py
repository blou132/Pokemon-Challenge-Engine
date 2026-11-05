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
    parser.add_argument("--library-dir", type=Path, help="Bibliothèque explicite (tests isolés ou stockage personnel avancé)")
    parser.add_argument("--prepare-library", type=Path, metavar="DOSSIER", help="Importer une fois les ROM locales, sans lancer l'interface")
    parser.add_argument("--verify-library", action="store_true", help="Vérifier la bibliothèque personnelle, sans lancer l'interface")
    parser.add_argument("--library-report", type=Path, help="Écrire le résultat de préparation/vérification dans un nouveau fichier JSON")
    args = parser.parse_args()
    if args.self_test is not None and args.data_dir is None:
        parser.error("--self-test exige --data-dir vers un dossier de validation isolé")
    if args.library_dir is not None and not args.library_dir.is_absolute():
        parser.error("--library-dir exige un chemin absolu")
    if args.library_report is not None and args.prepare_library is None and not args.verify_library:
        parser.error("--library-report exige --prepare-library ou --verify-library")
    from app.services.rom_library_service import RomLibraryService
    library_root = args.library_dir
    if args.self_test is not None and library_root is None:
        library_root = args.data_dir / "test-library"
    if args.prepare_library is not None or args.verify_library:
        import json
        try:
            library = RomLibraryService(library_root)
            imported = library.import_directory(args.prepare_library) if args.prepare_library is not None else ()
            checked = library.verify()
            report = {"library": str(library.root), "imported": sum(item.imported for item in imported),
                      "games": [{"game_id": item.entry.game_id, "sha256": item.entry.sha256,
                                 "valid": item.valid, "error": item.error} for item in checked]}
            serialized = json.dumps(report, ensure_ascii=False, indent=2)
            if args.library_report is not None:
                with args.library_report.open("x", encoding="utf-8") as output:
                    output.write(serialized + "\n")
            print(serialized, flush=True)
            return 0 if all(item.valid for item in checked) else 1
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Pokemon Challenge Engine")
    app.setOrganizationName("Pokemon Challenge Engine")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(application_icon())
    try:
        library = RomLibraryService(library_root)
        paths = resolve_app_paths(args.data_dir)
        configure_logging(paths.data, args.debug)
        logging.info("Démarrage de Pokemon Challenge Engine V%s", __version__)
        catalog = Catalog.load(paths.resources / "data")
        source_directories = () if args.self_test is not None else (
            paths.installation / "roms sources", paths.resources.parent / "roms sources")
        window = MainWindow(catalog, paths.data, library_service=library,
                            library_source_directories=source_directories)
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
