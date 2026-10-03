"""Native Qt widgets with synthetic persistent runs; no real emulator claim."""

from copy import deepcopy
import os
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QScrollArea

from app.core.challenge_engine import ChallengeEngine
from app.core.run_manager import RunManager
from app.models.profile import Profile
from app.models.run import history_event
from app.ui.run_dialogs import NewRunDialog, ManualRunEventDialog, RunDetailsDialog, prompt_run_action
from app.ui.runs_page import RunsPage
from app.ui.theme import STYLESHEET
from app.services.save_manager_service import SaveManagerService


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def manager(tmp_path):
    return RunManager(tmp_path / "runs")


def create(manager, catalog, name="Blanc Nuzlocke #1", game="white", rules=()):
    states = {key: "required" if key in rules else "possible" for key in catalog.rules}
    challenge = ChallengeEngine(catalog).generate(game, "custom" if rules else "normal", states, 0, 42)
    return manager.create(name, game, generation=catalog.games[game].generation, challenge=challenge)


def close(widget, qt_app):
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


@pytest.mark.parametrize("count", [0, 1, 20])
def test_library_zero_one_twenty_runs(qt_app, catalog, manager, count):
    for index in range(count):
        create(manager, catalog, f"Partie {index:02d}")
    page = RunsPage(catalog, manager)
    assert len(page.cards) == count
    assert len(page.visible_run_ids) == count
    assert page.empty_label.isHidden() == bool(count)
    assert str(count) in page.summary.text()
    if count == 0:
        assert "Aucune partie" in page.empty_label.text()
    close(page, qt_app)


def test_library_unknown_counts_are_not_zero(qt_app, catalog, manager):
    create(manager, catalog)
    page = RunsPage(catalog, manager)
    text = page.cards[0].stats_label.text()
    for field in ("Captures", "Morts", "Badges"):
        assert f"{field} : Non renseigné" in text
    close(page, qt_app)


def test_library_search_casefold_name(qt_app, catalog, manager):
    first = create(manager, catalog, "Blanc Nuzlocke")
    create(manager, catalog, "Noir Classique", "black")
    page = RunsPage(catalog, manager)
    page.search_edit.setText("  BLANC  ")
    assert page.visible_run_ids == [first.run_id]
    page.search_edit.setText("absent")
    assert not page.visible_run_ids
    assert "filtres" in page.empty_label.text()
    close(page, qt_app)


@pytest.mark.parametrize("combo,value", [("game_combo", "white"), ("challenge_combo", "nuzlocke"), ("status_combo", "active")])
def test_library_filters(qt_app, catalog, manager, combo, value):
    first = create(manager, catalog, rules=("nuzlocke", "permanent_death", "species_clause"))
    first.status = "active"
    manager.save(first)
    create(manager, catalog, "Noir Classique", "black")
    page = RunsPage(catalog, manager)
    control = getattr(page, combo)
    control.setCurrentIndex(control.findData(value))
    assert page.visible_run_ids == [first.run_id]
    close(page, qt_app)


def test_library_classic_filter(qt_app, catalog, manager):
    create(manager, catalog, rules=("monotype",))
    classical = create(manager, catalog, "Classique")
    page = RunsPage(catalog, manager)
    page.challenge_combo.setCurrentIndex(page.challenge_combo.findData("classic"))
    assert page.visible_run_ids == [classical.run_id]
    close(page, qt_app)


def test_generation_filter_not_hardwired_to_five(qt_app, catalog, manager):
    create(manager, catalog)
    other = manager.create("Future génération", "future_game", generation=9)
    page = RunsPage(catalog, manager)
    page.generation_combo.setCurrentIndex(page.generation_combo.findData(9))
    assert page.visible_run_ids == [other.run_id]
    close(page, qt_app)


