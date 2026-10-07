"""Mode Jeu rendu avec profils et passerelle synthétiques ; aucun jeu lancé."""

import os
from dataclasses import replace
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from app.bridge.state import BridgeState
from app.core.challenge_engine import ChallengeEngine
from app.models.profile import Profile
from app.services.config_service import AppConfig
from app.services.game_mode_config import BLOCKS, GameModeConfigStore, defaults
from app.services.game_mode_service import RunState
from app.services.tracking_service import TrackingState
from app.ui.game_mode_page import GAME_MODE_STYLE, GameModePage
from app.ui.game_mode_settings import InterfaceInGamePage
from app.ui.main_window import MainWindow
from app.ui.theme import STYLESHEET


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    added_fonts = []
    # Offscreen Qt on Windows can expose no fonts at all. Layout measurements
    # must use the application's real font, as in the layout regression suite.
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


def profile(catalog, *, game="white", rules=(), name="Run de test"):
    states = {key: "required" if key in rules else "possible" for key in catalog.rules}
    challenge = ChallengeEngine(catalog).generate(game, "custom", states, 0, 482193)
    return Profile("test_run", name, challenge)


@pytest.fixture
def page(qt_app, catalog):
    widget = GameModePage(catalog)
    widget.setStyleSheet(STYLESHEET + GAME_MODE_STYLE)
    widget.game_combo.setCurrentIndex(widget.game_combo.findData("white"))
    yield widget
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


def team_state():
    return BridgeState(status="receiving", game_id="white", game_code="IRAF", game_region="FR", rom_revision=0,
        party_size=2, party=[{"slot": 1, "species_id": 511, "level": 15, "hp": 6, "max_hp": 42},
                             {"slot": 2, "species_id": 498, "level": 14, "hp": 45, "max_hp": 45}])


def test_team_six_slots_french_names_and_real_fields_only(page):
    page.set_bridge_state(team_state())
    assert len(page.team_slots) == 6
    assert "Feuillajou" in page.team_slots[0].name_label.text()
    assert page.team_slots[0].hp_label.text() == "6 / 42 PV"
    assert "Gruikui" in page.team_slots[1].name_label.text()
    assert "Non disponible" in page.team_slots[1].status_label.text()
    assert "Emplacement vide" in page.team_slots[2].name_label.text()


def test_disconnected_team_does_not_keep_live_claims(page):
    page.set_bridge_state(team_state())
    page.set_bridge_state(replace(team_state(), status="disconnected"))
    assert all("Non disponible" in item.name_label.text() for item in page.team_slots)
    assert all(item.hp_label.text() == "Non disponible" for item in page.team_slots)


def test_mismatching_profile_clears_received_team_immediately(page, catalog):
    page.set_bridge_state(team_state())
    page.set_profile(profile(catalog, game="black2"))
    assert "incompatibles" in page.team_note.text()
    assert "Feuillajou" not in page.team_slots[0].name_label.text()


def test_run_panel_uses_profile_counts_without_guessing_time_or_cap(page, catalog):
    run = profile(catalog, rules={"nuzlocke", "permanent_death", "species_clause"})
    run.progress["badges"] = ["Badge Trio"]
    run.progress["deaths"] = [{"species_id": 504}]
    run.progress["captures"] = [{"species_id": 511}]
    page.set_profile(run)
    assert page.profile_label.text() == "Run de test"
    assert page.stat_labels["badges"].text() == "1"
    assert page.stat_labels["deaths"].text() == "1"
    assert page.stat_labels["seed"].text() == "482193"
    assert page.stat_labels["level_cap"].text() == "Non disponible"
    assert page.time_label.text() == "Session PCE : Non disponible"
    assert "manuellement : 1" in page.capture_count_label.text()


def test_monotype_does_not_invent_team_type_compliance(page, catalog):
    page.set_profile(profile(catalog, rules={"monotype"}))
    page.set_bridge_state(team_state())
    assert "Validité de l'équipe : Non disponible" in page.monotype_label.text()
    assert "Types d'équipe non transmis" in page.monotype_label.text()


