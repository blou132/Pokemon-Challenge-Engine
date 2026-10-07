"""Intégration Qt + fichiers JSON temporaires ; aucun jeu ni émulateur réel."""

from dataclasses import replace
import json
import os
from pathlib import Path
from threading import Event
from time import monotonic, sleep, time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QThread, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from app.bridge.state import BridgeState
from app.services.bridge_controller import BridgeController
from app.services.bridge_service import BridgeService
from app.services.config_service import AppConfig
from app.services.emulator_service import EmulatorService
from app.ui.bridge_page import BridgePage, UNAVAILABLE
from app.ui.main_window import MainWindow
from app.ui.theme import STYLESHEET


@pytest.fixture(scope="module")
def qt_app():
    application = QApplication.instance() or QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf"):
        font = Path("C:/Windows/Fonts") / name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    yield application
    application.processEvents()


@pytest.fixture
def connection(qt_app, catalog, tmp_path):
    clock = [100.0]
    bridge = BridgeService(tmp_path / "runtime" / "bridge", clock=lambda: clock[0])
    controller = BridgeController(tmp_path, bridge=bridge)
    page = BridgePage(catalog, controller, AppConfig())
    yield qt_app, page, controller, bridge, clock
    controller.shutdown()
    page.close()
    page.deleteLater()
    controller.deleteLater()
    qt_app.processEvents()


def until(application, predicate, timeout=3.0):
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        application.processEvents()
        QTest.qWait(10)
        # qWait pumps Qt but can retain the GIL while worker filesystem calls
        # need to reacquire it. Yield as the native QApplication loop does.
        sleep(0.001)
    assert predicate(), "L'état Qt attendu n'a pas été reçu dans le délai de test."


def prepare(connection):
    application, page, controller, _, _ = connection
    page.prepare_button.click()
    until(application, lambda: controller.state.status == "waiting")


def publish(bridge, sequence, **changes):
    payload = {
        "protocol_version": 1, "session_id": bridge.session_id, "sequence": sequence,
        "event": "hello", "timestamp": int(time()), "emulator": "desmume", "script_version": "0.2.0",
        "game_id": "black", "game_code": "IRBF", "game_region": "FR", "rom_revision": 0,
        "capabilities": ["heartbeat", "game_identity"], "memory_profile": None,
        "party_size": None, "party": None, "error": None,
    } | changes
    temporary = bridge.session_dir / "test-message.tmp"
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(bridge.session_dir / f"snapshot-{sequence}.json")


def test_connection_starts_lazily_and_has_no_fabricated_values(connection):
    _, page, controller, bridge, _ = connection
    assert controller._thread is None
    assert bridge.session_dir is None
    assert page.status_label.text() == "Arrêtée"
    assert page.game_label.text() == UNAVAILABLE
    assert page.party_size_label.text() == UNAVAILABLE
    assert page.party_note.text() == UNAVAILABLE
    assert page.party_table.rowCount() == 0
    assert not page.stop_button.isEnabled()
    assert "expérimentale" in page.validation_note.text()
    assert "ne constituent pas une validation" in page.validation_note.text()


def test_connection_offers_the_four_distinct_gen5_games(connection):
    _, page, _, _, _ = connection
    assert [(page.game_combo.itemData(index), page.game_combo.itemText(index))
            for index in range(page.game_combo.count())] == [
        ("black", "Pokémon Noir"), ("white", "Pokémon Blanc"),
        ("black2", "Pokémon Noir 2"), ("white2", "Pokémon Blanc 2"),
    ]


