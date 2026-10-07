"""V0.4.1 main path with synthetic launch services; no game is opened here."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QDialog, QMessageBox

from app.core.challenge_engine import ChallengeEngine
from app.core.run_manager import RunManager
from app.services.game_mode_config import launch_defaults
from app.services.config_service import AppConfig
from app.services.run_controller import RunController, _RunWorker
from app.services.run_launch_service import RunLaunchService
from app.services.run_tracking_service import RunTrackingService
from app.ui.main_window import MainWindow
from app.ui.run_dialogs import NewRunDialog
from test_run_integration import create, qt_app, until


def preparation(service, run):
    return {"run_id": run.run_id, "game_id": run.game_id, "profile": deepcopy(run.launch_profile),
            "rom_fingerprint": None, "health": {"ready": False, "issues": ["Synthetic environment"]}}


def dialog_choice(window, monkeypatch, *, name="Blanc Classique", source="classic", profile=None, challenge=None):
    values = {"name": name, "game_id": "white", "source": source,
              "profile_id": profile.id if profile else None, "challenge": challenge.to_dict() if challenge else None,
              "save_path": "", "launch_profile": launch_defaults("white", AppConfig(), window.base_dir)}
    monkeypatch.setattr(NewRunDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(NewRunDialog, "selection", lambda self: deepcopy(values))
    monkeypatch.setattr(RunLaunchService, "prepare", preparation)
    return values


def selected(window, run_id):
    return (window.game_mode_window is not None and window.game_mode_window.persistent_run is not None
            and window.game_mode_window.persistent_run.run_id == run_id
            and window.run_controller.active_run is not None
            and window.run_controller.active_run.run_id == run_id)


def finish(window, app):
    until(app, lambda: not window.run_prepare.is_busy and not window.run_controller.activation_pending)
    if window._run_mismatch_dialog is not None:
        window._run_mismatch_dialog.close()
    window.close()
    app.processEvents()


def test_zero_to_one_created_card_visible_without_manual_refresh(qt_app, tmp_path, catalog, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    window.navigate(6)
    dialog_choice(window, monkeypatch)
    try:
        assert window.runs_page.visible_run_ids == []
        run = window.new_run()
        assert window.runs_page.visible_run_ids == [run.run_id]
        assert window.runs_page.highlighted_run_id == run.run_id
        assert "1 partie" in window.runs_page.summary.text() and "1 enregistrée" in window.runs_page.summary.text()
        assert window.runs_page.creation_feedback.text() == "Partie créée"
        assert window.game_mode_window is None  # no opening before the acknowledgement
        until(qt_app, lambda: selected(window, run.run_id))
        assert window.runs.active_id == run.run_id
    finally:
        finish(window, qt_app)


def test_creation_clears_only_filters_that_would_hide_new_card(qt_app, tmp_path, catalog, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    window.navigate(6)
    window.runs_page.search_edit.setText("No matching adventure")
    window.runs_page.status_combo.setCurrentIndex(window.runs_page.status_combo.findData("archived"))
    dialog_choice(window, monkeypatch)
    try:
        run = window.new_run()
        assert run.run_id in window.runs_page.visible_run_ids
        assert window.runs_page.cards[0].highlighted
    finally:
        finish(window, qt_app)


def test_run_a_to_new_b_binds_before_existing_game_window_is_shown(qt_app, tmp_path, catalog, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    first = create(window.runs, tmp_path, catalog, "A")
    monkeypatch.setattr(RunLaunchService, "prepare", preparation)
    try:
        window.resume_run(first.run_id)
        until(qt_app, lambda: selected(window, first.run_id))
        window._run_action(first.run_id, "set_badges", {"count": 3})
        window._run_action(first.run_id, "add_note", {"text": "Only in A"})
        until(qt_app, lambda: bool(window.run_controller.active_run.notes))
        mode = window.game_mode_window
        shown = []
        original_show = mode.show
        monkeypatch.setattr(mode, "show", lambda: (shown.append(mode.persistent_run.run_id), original_show()))
        dialog_choice(window, monkeypatch, name="B")
        second = window.new_run()
        until(qt_app, lambda: selected(window, second.run_id))
        assert shown and set(shown) == {second.run_id}
        assert window.game_mode_window is mode
        assert window._requested_run_id == window.run_controller.requested_run_id == window.runs.active_id == second.run_id
        assert second.name == "B" and second.total_play_seconds == 0
        assert second.current_party == [] and second.known_pokemon == {} and second.current_zone is None
        assert second.deaths is None and second.captures is None and second.badges is None and second.notes == []
        assert [event["type"] for event in second.history] == ["run_created"]
        assert window.runs.load(first.run_id).badges == 3
    finally:
        finish(window, qt_app)


def test_creating_b_while_a_runs_keeps_b_visible_and_never_opens_a_for_b(qt_app, tmp_path, catalog, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    first = create(window.runs, tmp_path, catalog, "A")
    monkeypatch.setattr(RunLaunchService, "prepare", preparation)
    try:
        window.resume_run(first.run_id)
        until(qt_app, lambda: selected(window, first.run_id))
        dialog_choice(window, monkeypatch, name="B")
        monkeypatch.setattr(window, "_session_busy", lambda: True)
        second = window.new_run()
        assert window.runs.active_id == first.run_id
        assert window._requested_run_id == second.run_id
        assert second.run_id in window.runs_page.visible_run_ids
        assert window.runs_page.highlighted_run_id == second.run_id
        assert not window.game_mode_window.isVisible()
        window.open_game_mode()
        assert not window.game_mode_window.isVisible()
        assert window._run_mismatch_dialog.text() == "La partie active ne correspond pas à celle demandée."
        assert {button.text() for button in window._run_mismatch_dialog.buttons()} == {"Réessayer", "Retour à Mes parties"}
        assert window.runs.load(second.run_id).current_party == []
    finally:
        finish(window, qt_app)


def test_multiple_sources_get_independent_ids_and_exact_custom_snapshot(qt_app, tmp_path, catalog, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    states = {key: "required" if key in {"nuzlocke", "permanent_death"} else "forbidden" for key in catalog.rules}
    challenge = ChallengeEngine(catalog).generate("white", "custom", states, 0, 123)
    profile = window.profiles.create("Shared configuration", challenge)
    runs = []
    try:
        for name, source in (("A", "classic"), ("B", "profile"), ("C", "custom")):
            dialog_choice(window, monkeypatch, name=name, source=source,
                          profile=profile if source == "profile" else None,
                          challenge=challenge if source == "custom" else None)
            run = window.new_run()
            runs.append(run)
            until(qt_app, lambda: selected(window, run.run_id))
            assert window.runs.active_id == run.run_id
        assert len({run.run_id for run in runs}) == 3
        assert runs[0].active_rules == ()
        assert runs[1].profile_id == profile.id
        assert runs[2].profile_id is None and runs[2].rules_snapshot == challenge.to_dict()
        assert set(runs[2].active_rules) == {"nuzlocke", "permanent_death"}
        profile.challenge.active_rules.clear()
        window.profiles.save(profile)
        assert window.runs.load(runs[1].run_id).rules_snapshot == challenge.to_dict()
    finally:
        finish(window, qt_app)


def test_create_failure_never_opens_game_mode(qt_app, tmp_path, catalog, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    dialog_choice(window, monkeypatch)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[1:]))
    monkeypatch.setattr(window.runs, "create", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("Synthetic denied")))
    try:
        assert window.new_run() is None
        assert window.game_mode_window is None and window.runs.list_runs() == []
        assert warnings[0][0] == "Partie non créée"
    finally:
        finish(window, qt_app)


def test_reopening_restores_b_selection_without_new_run_or_automatic_window(qt_app, tmp_path, catalog, monkeypatch):
    monkeypatch.setattr(RunLaunchService, "prepare", preparation)
    first_window = MainWindow(catalog, tmp_path)
    first = create(first_window.runs, tmp_path, catalog, "A")
    second = create(first_window.runs, tmp_path, catalog, "B")
    first_window.resume_run(second.run_id)
    until(qt_app, lambda: selected(first_window, second.run_id))
    finish(first_window, qt_app)
    reopened = MainWindow(catalog, tmp_path)
    try:
        until(qt_app, lambda: reopened.run_controller.active_run is not None)
        assert reopened._requested_run_id == reopened.run_controller.active_run.run_id == second.run_id
        assert reopened.runs.active_id == second.run_id
        assert reopened.game_mode_window is None
        reopened.navigate(6)
        assert reopened.runs_page.active_run_id == second.run_id
        reopened.open_game_mode()
        assert selected(reopened, second.run_id)
        assert {run.run_id for run in reopened.runs.list_runs()} == {first.run_id, second.run_id}
    finally:
        finish(reopened, qt_app)


def test_stale_controller_publications_cannot_replace_selected_b(qt_app, tmp_path, catalog):
    manager = RunManager(tmp_path / "runs")
    first, second = create(manager, tmp_path, catalog, "A"), create(manager, tmp_path, catalog, "B")
    controller = RunController(manager.root)
    try:
        controller.activate(first.run_id)
        old_token = controller._activation_token
        controller.activate(second.run_id)
        until(qt_app, lambda: controller.active_run is not None and controller.active_run.run_id == second.run_id)
        controller._receive(first, {"dirty": False})
        controller._receive_activation(old_token, first)
        controller._activation_failed(old_token, "Stale failure")
        assert controller.active_run.run_id == second.run_id
        assert manager.active_id == second.run_id
        assert "Stale failure" != controller.state.get("error")
    finally:
        assert controller.shutdown()


def test_two_phase_activation_persists_pointer_only_after_acknowledgement(qt_app, tmp_path, catalog):
    manager = RunManager(tmp_path / "runs")
    first, second = create(manager, tmp_path, catalog, "A"), create(manager, tmp_path, catalog, "B")
    manager.set_active_id(first.run_id)
    worker = _RunWorker(manager.root)
    prepared = []
    committed = []
    worker.activation_ready.connect(lambda token, run: prepared.append((token, run.run_id, manager.active_id)))
    worker.activated.connect(lambda token, run: committed.append((run.run_id, manager.active_id)))
    try:
        worker.activate(second.run_id, "request-B")
        assert prepared == [("request-B", second.run_id, first.run_id)]
        assert committed == []
        worker.commit_activation(second.run_id, "request-B")
        assert committed == [(second.run_id, second.run_id)]
    finally:
        worker.close()


def test_pointer_write_failure_does_not_acknowledge_or_show_new_run(qt_app, tmp_path, catalog, monkeypatch):
    manager = RunManager(tmp_path / "runs")
    first, second = create(manager, tmp_path, catalog, "A"), create(manager, tmp_path, catalog, "B")
    controller = RunController(manager.root)
    activated = []
    controller.activated.connect(lambda run: activated.append(run.run_id))
    try:
        controller.activate(first.run_id)
        until(qt_app, lambda: controller.active_run is not None)
        original = RunManager.set_active_id
        def denied(self, run_id):
            if run_id == second.run_id:
                raise PermissionError("Synthetic active.json denied")
            return original(self, run_id)
        monkeypatch.setattr(RunManager, "set_active_id", denied)
        controller.activate(second.run_id)
        until(qt_app, lambda: bool(controller.state.get("error")))
        assert controller.active_run.run_id == first.run_id
        assert manager.active_id == first.run_id and activated == [first.run_id]
        assert controller._worker.tracker.active_run.run_id == first.run_id
    finally:
        assert controller.shutdown()


def test_changed_active_json_blocks_mode_opening(qt_app, tmp_path, catalog, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    monkeypatch.setattr(RunLaunchService, "prepare", preparation)
    first, second = create(window.runs, tmp_path, catalog, "A"), create(window.runs, tmp_path, catalog, "B")
    try:
        window.resume_run(second.run_id)
        until(qt_app, lambda: selected(window, second.run_id))
        external = RunManager(window.runs.root)
        external.set_active_id(first.run_id)
        window.open_game_mode(second.run_id)
        assert not window.game_mode_window.isVisible()
        assert not window._validate_requested_run(second.run_id)
        assert window._run_mismatch_dialog is not None
    finally:
        finish(window, qt_app)


def test_pending_candidate_never_observes_before_commit_and_can_cancel(tmp_path, catalog):
    manager = RunManager(tmp_path / "runs")
    first, second = create(manager, tmp_path, catalog, "A"), create(manager, tmp_path, catalog, "B")
    tracker = RunTrackingService(manager)
    tracker.activate(first.run_id)
    tracker.prepare_activation(second.run_id)
    from test_run_integration import sample
    tracker.observe(sample().party, "Route 3", game_id="white", game_code="IRAF", region="FR", revision=0,
                    emulator_running=True)
    assert tracker.active_run.current_party == [] and not tracker.session_active
    assert manager.active_id == first.run_id
    tracker.cancel_activation()
    assert tracker.active_run.run_id == first.run_id
    assert manager.load(second.run_id).current_party == []
    tracker.close()


def test_preflight_latest_request_wins_and_old_reference_ack_cannot_launch(qt_app, tmp_path, catalog, monkeypatch):
    window = MainWindow(catalog, tmp_path)
    first, second = create(window.runs, tmp_path, catalog, "A"), create(window.runs, tmp_path, catalog, "B")
    queued = []
    runner = SimpleNamespace(is_busy=False)
    def start(operation):
        runner.is_busy = True
        queued.append(operation)
    runner.start = start
    window.run_prepare = runner
    monkeypatch.setattr(RunLaunchService, "prepare", preparation)
    try:
        window.resume_run(first.run_id)
        window.resume_run(second.run_id)
        assert window._requested_run_id == second.run_id
        runner.is_busy = False
        window._run_prepared(queued.pop(0)())
        assert window.game_mode_window is None and runner.is_busy
        runner.is_busy = False
        window._run_prepared(queued.pop(0)())
        until(qt_app, lambda: selected(window, second.run_id))
        calls = []
        monkeypatch.setattr(window.game_mode_window, "run_action_saved", lambda *args: calls.append(args))
        window._run_action_saved(first.run_id, "update_launch_reference", first)
        window._run_changed(first, {})
        assert calls == [] and selected(window, second.run_id)
    finally:
        runner.is_busy = False
        finish(window, qt_app)