def test_future_generation_does_not_invent_eight_badges(qt_app, catalog, manager):
    run = manager.create("Future génération", "future_game", generation=9)
    run.badges = 12
    manager.save(run)
    page = RunsPage(catalog, manager)
    assert "Badges : 12 (manuel)" in page.cards[0].stats_label.text()
    details = page.open_details(run.run_id)
    assert details.badge_plus.isEnabled()
    assert "Badges : 12 · MANUEL" in details.progress_label.text()
    close(details, qt_app)
    close(page, qt_app)


@pytest.mark.parametrize("sort,expected", [("name", ["Alpha", "Zeta"]), ("time", ["Zeta", "Alpha"]),
                                           ("created", ["Alpha", "Zeta"]), ("last_played", ["Zeta", "Alpha"])])
def test_library_sort(qt_app, catalog, manager, sort, expected):
    zeta = create(manager, catalog, "Zeta")
    zeta.total_play_seconds = 500
    zeta.last_played_at = "2026-10-03T12:00:00+00:00"
    zeta.sessions.append({"session_id": str(uuid4()), "started_at": "2026-10-03T11:51:40+00:00",
                          "last_heartbeat": zeta.last_played_at, "ended_at": zeta.last_played_at, "duration": 500})
    manager.save(zeta)
    create(manager, catalog, "Alpha")
    page = RunsPage(catalog, manager)
    page.sort_combo.setCurrentIndex(page.sort_combo.findData(sort))
    assert [card.name_label.text() for card in page.cards] == expected
    close(page, qt_app)


def test_resume_emits_existing_id_without_creating_run(qt_app, catalog, manager):
    run = create(manager, catalog)
    page = RunsPage(catalog, manager)
    spy = QSignalSpy(page.resume_requested)
    page.cards[0].resume_button.click()
    assert spy.at(0) == [run.run_id]
    assert len(manager.list_runs()) == 1
    page.set_active_run(run.run_id)
    assert page.cards[0].status_label.text() == "PARTIE ACTIVE"
    close(page, qt_app)


def test_archived_requires_explicit_status_change(qt_app, catalog, manager):
    run = create(manager, catalog)
    run.status = "archived"
    manager.save(run)
    page = RunsPage(catalog, manager)
    assert not page.cards[0].resume_button.isEnabled()
    close(page, qt_app)


def test_new_classic_zero_rules_and_optional_save(qt_app, catalog):
    dialog = NewRunDialog(catalog, [], {})
    dialog.game_combo.setCurrentIndex(dialog.game_combo.findData("white"))
    dialog.name_edit.setText("Blanc Classique")
    values = dialog.selection()
    assert values["profile_id"] is None
    assert values["save_path"] is None
    assert values["launch_profile"] is None
    assert "0 règle active" in dialog.rules_label.text()
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    close(dialog, qt_app)


def test_new_from_profile_copies_launch_configuration(qt_app, catalog):
    challenge = ChallengeEngine(catalog).generate("white", "normal", {}, 0, 42)
    profile = Profile("source", "Ma configuration", challenge)
    launch = {"white": {"game_id": "white", "rom_path": "game.nds", "emulator_path": "desmume.exe", "save_path": "first.dsv"}}
    dialog = NewRunDialog(catalog, [profile], launch, profile=profile)
    dialog.save_edit.setText("chosen.dsv")
    values = dialog.selection()
    assert values["profile_id"] == "source"
    assert values["game_id"] == "white"
    assert values["launch_profile"]["save_path"] == "chosen.dsv"
    values["launch_profile"]["rom_path"] = "changed.nds"
    assert launch["white"]["rom_path"] == "game.nds"
    assert launch["white"]["save_path"] == "first.dsv"
    close(dialog, qt_app)


def test_profile_choices_follow_game(qt_app, catalog):
    profile = Profile("source", "Configuration Blanc", ChallengeEngine(catalog).generate("white", "normal", {}, 0, 42))
    dialog = NewRunDialog(catalog, [profile], {}, profile=profile)
    dialog.game_combo.setCurrentIndex(dialog.game_combo.findData("black"))
    assert dialog.selection()["profile_id"] is None
    assert dialog.profile_combo.findData("source") == -1
    close(dialog, qt_app)


