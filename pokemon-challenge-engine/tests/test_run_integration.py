"""Synthetic Qt/launch integration. No emulator or user save is opened."""

from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path
from time import monotonic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.bridge.state import BridgeState
from app.core.challenge_engine import ChallengeEngine
from app.core.run_manager import RunManager
from app.services.config_service import AppConfig
from app.services.game_mode_config import launch_defaults
from app.services.run_controller import RunController, _RunWorker
from app.services.run_launch_service import RunLaunchService
from app.services.run_tracking_service import RunTrackingService
from app.ui.game_mode_page import GameModePage
from app.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def until(app, predicate):
    end = monotonic() + 6
    while not predicate() and monotonic() < end:
        app.processEvents()
        QTest.qWait(5)
    assert predicate()


def create(manager, base, catalog, name="Blanc Nuzlocke"):
    states = {key: "required" if key in {"nuzlocke", "permanent_death"} else "possible" for key in catalog.rules}
    challenge = ChallengeEngine(catalog).generate("white", "custom", states, 0, 42)
    return manager.create(name, "white", challenge=challenge, game_code="IRAF", region="FR", revision=0,
                          launch_profile=launch_defaults("white", AppConfig(), base))


def sample(hp=20, sequence=1):
    return BridgeState(status="receiving", game_id="white", game_code="IRAF", game_region="FR", rom_revision=0,
        session_id="fixture", sequence=sequence, party_size=1,
        party=[{"slot": 1, "species_id": 498, "level": 10, "hp": hp, "max_hp": 30,
                "personality_id": 123, "original_trainer_id": 456}])


def test_worker_requires_owned_process_and_fresh_bridge_samples(qt_app, tmp_path, catalog):
    manager = RunManager(tmp_path / "runs")
    run = create(manager, tmp_path, catalog)
    clock = [0.0]
    worker = _RunWorker(tmp_path / "runs")
    worker.tracker = RunTrackingService(manager, clock=lambda: clock[0])
    worker.tracker.activate(run.run_id)
    worker.consume(sample())
    assert not worker.tracker.session_active
    worker.process_context(True, "black")
    worker.consume(sample())
    assert not worker.tracker.session_active
    worker.process_context(True, "white")
    worker.consume(sample())
    assert worker.tracker.session_active
    clock[0] = 2
    worker.consume(sample(sequence=2))
    assert worker.tracker.active_run.total_play_seconds == 2
    clock[0] = 20
    worker.consume(sample(sequence=2))  # repeated publication is not a new heartbeat
    worker.tick()
    assert not worker.tracker.session_active
    assert worker.tracker.active_run.total_play_seconds == 2
    worker.close()


def test_worker_rejects_unknown_actions_and_wrong_run(qt_app, tmp_path, catalog):
    manager = RunManager(tmp_path / "runs")
    one, two = create(manager, tmp_path, catalog), create(manager, tmp_path, catalog, "Autre")
    worker = _RunWorker(tmp_path / "runs")
    worker.tracker = RunTrackingService(manager)
    worker.tracker.activate(one.run_id)
    worker.action(two.run_id, "add_note", {"text": "Wrong run"})
    assert worker.error
    worker.action(one.run_id, "__getattribute__", {})
    assert worker.error
    assert manager.load(one.run_id).notes == []
    worker.action(one.run_id, "add_note", {"text": "Note explicite"})
    assert not worker.error
    assert len(manager.load(one.run_id).notes) == 1
    worker.close()


def test_controller_flushes_on_close_and_reopens_without_counting_offline(qt_app, tmp_path, catalog):
    manager = RunManager(tmp_path / "runs")
    run = create(manager, tmp_path, catalog)
    controller = RunController(tmp_path / "runs")
    controller.activate(run.run_id)
    until(qt_app, lambda: controller.active_run is not None)
    controller.action(run.run_id, "add_note", {"text": "Fermeture sûre"})
    assert controller.shutdown()
    saved = manager.load(run.run_id)
    assert len(saved.notes) == 1
    restored = RunTrackingService(RunManager(tmp_path / "runs"))
    assert restored.active_run.run_id == run.run_id
    assert restored.active_run.total_play_seconds == 0
    assert not restored.session_active
    restored.close()


