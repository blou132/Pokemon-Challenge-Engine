"""Offscreen manual workflow tests; no emulator, Java or user save is touched."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QDialog

from app.core.allowed_pokemon import latest_designation
from app.services.run_controller import _RunWorker
from app.ui.run_dialogs import RunDetailsDialog
from app.ui.widgets.allowed_pokemon import AllowedPokemonDialog
from test_rule_observation import member, observe, tracking
from test_allowed_pokemon import designate


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def close(widget, app):
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_dialog_never_chooses_by_first_slot_or_species_and_requires_confirmation(qt_app, tmp_path):
    _, _, service = tracking(tmp_path, ["starter_only", "solo_run"])
    observe(service, [member(), member(pid=999, slot=2)])
    dialog = AllowedPokemonDialog(service.active_run)
    try:
        assert not dialog.pokemon_combo.isEditable()
        assert dialog.pokemon_combo.currentData() == ""
        dialog.accept()
        assert dialog.result() != QDialog.DialogCode.Accepted
        dialog.pokemon_combo.setCurrentIndex(2)
        dialog.accept()
        assert "explicitement" in dialog.error_label.text()
        assert "starter reçu" in dialog.confirm_check.text()
        dialog.confirm_check.setChecked(True)
        payload = dialog.payload()
        assert payload["pokemon_key"] == service.active_run.current_party[1]["pokemon_key"]
        assert payload["confirmed"] is True and payload["previous_event_id"] is None
        dialog.pokemon_combo.setCurrentIndex(1)
        assert not dialog.confirm_check.isChecked()
        assert latest_designation(service.active_run) is None
    finally:
        close(dialog, qt_app)


def test_ambiguous_and_weak_individuals_are_not_selectable(qt_app, tmp_path):
    _, _, service = tracking(tmp_path, ["solo_run"])
    observe(service, [member(), member(slot=2), member(pid=None, slot=3)])
    dialog = AllowedPokemonDialog(service.active_run)
    try:
        assert dialog.pokemon_combo.count() == 1
        dialog.confirm_check.setChecked(True)
        dialog.accept()
        assert dialog.result() != QDialog.DialogCode.Accepted
    finally:
        close(dialog, qt_app)


def test_removal_is_available_when_individual_no_longer_has_strong_identity(qt_app, tmp_path):
    _, _, service = tracking(tmp_path, ["solo_run"])
    observe(service, [member()])
    before = latest_designation(designate(service))
    observe(service, [member(), member(slot=2)])
    dialog = AllowedPokemonDialog(service.active_run)
    try:
        assert not dialog.candidates
        index = dialog.pokemon_combo.findData(None)
        assert index > 0
        dialog.pokemon_combo.setCurrentIndex(index)
        assert "retrait" in dialog.confirm_check.text()
        dialog.confirm_check.setChecked(True)
        payload = dialog.payload()
        assert payload["pokemon_key"] is None and payload["previous_event_id"] == before["event_id"]
        service.designate_allowed_pokemon(**payload)
        assert latest_designation(service.active_run)["payload"]["pokemon_key"] is None
    finally:
        close(dialog, qt_app)


def test_rules_tab_routes_explicit_choice_to_owner_worker_without_direct_writes(qt_app, tmp_path, catalog, monkeypatch):
    manager, run, service = tracking(tmp_path, ["starter_only", "solo_run"])
    observe(service, [member()])
    service.flush(force=True)
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    worker = _RunWorker(manager.root)
    worker.tracker = service
    spy = QSignalSpy(dialog.action_requested)

    def choose(form):
        form.pokemon_combo.setCurrentIndex(1)
        form.confirm_check.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(AllowedPokemonDialog, "exec", choose)
    before = (manager.root / run.run_id / "run.json").read_bytes()
    try:
        assert not dialog.designation_button.isHidden()
        dialog.designation_button.click()
        assert spy.count() == 1
        assert (manager.root / run.run_id / "run.json").read_bytes() == before
        run_id, action, payload = spy.at(0)
        assert run_id == run.run_id and action == "designate_allowed_pokemon"
        worker.action(run_id, action, payload)
        assert not worker.error
        updated = manager.load(run.run_id)
        dialog.set_run(updated)
        text = dialog.rules_view.toPlainText()
        assert "Origine starter déclarée, non prouvée" in text
        assert "combat inconnue" in text
        event = latest_designation(updated)
        summary = dialog._event_details(event["payload"])
        assert "Starter déclaré manuellement" in summary
        assert event["payload"]["pokemon_key"] not in summary
    finally:
        worker.close()
        close(dialog, qt_app)


def test_wrong_run_worker_action_cannot_select_individual(qt_app, tmp_path):
    manager, run, service = tracking(tmp_path, ["solo_run"])
    observe(service, [member()])
    other = manager.create("Other", "white", challenge=run.rules_snapshot)
    worker = _RunWorker(manager.root)
    worker.tracker = service
    try:
        worker.action(other.run_id, "designate_allowed_pokemon", {
            "pokemon_key": service.active_run.current_party[0]["pokemon_key"], "confirmed": True})
        assert worker.error
        assert latest_designation(service.active_run) is None
        assert latest_designation(manager.load(other.run_id)) is None
    finally:
        worker.close()


def test_classic_rules_view_has_no_designation_action(qt_app, tmp_path, catalog):
    manager, run, _ = tracking(tmp_path, [])
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    try:
        assert dialog.designation_button.isHidden()
        assert dialog._event_details({"purpose": {}, "note": "historique ancien"}) == "historique ancien"
    finally:
        close(dialog, qt_app)