@pytest.mark.parametrize("game_id,code,name", [
    ("white", "IRAF", "Pokémon Blanc"), ("white2", "IRDF", "Pokémon Blanc 2"),
])
def test_white_identity_profile_and_team_reach_ui_from_synthetic_messages(connection, game_id, code, name):
    application, page, controller, bridge, _ = connection
    page.game_combo.setCurrentIndex(page.game_combo.findData(game_id))
    prepare(connection)
    assert bridge.state.expected_game == game_id
    publish(bridge, 1, game_id=game_id, game_code=code, memory_profile=f"{game_id}_fr_rev0")
    until(application, lambda: controller.state.status == "connected")
    assert page.game_label.text() == name
    assert page.region_label.text() == f"FR / {code}"
    assert page.revision_label.text() == "0"
    assert page.memory_profile_label.text() == f"{game_id}_fr_rev0"
    publish(bridge, 2, game_id=game_id, game_code=code, memory_profile=f"{game_id}_fr_rev0",
            event="party_update", capabilities=["heartbeat", "game_identity", "party_size", "party_level", "party_species", "party_hp"],
            party_size=1, party=[{"slot": 1, "level": 5, "species_id": 501, "hp": 18, "max_hp": 22}])
    until(application, lambda: controller.state.status == "receiving")
    assert page.party_size_label.text() == "1"
    assert [page.party_table.item(0, column).text() for column in range(4)] == ["1", "5", "501", "18 / 22"]
    assert "ne constituent pas une validation" in page.validation_note.text()


def test_prepare_waits_for_lua_and_exposes_exact_script_path(connection):
    _, page, controller, bridge, _ = connection
    prepared = QSignalSpy(controller.prepared)
    prepare(connection)
    assert prepared.count() == 1
    assert Path(page.script_path.text()) == bridge.session_dir / "connect.lua"
    assert Path(page.script_path.text()).is_file()
    assert page.status_label.text() == "En attente du script Lua"
    assert "Tools > Lua Scripting > New Lua Script" in page.instructions.text()
    assert controller._thread.isRunning()
    assert bridge.session_dir.is_dir()
    assert not page.prepare_button.isEnabled()
    assert page.party_size_label.text() == UNAVAILABLE


def test_json_heartbeat_and_party_reach_ui_without_inventing_unknowns(connection):
    application, page, controller, bridge, _ = connection
    prepare(connection)
    publish(bridge, 1)
    until(application, lambda: controller.state.status == "connected")
    assert page.status_label.text() == "Connectée au script Lua"
    assert page.game_label.text() == "Pokémon Noir"
    assert page.region_label.text() == "FR / IRBF"
    assert page.revision_label.text() == "0"
    assert page.party_size_label.text() == UNAVAILABLE
    assert page.memory_profile_label.text() == UNAVAILABLE
    assert page.protocol_label.text() == "1"
    assert page.script_version_label.text() == "0.2.0"
    assert page.timestamp_label.text() != UNAVAILABLE
    assert page.event_label.text() == "hello"

    publish(bridge, 2, event="party_update", memory_profile="test-fixture-black",
            capabilities=["heartbeat", "game_identity", "party_size", "party_level", "party_species", "party_hp"],
            party_size=2, party=[
                {"slot": 1, "level": 5, "species_id": 495, "hp": 0, "max_hp": 21},
                {"slot": 2, "level": None, "species_id": None, "hp": None, "max_hp": None},
            ])
    until(application, lambda: controller.state.status == "receiving")
    assert page.party_size_label.text() == "2"
    assert page.party_table.rowCount() == 2
    assert [page.party_table.item(0, column).text() for column in range(4)] == ["1", "5", "495", "0 / 21"]
    assert [page.party_table.item(1, column).text() for column in range(4)] == ["2", UNAVAILABLE, UNAVAILABLE, UNAVAILABLE]
    assert page.memory_profile_label.text() == "test-fixture-black"
    assert page.received_label.text() == "2"