def test_new_run_empty_name_not_accepted(qt_app, catalog):
    dialog = NewRunDialog(catalog, [], {})
    dialog.name_edit.setText("   ")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert not dialog.error_label.isHidden()
    close(dialog, qt_app)


def detail_fixture(manager, catalog):
    run = create(manager, catalog, rules=("nuzlocke", "permanent_death", "species_clause"))
    pokemon = {"slot": 1, "species_id": 498, "level": 23, "current_hp": 77, "max_hp": 77,
               "personality_id": 3987654321, "original_trainer_id": 3123456789,
               "pokemon_key": "known-one", "life_status": "dead"}
    run.current_party = [pokemon]
    run.known_pokemon = {"known-one": pokemon}
    run.deaths = [{"death_id": str(uuid4()), "pokemon_key": "known-one", "pokemon": deepcopy(pokemon),
                   "zone": "Route 4", "date": "2026-10-03T12:00:00+00:00", "note": "Combat", "source": "manual", "corrected": False}]
    run.history.append(history_event("manual_death", "manual", {"pokemon": pokemon}, "2026-10-03T12:00:00+00:00"))
    # Detailed rendering uses a supplied in-memory run, independently from store validators.
    return run


def test_six_detail_sections_and_unknown_stats(qt_app, catalog, manager):
    run = create(manager, catalog)
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    assert [dialog.tabs.tabText(index) for index in range(6)] == ["Aperçu", "Progression", "Équipe", "Règles", "Historique", "Sauvegardes"]
    assert "Captures : Non renseigné" in dialog.progress_label.text()
    assert "Badges : Non renseigné" in dialog.progress_label.text()
    assert not dialog.badge_minus.isEnabled()
    assert "Aucune sauvegarde" in dialog.save_label.text()
    close(dialog, qt_app)


def test_graveyard_preserves_dead_after_healing_and_excludes_raw_pid(qt_app, catalog, manager):
    run = detail_fixture(manager, catalog)
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    dialog.set_run(run)
    assert "Gruikui" in dialog.graveyard.item(0).text()
    assert "Route 4" in dialog.graveyard.item(0).text()
    assert dialog.team_table.item(0, 2).text() == "77 / 77"
    assert dialog.team_table.item(0, 3).text() == "☠ Mort"
    assert "3987654321" not in dialog.graveyard.item(0).text()
    assert "3987654321" not in dialog.history_table.item(dialog.history_table.rowCount() - 1, 3).text()
    run.current_party = []
    dialog.set_run(run)
    assert dialog.graveyard.count() == 1
    close(dialog, qt_app)


@pytest.mark.parametrize("answer,expected", [(QMessageBox.StandardButton.Yes, 1), (QMessageBox.StandardButton.No, 0)])
def test_correction_requires_confirmation_and_dispatches_id(qt_app, catalog, manager, monkeypatch, answer, expected):
    run = detail_fixture(manager, catalog)
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    dialog.set_run(run)
    dialog.graveyard.setCurrentRow(0)
    spy = QSignalSpy(dialog.action_requested)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: answer)
    dialog.correction_button.click()
    assert spy.count() == expected
    assert len(run.history) == 2
    if expected:
        run_id, action, payload = spy.at(0)
        assert run_id == run.run_id and action == "correct_death"
        assert payload["death_id"] == run.deaths[0]["death_id"]
        assert payload["confirmed"] is True
    close(dialog, qt_app)


def test_corrected_death_disappears_from_graveyard_not_history(qt_app, catalog, manager):
    run = detail_fixture(manager, catalog)
    run.deaths[0]["corrected"] = True
    run.history.append(history_event("death_corrected", "manual", {"note": "Erreur corrigée"}))
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    dialog.set_run(run)
    assert dialog.graveyard.count() == 0
    assert dialog.history_table.rowCount() == 3
    assert "Morts : 0" in dialog.progress_label.text()
    close(dialog, qt_app)