def test_randomizer_is_only_configured(page, catalog):
    page.set_profile(profile(catalog, rules={"randomizer"}))
    text = page.randomizer_label.text()
    assert "configuré, non appliqué" in text
    assert all(name in text.lower() for name in ("sauvages", "dresseurs", "objets", "attaques", "types", "talents"))


def test_nuzlocke_widget_reuses_persisted_result_and_unknowns(page):
    state = TrackingState(profile_name="Run", status="tracking", zone_name="Route 1", current_map_id=317,
                          zone_used=True, zone_status="captured", encounter={"species_id": 504, "level": 3, "result": "captured"})
    page.set_tracking_state(state)
    assert page.zone_label.text() == "Route 1"
    assert page.nuzlocke_widget.availability_label.text() == "Utilisée"
    assert page.nuzlocke_widget.result_label.text() == "Capturé"
    page.set_tracking_state(TrackingState())
    assert page.zone_label.text() == "Non disponible"


def test_speed_requested_and_confirmed_are_distinct(page):
    page.set_run_state(RunState(game_id="white", running=True, elapsed_seconds=3671, requested_speed="x4"))
    assert "État demandé : x4" in page.speed_label.text()
    assert "État réel : Non disponible" in page.speed_label.text()
    assert page.time_label.text() == "Session PCE : 01:01:11"
    spy = QSignalSpy(page.speed_requested)
    page.speed_buttons["x2"].click()
    assert spy.count() == 1 and spy.at(0) == ["x2"]


def test_connected_profile_cannot_be_changed(page, catalog):
    run = profile(catalog)
    page.set_profiles([run], run.id)
    page.set_bridge_state(team_state())
    assert not page.profile_combo.isEnabled()
    assert not page.game_combo.isEnabled()


def test_running_session_locks_profile_even_without_lua(page, catalog):
    page.set_profiles([profile(catalog)])
    page.set_run_state(RunState(game_id="white", running=True))
    page.set_bridge_state(BridgeState())
    assert not page.profile_combo.isEnabled()
    assert not page.game_combo.isEnabled()


def test_no_profile_still_rejects_team_from_another_selected_game(page):
    page.game_combo.setCurrentIndex(page.game_combo.findData("black"))
    page.set_bridge_state(team_state())
    assert "incompatibles" in page.team_note.text()
    assert "Feuillajou" not in page.team_slots[0].name_label.text()


def test_explicit_no_profile_clears_previous_selection(page, catalog):
    run = profile(catalog)
    page.set_profiles([run], run.id)
    page.set_profiles([run], None)
    assert page.profile_combo.currentData() is None
    assert page.profile_label.text() == "Sans profil"


@pytest.mark.parametrize("density,size", [("compact", (1366, 768)), ("standard", (1366, 768)), ("large", (1920, 1080))])
def test_layout_keeps_three_columns_accessible(page, qt_app, tmp_path, density, size):
    settings = defaults(AppConfig(), tmp_path)["interface"]
    settings["density"] = density
    page.set_interface(settings)
    page.resize(*size)
    page.show()
    qt_app.processEvents()
    assert page.width() == size[0]
    assert page.left_scroll.geometry().right() < page.center.geometry().left()
    assert page.center.geometry().right() < page.right_scroll.geometry().left()
    assert page.right_scroll.geometry().right() < page.width()
    assert page.center.width() >= 280
    assert not page.grab().isNull()


def test_block_visibility_and_side_are_customizable(page, tmp_path):
    settings = defaults(AppConfig(), tmp_path)["interface"]
    settings["visible"]["team"] = False
    settings["visible"]["debug"] = True
    settings["sides"]["zone"] = "left"
    page.set_interface(settings)
    assert page.blocks["team"].isHidden()
    assert not page.blocks["debug"].isHidden()
    assert page.left_layout.indexOf(page.blocks["zone"]) >= 0
    page.toggle_panels(False)
    assert page.left_scroll.isHidden() and page.right_scroll.isHidden()
    page.toggle_panels(True)
    assert not page.left_scroll.isHidden()


