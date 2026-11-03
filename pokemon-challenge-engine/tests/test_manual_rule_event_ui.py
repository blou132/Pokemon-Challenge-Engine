"""Qt workflow over synthetic declarations; no emulator or personal saves."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QDialog

from app.core.manual_rule_event import active_declarations
from app.services.run_controller import _RunWorker
from app.ui.game_mode_page import GameModePage
from app.ui.run_dialogs import RunDetailsDialog
from app.ui.runs_page import RunCard
from app.ui.widgets.manual_rule_event import ManualRuleEventDialog
from test_rule_observation import tracking


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def close(widget, app):
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_declaration_requires_confirmation_and_changes_reset_it(qt_app, tmp_path):
    _, _, service = tracking(tmp_path, ["no_healing", "no_items"])
    dialog = ManualRuleEventDialog(service.active_run)
    try:
        dialog.accept()
        assert dialog.result() != QDialog.DialogCode.Accepted
        dialog.confirmation.setChecked(True)
        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("battle_healing_item"))
        assert not dialog.confirmation.isChecked()
        dialog.confirmation.setChecked(True)
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.payload()["kind"] == "battle_healing_item"
        assert not active_declarations(service.active_run.history)
    finally:
        close(dialog, qt_app)


def test_correction_requires_a_reason_and_keeps_original_entry(qt_app, tmp_path):
    _, _, service = tracking(tmp_path, ["no_healing"])
    original = service.record_rule_event("healing_move", confirmed=True).history[-1]
    dialog = ManualRuleEventDialog(service.active_run)
    try:
        dialog.previous_combo.setCurrentIndex(1)
        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData(None))
        dialog.confirmation.setChecked(True)
        dialog.accept()
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert "raison" in dialog.error_label.text()
        dialog.note_edit.setPlainText("Erreur de déclaration")
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted
        service.record_rule_event(**dialog.payload())
        assert not active_declarations(service.active_run.history)
        assert original in service.active_run.history
    finally:
        close(dialog, qt_app)


def test_rules_button_routes_only_through_owner_worker(qt_app, tmp_path, catalog, monkeypatch):
    manager, initial, service = tracking(tmp_path, ["no_items", "no_healing"])
    dialog = RunDetailsDialog(catalog, manager, initial.run_id)
    worker = _RunWorker(manager.root)
    worker.tracker = service
    failures = QSignalSpy(worker.failed)
    request = QSignalSpy(dialog.action_requested)

    def choose(form):
        form.kind_combo.setCurrentIndex(form.kind_combo.findData("battle_healing_item"))
        form.confirmation.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ManualRuleEventDialog, "exec", choose)
    try:
        assert not dialog.rule_event_button.isHidden()
        dialog.rule_event_button.click()
        assert request.count() == 1
        assert not active_declarations(manager.load(initial.run_id).history)
        worker.action(*request.at(0))
        assert failures.count() == 0
        saved = manager.load(initial.run_id)
        assert len(active_declarations(saved.history)) == 1
        dialog.set_run(saved)
        text = dialog.rules_view.toPlainText()
        assert "Écart déclaré manuellement" in text and "Aucune détection automatique" in text
        row = dialog.history_table.rowCount() - 1
        assert dialog.history_table.item(row, 2).text() == "Manuel"
        assert "Objet de soin volontaire" in dialog.history_table.item(row, 3).text()
    finally:
        close(dialog, qt_app)


@pytest.mark.parametrize("rules,enabled", [([], False), (["no_items"], True), (["no_pokemon_center"], True),
    (["nuzlocke"], True), (["solo_run"], True), (["no_evolution"], True), (["level_cap"], False)])
def test_action_is_available_only_for_relevant_rules(qt_app, tmp_path, catalog, rules, enabled):
    manager, run, _ = tracking(tmp_path, rules)
    page = GameModePage(catalog)
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    try:
        page.set_persistent_run(run)
        assert page.manual_actions["record_rule_event"].isEnabled() is enabled
        assert dialog.rule_event_button.isHidden() is not enabled
    finally:
        close(dialog, qt_app)
        close(page, qt_app)


def test_encounter_dialog_worker_counters_and_correction_flow(qt_app, tmp_path, catalog):
    manager, initial, service = tracking(tmp_path, ["nuzlocke", "catch_limit"],
                                       params={"catch_limit": {"per_zone": 2}})
    form = ManualRuleEventDialog(service.active_run)
    worker = _RunWorker(manager.root)
    worker.tracker = service
    failures = QSignalSpy(worker.failed)
    try:
        assert form.kind_combo.currentData() == "wild_encounter"
        assert form.outcome_combo.currentData() == "unknown"
        form.species_spin.setValue(504)
        form.zone_edit.setText("Route 1")
        form.outcome_combo.setCurrentIndex(form.outcome_combo.findData("captured"))
        form.confirmation.setChecked(True)
        form.accept()
        assert form.result() == QDialog.DialogCode.Accepted
        worker.action(initial.run_id, "record_rule_event", form.payload())
        assert failures.count() == 0
    finally:
        close(form, qt_app)
    saved = manager.load(initial.run_id)
    page = GameModePage(catalog)
    dialog = RunDetailsDialog(catalog, manager, initial.run_id)
    card = RunCard(saved, catalog)
    correction = ManualRuleEventDialog(saved)
    try:
        page.set_persistent_run(saved)
        assert "Captures · Manuel : 1" in page.capture_count_label.text()
        assert "Captures : 1 (manuel)" in card.stats_label.text()
        assert "Capturé" in dialog.history_table.item(dialog.history_table.rowCount() - 1, 3).text()
        correction.previous_combo.setCurrentIndex(1)
        assert correction.species_spin.value() == 504
        assert correction.zone_edit.text() == "Route 1"
        assert correction.outcome_combo.currentData() == "captured"
        correction.outcome_combo.setCurrentIndex(correction.outcome_combo.findData("player_fled"))
        correction.note_edit.setPlainText("J'ai fui, ce n'était pas une capture")
        correction.confirmation.setChecked(True)
        worker.action(initial.run_id, "record_rule_event", correction.payload())
        assert failures.count() == 0
        page.set_persistent_run(manager.load(initial.run_id))
        assert "Non renseigné" in page.capture_count_label.text()
        assert len(service.active_run.history) > len(saved.history)
    finally:
        for widget in (page, dialog, card, correction):
            close(widget, qt_app)


def test_encounter_correction_preserves_stable_zone_and_resets_confirmation(qt_app, tmp_path):
    _, _, service = tracking(tmp_path, ["nuzlocke"])
    service.record_rule_event("wild_encounter", confirmed=True,
        zone={"capture_zone_id": "route-1", "name": "Route 1"},
        details={"species_id": 504, "outcome": "escaped", "encounter_kind": "wild_standard"})
    form = ManualRuleEventDialog(service.active_run)
    try:
        form.previous_combo.setCurrentIndex(1)
        assert form.payload()["zone"]["capture_zone_id"] == "route-1"
        form.confirmation.setChecked(True)
        form.species_spin.setValue(506)
        assert not form.confirmation.isChecked()
        form.zone_edit.clear()
        assert form.payload()["zone"] is None
    finally:
        close(form, qt_app)
