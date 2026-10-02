"""Vérification native Qt et captures, sans ROM ni profil utilisateur.

Exécuter depuis la racine : python -m tools.verify_ui
Les données du parcours sont isolées dans un répertoire temporaire.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from app.core.catalog import Catalog
from app.main import PROJECT_DIR, application_icon
from app.ui.main_window import MainWindow
from app.ui.monotype_wheel import MonotypeDialog
from app.ui.theme import STYLESHEET


def main() -> None:
    parser = argparse.ArgumentParser(description="Vérification Qt sans données de jeu")
    parser.add_argument("--offscreen", action="store_true", help="Rendu aux dimensions demandées même sur un écran plus petit")
    parser.add_argument("--entrypoint", action="store_true", help="Démarrer puis fermer automatiquement le véritable point d'entrée")
    args = parser.parse_args()
    if args.entrypoint:
        verify_entrypoint()
        return
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication([])
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "seguisym.ttf"):
        font = font_dir / name
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(application_icon())
    captures = PROJECT_DIR / "docs" / "screenshots"
    captures.mkdir(parents=True, exist_ok=True)
    catalog = Catalog.load(PROJECT_DIR / "data")
    dimensions = {}
    with tempfile.TemporaryDirectory(prefix="pce-ui-") as temporary:
        window = MainWindow(catalog, Path(temporary))
        window.resize(1280, 700)
        window.show()
        QTest.qWait(300)

        def capture(name: str) -> None:
            QTest.qWait(100)
            assert window.grab().save(str(captures / f"{name}.png"))
            dimensions[name] = [window.width(), window.height()]
            for scroll in window.pages.currentWidget().findChildren(QScrollArea):
                assert scroll.horizontalScrollBar().maximum() == 0

        capture("accueil-1366")
        window.resize(1880, 980)
        QTest.qWait(100)
        # Le gestionnaire de fenêtres Windows peut borner la taille à l'écran
        # réel. Le rendu offscreen vérifie alors la grande résolution.
        if window.size().width() == 1880 and window.size().height() == 980:
            capture("accueil-1920")
        window.resize(1280, 700)
        window.new_challenge("black2")
        page = window.challenge_page
        page.preset_combo.setCurrentIndex(page.preset_combo.findData("chaos"))
        page.preset_combo.activated.emit(page.preset_combo.currentIndex())
        page.seed_edit.setText("482193")
        page.count_spin.setValue(5)
        QTest.mouseClick(page.generate_button, Qt.MouseButton.LeftButton)
        assert page.challenge is not None, page.feedback.text()
        assert len(page.challenge.active_rules) == 5
        page.name_edit.setText("Noir 2 · Aventure de démonstration")
        capture("challenge-1366")
        page.save_profile()
        assert len(window.profiles.list_profiles()) == 1
        scroll = page.findChild(QScrollArea)
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        capture("challenge-apercu-1366")
        window.navigate(2)
        capture("regles-1366")
        window.navigate(3)
        capture("profils-1366")
        window.navigate(4)
        capture("parametres-1366")
        dialog = MonotypeDialog(catalog.types, 482193, parent=window)
        dialog.animation_duration_ms = 120
        dialog.show()
        QTest.mouseClick(dialog.roll_button, Qt.MouseButton.LeftButton)
        QTest.qWait(250)
        assert dialog.configuration()["type_id"] == dialog.wheel.pointer_type_id()
        assert dialog.grab().save(str(captures / "monotype.png"))
        dialog.accept()
        window.close()
        app.processEvents()
    print(json.dumps({"resultat": "OK", "plateforme": app.platformName(), "dimensions": dimensions,
                      "parcours": "génération, sauvegarde, rechargement, navigation, roue"}, ensure_ascii=False))


def verify_entrypoint() -> None:
    """Exécute app.main sur données isolées, sans parcourir les disques utilisateur."""
    import app.main as application
    from app.services.retrobat_discovery_service import RetroBatDiscoveryService
    import logging

    original_show = MainWindow.show
    original_project = application.PROJECT_DIR
    original_drives = RetroBatDiscoveryService._drives
    opened: list[bool] = []

    def show_and_close(window: MainWindow) -> None:
        original_show(window)
        opened.append(window.isVisible())
        def close_after_setup():
            window.close()
            if window.isVisible():
                QTimer.singleShot(200, close_after_setup)
        QTimer.singleShot(500, close_after_setup)

    MainWindow.show = show_and_close
    sys.argv = sys.argv[:1]
    with tempfile.TemporaryDirectory(prefix="pce-entrypoint-") as temporary:
        try:
            application.PROJECT_DIR = Path(temporary)
            shutil.copytree(original_project / "data", application.PROJECT_DIR / "data")
            RetroBatDiscoveryService._drives = staticmethod(lambda: ())
            code = application.main()
            assert code == 0 and opened == [True]
            print("Point d'entrée app.main : fenêtre Windows affichée, boucle Qt exécutée, fermeture propre (code 0), données isolées.")
        finally:
            logging.shutdown()
            MainWindow.show = original_show
            application.PROJECT_DIR = original_project
            RetroBatDiscoveryService._drives = staticmethod(original_drives)


if __name__ == "__main__":
    main()