def test_missing_heartbeat_disconnects_and_clears_team(connection):
    application, page, controller, bridge, clock = connection
    prepare(connection)
    publish(bridge, 1, event="party_update", memory_profile="test-fixture-black",
            capabilities=["heartbeat", "game_identity", "party_size"], party_size=0, party=[])
    until(application, lambda: controller.state.status == "receiving")
    assert page.party_size_label.text() == "0"
    assert page.party_note.text() == "Équipe vide."
    clock[0] += 4
    until(application, lambda: controller.state.status == "disconnected")
    assert page.status_label.text() == "Déconnectée"
    assert page.party_size_label.text() == UNAVAILABLE
    assert page.party_note.text() == UNAVAILABLE
    assert page.party_table.rowCount() == 0
    assert "Aucun message Lua" in page.error_label.text()
    assert page.prepare_button.isEnabled()


def test_bad_json_is_visible_then_valid_message_recovers(connection):
    application, page, controller, bridge, _ = connection
    prepare(connection)
    (bridge.session_dir / "snapshot-1.json").write_text("{broken", encoding="utf-8")
    until(application, lambda: controller.state.status == "error")
    assert page.status_label.text() == "Erreur"
    assert page.error_label.text()
    assert page.received_label.text() == "0"
    publish(bridge, 1)
    until(application, lambda: controller.state.status == "connected")
    assert page.error_label.isHidden()
    assert page.received_label.text() == "1"


def test_rom_prepare_error_does_not_crash_and_can_be_retried(connection):
    application, page, controller, _, _ = connection
    failed = QSignalSpy(controller.failed)
    page.set_config(AppConfig(rom_paths={"black": str(controller.base_dir / "missing.nds")}))
    page.prepare_button.click()
    until(application, lambda: controller.state.status == "error" and failed.count() == 1)
    assert page.error_label.text()
    assert page.prepare_button.isEnabled()
    assert page.script_path.text() == ""
    page.set_config(AppConfig())
    prepare(connection)
    assert page.error_label.isHidden()


def test_preparation_poll_and_stop_run_in_worker(connection, monkeypatch):
    application, _, controller, bridge, _ = connection
    thread_calls = []
    original_prepare = EmulatorService.prepare
    original_poll = bridge.poll
    original_stop = bridge.stop

    def record_prepare(service, *args):
        thread_calls.append(("prepare", QThread.currentThread()))
        return original_prepare(service, *args)

    def record_poll():
        thread_calls.append(("poll", QThread.currentThread()))
        return original_poll()

    def record_stop():
        thread_calls.append(("stop", QThread.currentThread()))
        return original_stop()

    monkeypatch.setattr(EmulatorService, "prepare", record_prepare)
    monkeypatch.setattr(bridge, "poll", record_poll)
    monkeypatch.setattr(bridge, "stop", record_stop)
    prepare(connection)
    until(application, lambda: any(name == "poll" for name, _ in thread_calls))
    worker_thread = controller._thread
    finished = QSignalSpy(worker_thread.finished)
    controller.shutdown()
    assert finished.count() == 1
    assert not worker_thread.isRunning()
    assert all(thread is worker_thread and thread is not application.thread() for _, thread in thread_calls)
    assert {name for name, _ in thread_calls} == {"prepare", "poll", "stop"}
    assert controller._thread is None
    assert bridge.state.status == "stopped"
    controller.shutdown()


def test_ui_event_loop_remains_responsive_during_preparation(connection, monkeypatch):
    application, page, controller, _, _ = connection
    entered, release = Event(), Event()
    original_prepare = EmulatorService.prepare

    def held_prepare(service, *args):
        entered.set()
        assert release.wait(3.0), "Le test n'a pas libéré la préparation."
        return original_prepare(service, *args)

    monkeypatch.setattr(EmulatorService, "prepare", held_prepare)
    timer = QTimer()
    timer.setSingleShot(True)
    ticked = QSignalSpy(timer.timeout)
    try:
        page.prepare_button.click()
        until(application, entered.is_set)
        timer.start(10)
        until(application, lambda: ticked.count() == 1)
        assert not page.prepare_button.isEnabled()
    finally:
        release.set()
    until(application, lambda: controller.state.status == "waiting")