def test_interface_page_has_thirteen_independent_blocks(qt_app, tmp_path):
    widget = InterfaceInGamePage(defaults(AppConfig(), tmp_path)["interface"])
    assert set(widget.visible_checks) == set(BLOCKS)
    assert len(widget.visible_checks) == 13
    widget.visible_checks["logs"].setChecked(True)
    widget.side_combos["team"].setCurrentIndex(0)
    widget.density_combo.setCurrentIndex(widget.density_combo.findData("compact"))
    settings = widget.values()
    assert settings["visible"]["logs"] and settings["sides"]["team"] == "left"
    assert settings["density"] == "compact"
    assert settings["monitor_name"] == "" and not settings["auto_arrange"]
    widget.deleteLater()


def test_main_window_keeps_pages_and_game_mode_is_separate(qt_app, catalog, tmp_path):
    window = MainWindow(catalog, tmp_path)
    try:
        assert window.pages.count() == 7
        assert len(window.nav_group.buttons()) == 5
        window.game_mode_button.click()
        mode = window.game_mode_window
        assert mode is not None and mode.isWindow()
        assert window.pages.count() == 7
        assert mode.page.profile_combo.currentData() is None
        assert not (tmp_path / "game-mode.local.json").exists()
        mode.open_settings("interface")
        assert mode.settings_tabs.count() == 5
        assert mode.settings_tabs.currentWidget() is mode.interface_settings
        mode.interface_settings.visible_checks["debug"].setChecked(True)
        mode.interface_settings.save_button.click()
        assert mode.service.config["interface"]["visible"]["debug"] is True
        assert (tmp_path / "game-mode.local.json").exists()
        mode.set_shortcuts({"fullscreen": "Ctrl+Alt+F", "manual_backup": "Ctrl+Alt+B"})
        assert all(shortcut.context() == Qt.ShortcutContext.WindowShortcut for shortcut in mode._shortcuts.values())
        mode.bridge_requested.emit()
        assert window.pages.currentWidget() is window.bridge_page
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_associated_launch_profile_is_restored_without_overwriting_explicit_none(qt_app, catalog, tmp_path):
    window = MainWindow(catalog, tmp_path)
    try:
        saved = window.profiles.create("Run associée", profile(catalog).challenge)
        window.open_game_mode()
        mode = window.game_mode_window
        mode.refresh_profiles()
        mode.service.save_launch_profile("white", {"challenge_profile_id": saved.id})
        mode.page.game_combo.setCurrentIndex(mode.page.game_combo.findData("white"))
        assert mode.page.profile_combo.currentData() == saved.id
        mode.page.profile_combo.setCurrentIndex(0)
        assert mode.page.profile_combo.currentData() is None
        assert mode.page.game_combo.currentData() == "white"
        mode._game_changed("white", select_associated=False)
        assert mode.page.profile_combo.currentData() is None
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_open_game_mode_keeps_profile_already_selected_in_bridge(qt_app, catalog, tmp_path):
    window = MainWindow(catalog, tmp_path)
    try:
        saved = window.profiles.create("Profil Lua existant", profile(catalog).challenge)
        window.bridge_controller.tracking_state = TrackingState(profile_id=saved.id, profile_name=saved.name)
        window.open_game_mode()
        assert window.game_mode_window.page.profile_combo.currentData() == saved.id
        assert window.game_mode_window.page.game_combo.currentData() == "white"
        assert window.bridge_controller.tracking_state.profile_id == saved.id
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_bridge_navigation_uses_selected_games_launch_paths_without_changing_legacy_config(qt_app, catalog, tmp_path):
    window = MainWindow(catalog, tmp_path)
    try:
        window.config = AppConfig(retrobat_path="legacy-retrobat", desmume_path="legacy.exe",
                                  rom_paths={"black": "black.nds", "white": "old-white.nds"}, save_path="legacy-save")
        window.open_game_mode()
        mode = window.game_mode_window
        mode.service.save_launch_profile("white", {"emulator_path": "new-desmume.exe", "rom_path": "new-white.nds"})
        mode.page.game_combo.setCurrentIndex(mode.page.game_combo.findData("white"))
        mode.bridge_requested.emit()
        assert window.bridge_page.game_combo.currentData() == "white"
        assert window.bridge_page.profile_combo.currentData() is None
        assert window.bridge_page.config.desmume_path == "new-desmume.exe"
        assert window.bridge_page.config.rom_paths["white"] == "new-white.nds"
        assert window.bridge_page.config.rom_paths["black"] == "black.nds"
        assert window.bridge_page.config.save_path == "legacy-save"
        assert window.config.rom_paths["white"] == "old-white.nds"
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_bridge_navigation_does_not_replace_active_connection(qt_app, catalog, tmp_path):
    window = MainWindow(catalog, tmp_path)
    try:
        window.open_game_mode()
        mode = window.game_mode_window
        mode.page.game_combo.setCurrentIndex(mode.page.game_combo.findData("white"))
        window.bridge_page.game_combo.setCurrentIndex(window.bridge_page.game_combo.findData("black"))
        previous = window.bridge_page.config
        window.bridge_controller.state = BridgeState(status="receiving", game_id="black")
        mode.bridge_requested.emit()
        assert window.bridge_page.config is previous
        assert window.bridge_page.game_combo.currentData() == "black"
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_main_game_mode_shortcut_loads_and_updates_without_global_hook(qt_app, catalog, tmp_path):
    store = GameModeConfigStore(tmp_path, AppConfig())
    config = store.load()
    config["shortcuts"]["game_mode"] = "Ctrl+Alt+G"
    store.save(config)
    window = MainWindow(catalog, tmp_path)
    try:
        assert window._game_mode_shortcut.key().toString() == "Ctrl+Alt+G"
        assert window._game_mode_shortcut.context() == Qt.ShortcutContext.WindowShortcut
        window._game_mode_shortcut.activated.emit()
        assert window.game_mode_window.isVisible()
        window.game_mode_window._save_shortcuts({"game_mode": "Ctrl+Alt+M"})
        assert window._game_mode_shortcut.key().toString() == "Ctrl+Alt+M"
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_hiding_after_launch_keeps_run_timer_and_monitoring(qt_app, catalog, tmp_path, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    try:
        window.open_game_mode()
        mode = window.game_mode_window
        mode.service.save_launch_profile("white", {"game_mode": False})
        mode.page.game_combo.setCurrentIndex(mode.page.game_combo.findData("white"))
        def synthetic_launch(game_id, profile_id):
            mode.service.state = RunState(game_id=game_id, profile_id=profile_id, running=True)
            return object()
        monkeypatch.setattr(mode.service, "launch", synthetic_launch)
        mode.launch_game("white")
        from test_bridge_ui import until
        until(qt_app, lambda: not mode.launch_busy and mode.service.state.running)
        assert mode.isHidden()
        assert mode.timer.isActive()
        assert mode.service.state.running
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_arrangement_refuses_unverified_dpi_without_moving_windows(qt_app, catalog, tmp_path, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    try:
        window.open_game_mode()
        mode = window.game_mode_window
        mode.service.config["interface"]["monitor_name"] = "screen-test"
        mode.service.state = RunState(game_id="white", running=True)
        class SyntheticScreen:
            def name(self):
                return "screen-test"
            def devicePixelRatio(self):
                return 1.5
        monkeypatch.setattr(QApplication, "screens", lambda: [SyntheticScreen()])
        def unexpected_arrange(_rect):
            pytest.fail("Un DPI non vérifié ne doit déplacer aucune fenêtre.")
        monkeypatch.setattr(mode.service, "arrange", unexpected_arrange)
        mode.arrange_windows()
        assert "mise à l'échelle" in mode.page.status_label.text()
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()