def test_rules_technical_snapshot_exact_and_collapsed(qt_app, catalog, manager):
    import json
    run = create(manager, catalog, rules=("nuzlocke", "permanent_death", "species_clause"))
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    assert dialog.technical_view.isHidden()
    assert json.loads(dialog.technical_view.toPlainText()) == run.rules_snapshot
    assert "figées" in dialog.rules_view.toPlainText()
    close(dialog, qt_app)


def test_badges_manual_signal_does_not_invent_auto_reading(qt_app, catalog, manager):
    run = create(manager, catalog)
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    spy = QSignalSpy(dialog.action_requested)
    dialog.badge_plus.click()
    assert spy.at(0) == [run.run_id, "set_badges", {"count": 1}]
    assert run.badges is None
    assert "MANUEL" in dialog.progress_label.text()
    close(dialog, qt_app)


def test_save_manager_reused_by_signal(qt_app, catalog, manager):
    run = create(manager, catalog)
    page = RunsPage(catalog, manager)
    spy = QSignalSpy(page.saves_requested)
    details = page.open_details(run.run_id)
    details.saves_requested.emit(run.run_id)
    assert spy.at(0) == [run.run_id]
    close(details, qt_app)
    close(page, qt_app)


def test_detail_last_backup_uses_exact_save_and_lazy_inventory(qt_app, catalog, manager, tmp_path, monkeypatch):
    source = tmp_path / "first.dsv"
    second = tmp_path / "second.dsv"
    source.write_bytes(b"first synthetic save")
    second.write_bytes(b"second synthetic save")
    service = SaveManagerService(tmp_path / "backups")
    expected = service.backup(source, "white")
    unrelated = service.backup(second, "white")
    run = create(manager, catalog)
    run.save_path = str(source)
    run.launch_profile = {"backup_directory": str(service.root)}
    manager.save(run)
    calls = []
    original = SaveManagerService.list_backups_for_save
    def inventory(self, *args):
        calls.append(args)
        return original(self, *args)
    monkeypatch.setattr(SaveManagerService, "list_backups_for_save", inventory)
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    assert not calls
    dialog.tabs.setCurrentIndex(5)
    assert len(calls) == 1
    assert expected.filename in dialog.backup_label.text()
    assert unrelated.filename not in dialog.backup_label.text()
    dialog.set_run(run)
    assert len(calls) == 1
    close(dialog, qt_app)


def test_manual_death_known_individual_retains_identity(qt_app, catalog, manager):
    run = detail_fixture(manager, catalog)
    run.known_pokemon["known-two"] = dict(run.known_pokemon["known-one"], slot=2, personality_id=12)
    dialog = ManualRunEventDialog("manual_death", run)
    assert dialog.pokemon_combo.count() == 3
    dialog.pokemon_combo.setCurrentIndex(dialog.pokemon_combo.findData("known-two"))
    assert dialog.payload()["pokemon_key"] == "known-two"
    assert "3987654321" not in dialog.pokemon_combo.itemText(1)
    dialog.pokemon_combo.setEditText("Autre Gruikui")
    values = dialog.payload()
    assert "pokemon_key" not in values
    assert values["pokemon"] == "Autre Gruikui"
    close(dialog, qt_app)


@pytest.mark.parametrize("action", ["manual_capture", "manual_death"])
def test_manual_event_requires_explicit_pokemon(qt_app, catalog, manager, action):
    run = create(manager, catalog)
    dialog = ManualRunEventDialog(action, run)
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.pokemon_combo.setEditText("Gruikui")
    dialog.zone_edit.setText("Route 3")
    dialog.note_edit.setPlainText("Saisie utilisateur")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    values = dialog.payload()
    assert values["pokemon"] == "Gruikui" and values["zone"] == "Route 3"
    assert "T" in values["date"]
    close(dialog, qt_app)


def test_note_requires_text(qt_app, catalog, manager):
    dialog = ManualRunEventDialog("add_note", create(manager, catalog))
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.note_edit.setPlainText("Premier badge")
    dialog.accept()
    assert dialog.payload() == {"text": "Premier badge"}
    close(dialog, qt_app)