def test_stop_resets_connection_and_second_game_can_be_prepared(connection):
    application, page, controller, bridge, _ = connection
    prepare(connection)
    old_session = bridge.session_id
    page.stop_button.click()
    until(application, lambda: controller.state.status == "stopped")
    assert page.script_path.text() == ""
    assert page.game_combo.isEnabled()
    page.game_combo.setCurrentIndex(page.game_combo.findData("black2"))
    prepare(connection)
    assert Path(page.script_path.text()) == bridge.session_dir / "connect.lua"
    assert bridge.state.expected_game == "black2"
    assert bridge.session_id != old_session
    publish(bridge, 1, game_id="black2", game_code="IREF")
    until(application, lambda: controller.state.status == "connected")
    assert page.game_label.text() == "Pokémon Noir 2"


def test_process_id_does_not_falsely_connect_lua(connection):
    _, page, controller, _, _ = connection
    page.track_process(SimpleNamespace(pid=4321))
    assert page.pid_label.text() == "4321"
    assert controller.state.status == "stopped"
    assert page.status_label.text() == "Arrêtée"


def test_timestamp_outside_platform_range_is_not_a_gui_crash(connection):
    _, page, _, _, _ = connection
    page.update_state(replace(BridgeState(), last_timestamp=10**100))
    assert page.timestamp_label.text() == "Horodatage non affichable"


@pytest.mark.parametrize("size", [(1110, 680), (1660, 980)])
def test_connection_page_scrolls_at_supported_resolutions(connection, size):
    application, page, _, _, _ = connection
    previous = application.styleSheet()
    application.setStyleSheet(STYLESHEET)
    try:
        page.resize(*size)
        page.show()
        application.processEvents()
        scroll = page.findChild(QScrollArea)
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.widget().width() <= scroll.viewport().width()
        scroll.ensureWidgetVisible(page.pid_label)
        application.processEvents()
        point = page.pid_label.mapTo(scroll.viewport(), page.pid_label.rect().center())
        assert scroll.viewport().rect().contains(point)
    finally:
        application.setStyleSheet(previous)


def test_window_navigation_config_and_close_connect_to_controller(qt_app, catalog, tmp_path):
    window = MainWindow(catalog, tmp_path)
    try:
        assert window.pages.count() == 6
        assert window.bridge_controller._thread is None
        window.nav_buttons[5].click()
        assert window.pages.currentWidget() is window.bridge_page
        new_config = AppConfig(rom_paths={"black": "D:/jeux/noir.nds"})
        window.config_changed(new_config)
        assert window.bridge_page.config is new_config
        window.close()
        assert window.bridge_controller._closed
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


@pytest.mark.parametrize("game_id", ["white", "white2"])
def test_white_challenge_is_selectable_and_generatable_in_window(qt_app, catalog, tmp_path, game_id):
    window = MainWindow(catalog, tmp_path)
    try:
        window.new_challenge(game_id)
        page = window.challenge_page
        assert page.game_combo.currentData() == game_id
        assert window.pages.currentWidget() is page
        page.seed_edit.setText("123")
        page.generate_button.click()
        assert page.challenge is not None and page.challenge.game_id == game_id
        assert page.challenge.active_rules
        assert game_id in window.settings_page.rom_edits
        assert window.bridge_page.game_combo.findData(game_id) >= 0
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_four_game_home_cards_fit_minimum_window(qt_app, catalog, tmp_path):
    window = MainWindow(catalog, tmp_path)
    previous = qt_app.styleSheet()
    qt_app.setStyleSheet(STYLESHEET)
    try:
        window.resize(1060, 640)
        window.show()
        qt_app.processEvents()
        scroll = window.home_page.findChild(QScrollArea)
        assert scroll.widget().width() <= scroll.viewport().width()
        assert scroll.horizontalScrollBar().maximum() == 0
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()
        qt_app.setStyleSheet(previous)