def test_game_mode_keeps_death_after_live_heal_and_legacy_updates(qt_app, tmp_path, catalog):
    manager = RunManager(tmp_path / "runs")
    run = create(manager, tmp_path, catalog)
    tracker = RunTrackingService(manager)
    tracker.activate(run.run_id)
    for hp in (20, 0, 30):
        tracker.observe(sample(hp).party, "Route 3", game_id="white", game_code="IRAF", region="FR",
                        revision=0, emulator_running=True)
    page = GameModePage(catalog)
    page.set_persistent_run(tracker.active_run, {"last_saved_at": tracker.last_saved_at})
    page.set_bridge_state(sample(30))
    page.set_profile(None)
    assert "Mort" in page.team_slots[0].status_label.text()
    assert "30 / 30" in page.team_slots[0].hp_label.text()
    assert "Non renseigné" in page.stat_labels["badges"].text()
    assert "1" == page.stat_labels["deaths"].text()
    assert not page.game_combo.isEnabled()
    assert not page.profile_combo.isEnabled()
    assert "Sauvegarde Pokémon" in page.autosave_label.text()
    assert "123" not in page.team_slots[0].name_label.text()
    tracker.close()
    page.close()


def test_new_run_mode_displays_unknown_counts(qt_app, tmp_path, catalog):
    page = GameModePage(catalog)
    run = create(RunManager(tmp_path / "runs"), tmp_path, catalog)
    page.set_persistent_run(run)
    assert "Non renseigné" in page.capture_count_label.text()
    assert "Non renseigné" in page.stat_labels["deaths"].text()
    page.close()


