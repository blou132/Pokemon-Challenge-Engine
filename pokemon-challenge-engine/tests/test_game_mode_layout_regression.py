"""Synthetic Qt layout checks; native Windows image reviews remain separate."""

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QFrame, QWidget

from app.bridge.state import BridgeState
from app.core.challenge_engine import ChallengeEngine
from app.core.run_manager import RunManager
from app.services.game_mode_service import RunState
from app.ui.game_mode_page import GAME_MODE_STYLE, GameModePage
from app.ui.theme import STYLESHEET


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    added_fonts = []
    # Windows' offscreen plugin does not discover installed fonts. Measure the
    # application's actual font rather than its empty-font fallback glyphs.
    if sys.platform == "win32" and not QFontDatabase.families():
        fonts = Path(os.environ["WINDIR"]) / "Fonts"
        for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
            font_id = QFontDatabase.addApplicationFont(str(fonts / filename))
            assert font_id >= 0
            added_fonts.append(font_id)
    yield app
    app.processEvents()
    for font_id in added_fonts:
        QFontDatabase.removeApplicationFont(font_id)


@pytest.mark.parametrize("width,height,density", [
    (1366, 768, "compact"),
    (1366, 768, "standard"),
    (1920, 1080, "standard"),
])
@pytest.mark.parametrize("phase,message", [
    ("waiting_script", "DeSmuME a démarré. Attente du heartbeat Lua…"),
    ("error", "Aucun heartbeat Lua reçu pour cette session. DeSmuME reste ouvert. "
     "Réessayez la connexion ou ouvrez le mode manuel pour charger le script de cette session."),
    ("connected", "Connexion Lua confirmée par le jeu."),
])
def test_persistent_run_and_lua_recovery_fit_target_size(
        qt_app, catalog, tmp_path, width, height, density, phase, message):
    states = {key: "required" if key in {"nuzlocke", "permanent_death", "species_clause"}
              else "possible" for key in catalog.rules}
    challenge = ChallengeEngine(catalog).generate("white", "custom", states, 0, 42)
    run = RunManager(tmp_path / "runs").create(
        "Blanc Nuzlocke — données synthétiques", "white", challenge=challenge)
    # An unshown parent preserves the requested widget dimensions even when the
    # physical monitor is smaller than the 1920x1080 test case.
    host = QWidget()
    page = GameModePage(catalog, host)
    try:
        page.setStyleSheet(STYLESHEET + GAME_MODE_STYLE)
        page.setFixedSize(width, height)
        page.set_interface({"density": density, "visible": {}, "sides": {}})
        page.set_persistent_run(run)
        page.set_bridge_state(BridgeState(
            status="connected" if phase == "connected" else "waiting",
            game_id="white", game_code="IRAF", game_region="FR", rom_revision=0,
            memory_profile="white_fr_rev0", protocol_version=2,
            session_id="synthetic-layout"))
        page.set_run_state(RunState(game_id="white", running=True, message=message))
        page.set_session_phase(phase, message)
        page.ensurePolished()
        page.show()
        qt_app.processEvents()
        rendered = page.grab()  # Activates all nested layouts before measurement.
        qt_app.processEvents()

        assert (rendered.width(), rendered.height()) == (width, height)
        assert not page.run_bar.isHidden()
        assert not page.recovery_row.isHidden()
        assert page.minimumSizeHint().width() <= width
        assert page.minimumSizeHint().height() <= height
        assert page.center.geometry().bottom() < page.height()
        assert page.left_scroll.geometry().right() < page.center.geometry().left()
        assert page.center.geometry().right() < page.right_scroll.geometry().left()

        placeholder = page.findChild(QFrame, "dsPlaceholder")
        assert placeholder is not None
        assert page.launch_button.y() > placeholder.geometry().bottom()
        assert page.launch_button.geometry().bottom() < page.status_label.y()
        assert page.status_label.geometry().bottom() < page.center.height()
        assert page.status_label.geometry().right() < page.center.width()
        assert page.status_label.height() >= page.status_label.heightForWidth(page.status_label.width())
        assert page.status_label.text() == message
    finally:
        page.close()
        host.close()
        host.deleteLater()
        qt_app.processEvents()