def test_pending_death_confirmation_keeps_review_identity(qt_app, catalog, manager, monkeypatch):
    run = detail_fixture(manager, catalog)
    review_id = str(uuid4())
    run.pending_deaths = [{"review_id": review_id, "pokemon": {"species_id": 498, "current_hp": 0}, "zone": {"id": "route_3", "name": "Route 3"}}]
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    dialog.set_run(run)
    assert not dialog.pending_button.isHidden()
    assert "Gruikui" in dialog.pending_list.item(0).text()
    dialog.pending_list.setCurrentRow(0)
    spy = QSignalSpy(dialog.action_requested)
    monkeypatch.setattr(ManualRunEventDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    dialog.pending_button.click()
    values = spy.at(0)
    assert values[1] == "manual_death"
    assert values[2]["review_id"] == review_id
    assert values[2]["pokemon"] == "Gruikui"
    assert "pokemon_key" not in values[2]  # No assignment to same-species known individual.
    run.pending_deaths[0]["resolved"] = True
    dialog.set_run(run)
    assert dialog.pending_list.count() == 0
    assert dialog.pending_button.isHidden()
    close(dialog, qt_app)


def test_pending_death_cancel_does_not_mutate(qt_app, catalog, manager, monkeypatch):
    run = detail_fixture(manager, catalog)
    run.pending_deaths = [{"review_id": str(uuid4()), "pokemon": run.current_party[0], "zone": "Route 4"}]
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    dialog.set_run(run)
    dialog.pending_list.setCurrentRow(0)
    spy = QSignalSpy(dialog.action_requested)
    monkeypatch.setattr(ManualRunEventDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    dialog.pending_button.click()
    assert spy.count() == 0
    assert not run.pending_deaths[0].get("resolved", False)
    close(dialog, qt_app)


def test_status_change_confirmation_dispatches_without_mutating(qt_app, catalog, manager, monkeypatch):
    run = create(manager, catalog)
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    spy = QSignalSpy(dialog.action_requested)
    dialog.status_combo.setCurrentIndex(dialog.status_combo.findData("archived"))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    dialog._change_status()
    assert spy.count() == 0
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog._change_status()
    assert spy.at(0) == [run.run_id, "set_status", {"status": "archived"}]
    assert manager.load(run.run_id).status == "preparing"
    close(dialog, qt_app)


def test_history_summary_omits_technical_identifiers():
    payload = {"personality_id": 3987654321, "original_trainer_id": 3123456789,
               "pokemon_key": "pid:3987654321:3123456789", "pokemon": {"species_id": 498, "personality_id": 3987654321}}
    text = RunDetailsDialog._event_details(payload)
    assert text == "Gruikui"


def test_quick_action_cancel_returns_no_payload(qt_app, catalog, manager, monkeypatch):
    run = create(manager, catalog)
    monkeypatch.setattr(ManualRunEventDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    assert prompt_run_action(None, catalog, run, "manual_capture") is None


@pytest.mark.parametrize("size", [(1366, 768), (1920, 1080)])
@pytest.mark.parametrize("count", [0, 1, 20])
def test_library_and_details_fit_target_windows(qt_app, catalog, manager, size, count):
    for index in range(count):
        create(manager, catalog, f"Blanc Nuzlocke #{index + 1}")
    page = RunsPage(catalog, manager)
    page.setStyleSheet(STYLESHEET)
    page.resize(size[0] - 220, size[1] - 50)
    page.show()
    qt_app.processEvents()
    assert page.minimumSizeHint().width() <= size[0] - 220
    scroll = page.findChild(QScrollArea)
    if count == 20:
        assert scroll.verticalScrollBar().maximum() > 0
    assert not page.grab().isNull()
    if count:
        details = page.open_details(page.visible_run_ids[0])
        qt_app.processEvents()
        assert details.width() < size[0] and details.height() < size[1]
        assert not details.grab().isNull()
        close(details, qt_app)
    close(page, qt_app)