def test_main_window_starts_with_library_and_resume_keeps_same_run(qt_app, tmp_path, catalog, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    run = create(window.runs, tmp_path, catalog)
    def prepare(service, selected):
        return {"run_id": selected.run_id, "profile": selected.launch_profile, "rom_fingerprint": None,
                "health": {"ready": False, "issues": ["Installation synthétique absente"]}}
    monkeypatch.setattr(RunLaunchService, "prepare", prepare)
    try:
        assert window.pages.count() == 7
        assert window.pages.currentWidget() is window.runs_page
        window.navigate(6)
        assert window.pages.count() == 7
        window.resume_run(run.run_id)
        until(qt_app, lambda: window.game_mode_window is not None and window.game_mode_window.persistent_run is not None)
        assert window.game_mode_window.persistent_run.run_id == run.run_id
        assert len(window.runs.list_runs()) == 1
        assert window.run_controller.active_run.total_play_seconds == 0
        window._run_action(run.run_id, "set_badges", {"count": 2})
        until(qt_app, lambda: window.run_controller.active_run.badges == 2)
        assert "2 / 8" in window.game_mode_window.page.stat_labels["badges"].text()
        assert window.bridge_page.persistent_game == "white"
        window.bridge_page.update_state(BridgeState())
        assert not window.bridge_page.profile_combo.isEnabled()
    finally:
        window.close()
        qt_app.processEvents()


def test_launch_snapshot_does_not_follow_mutable_global_setup(tmp_path):
    from types import SimpleNamespace
    from app.services.discovery_safety import file_hash
    from app.services.game_mode_config import GameModeConfigStore
    rom = tmp_path / "fixture.nds"
    rom.write_bytes(b"synthetic fixture, not a game")
    options = launch_defaults("white", AppConfig(), tmp_path)
    options["rom_path"] = str(rom)
    options["save_path"] = str(tmp_path / "owned.dsv")
    run = SimpleNamespace(run_id="local", game_id="white", launch_profile=deepcopy(options),
                          save_path=options["save_path"], rom_fingerprint=file_hash(rom))
    store = GameModeConfigStore(tmp_path, AppConfig())
    mutable = store.load()
    mutable["launch_profiles"]["white"]["rom_path"] = "another.nds"
    store.save(mutable)
    checks = []
    setup = SimpleNamespace(health_check=lambda game, **kw: (checks.append(kw) or {"ready": True, "issues": []}))
    result = RunLaunchService(tmp_path, AppConfig(), setup=setup).prepare(run)
    assert result["health"]["ready"]
    assert checks[0]["options_override"]["rom_path"] == str(rom)
    assert checks[0]["options_override"]["save_path"] == run.save_path
    assert store.load()["launch_profiles"]["white"]["rom_path"] == "another.nds"
    rom.write_bytes(b"different synthetic fixture")
    result = RunLaunchService(tmp_path, AppConfig(), setup=setup).prepare(run)
    assert not result["health"]["ready"]
    assert "ROM a changé" in result["health"]["issues"][0]


def test_launch_snapshot_keeps_archive_provenance(tmp_path):
    from types import SimpleNamespace
    options = launch_defaults("white", AppConfig(), tmp_path)
    options["rom_path"] = "prepared.nds"
    record = {"prepared_path": "prepared.nds", "source_path": "source.zip", "archive_member": "white.nds"}
    setup = SimpleNamespace(store=SimpleNamespace(load=lambda: {"games": {"white": record}}))
    snapshot = RunLaunchService(tmp_path, AppConfig(), setup=setup).snapshot("white", options, "chosen.dsv")
    assert snapshot["_source"]["source_path"] == "source.zip"
    assert snapshot["save_path"] == "chosen.dsv"
    assert options["save_path"] == ""


def test_launch_override_ignores_deleted_source_profile_and_keeps_global_preferences(tmp_path):
    from types import SimpleNamespace
    from app.services.game_mode_service import GameModeService
    configs = []
    class Launcher:
        def __init__(self, config):
            configs.append(config)
        def validate(self, game_id):
            return []
        def launch(self, game_id):
            return SimpleNamespace(pid=123, poll=lambda: None)
    windows = SimpleNamespace(running_executable=lambda path: False)
    mode = GameModeService(tmp_path, AppConfig(), launcher_factory=Launcher, window_manager=windows)
    old = deepcopy(mode.config)
    options = launch_defaults("white", AppConfig(), tmp_path)
    options.update(rom_path="run.nds", emulator_path="owned.exe", challenge_profile_id="deleted_profile")
    mode.launch("white", options_override=options)
    assert configs[0].rom_paths["white"] == "run.nds"
    assert mode.state.profile_id is None
    assert mode.config == old
    assert not mode.store.path.exists()


def test_controller_final_write_failure_can_be_retried(qt_app, tmp_path, catalog, monkeypatch):
    manager = RunManager(tmp_path / "runs")
    run = create(manager, tmp_path, catalog)
    controller = RunController(tmp_path / "runs")
    controller.activate(run.run_id)
    until(qt_app, lambda: controller.active_run is not None)
    original_save = RunManager.save
    def denied(self, run):
        raise PermissionError("Disque de test verrouillé")
    monkeypatch.setattr(RunManager, "save", denied)
    controller.action(run.run_id, "add_note", {"text": "À préserver"})
    until(qt_app, lambda: bool(controller.state.get("error")))
    assert not controller.shutdown()
    assert controller._thread.isRunning()
    monkeypatch.setattr(RunManager, "save", original_save)
    assert controller.shutdown()
    assert len(manager.load(run.run_id).notes) == 1


def test_session_started_during_resume_preflight_prevents_switch(qt_app, tmp_path, catalog):
    window = MainWindow(catalog, tmp_path)
    run = create(window.runs, tmp_path, catalog)
    try:
        window.bridge_controller.state = sample()
        window._run_prepared({"run_id": run.run_id})
        assert window.run_controller.active_run is None
        assert "pendant la vérification" in window.statusBar().currentMessage()
    finally:
        window.close()


def test_rapid_badge_clicks_apply_deltas_in_worker(qt_app, tmp_path, catalog):
    window = MainWindow(catalog, tmp_path)
    run = create(window.runs, tmp_path, catalog)
    window.runs.update(run.run_id, lambda item: setattr(item, "badges", 2))
    try:
        window.run_controller.activate(run.run_id)
        until(qt_app, lambda: window.game_mode_window is not None and window.game_mode_window.persistent_run is not None)
        mode = window.game_mode_window
        mode._quick_run_action("badge_increment")
        mode._quick_run_action("badge_increment")
        until(qt_app, lambda: window.run_controller.active_run.badges == 4)
        mode._quick_run_action("badge_decrement")
        mode._quick_run_action("badge_decrement")
        until(qt_app, lambda: window.run_controller.active_run.badges == 2)
        assert window.runs.load(run.run_id).badges == 2
    finally:
        window.close()
