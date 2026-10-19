"""Synthetic exported conditions only; no ROM, Java or evolution in game tested."""

from copy import deepcopy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.core.run_manager import RunManager
from app.services.run_transformation_provider import RunTransformationProvider
from app.ui.run_dialogs import RunDetailsDialog
from app.ui.widgets.derived_evolutions import DerivedEvolutionsDialog, evolution_condition_text


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def row(method="LEVEL", parameter=16, form=0):
    return {"species_id": 1, "form": form, "evolutions": [25], "evolution_conditions": [
        {"species_id": 25, "form": 0, "method": method, "parameter": parameter}]}


def test_only_explicit_level_method_is_interpreted():
    assert "niveau 16" in evolution_condition_text(row())
    unknown = evolution_condition_text(row("NEW_METHOD", 16))
    assert "non interprétée" in unknown and "NEW_METHOD" in unknown and "16" in unknown
    assert "niveau 16" not in unknown
    assert "non interprétée" in evolution_condition_text(row("LEVEL", 0))


def test_old_report_targets_never_invent_conditions():
    old = {"species_id": 1, "form": 0, "evolutions": [2]}
    assert "non enregistrées" in evolution_condition_text(old)
    assert "niveau" not in evolution_condition_text(old)
    assert "Aucune évolution exposée" in evolution_condition_text({**old, "evolution_conditions": []})


def test_extra_individual_is_not_described_as_identity_evolution():
    assert "individu supplémentaire" in evolution_condition_text(row("LEVEL_IS_EXTRA", 20))


def test_dialog_preserves_forms_and_does_not_mutate_report(qt_app):
    data = {"pokemon": [row(parameter=42, form=1), row(parameter=16)]}
    before = deepcopy(data)
    dialog = DerivedEvolutionsDialog(data)
    assert "niveau 16" in dialog.conditions_view.toPlainText()
    dialog.species_combo.setCurrentIndex(1)
    assert "forme 1" in dialog.species_combo.currentText()
    assert "niveau 42" in dialog.conditions_view.toPlainText()
    assert data == before
    dialog.close()


def test_details_recheck_provenance_before_opening_conditions(qt_app, catalog, tmp_path, monkeypatch):
    manager = RunManager(tmp_path / "runs")
    run = manager.create("Partie", "white")
    original = manager.load(run.run_id).to_dict()
    dialog = RunDetailsDialog(catalog, manager, run.run_id)
    run.rules_snapshot["active_rules"] = ["randomizer"]
    data = {"game_id": "white", "rom_sha256": run.rom_fingerprint, "categories": ["evolutions"],
            "pokemon": [row()], "source": "verified-derived-rom"}
    monkeypatch.setattr(RunTransformationProvider, "for_run", lambda *args: data)
    dialog.set_run(run)
    assert dialog.evolutions_button.isEnabled()

    def altered(*args):
        raise ValueError("Provenance modifiée")

    monkeypatch.setattr(RunTransformationProvider, "for_run", altered)
    monkeypatch.setattr(DerivedEvolutionsDialog, "exec", lambda self: pytest.fail("unverified report displayed"))
    dialog.evolutions_button.click()
    assert "Provenance modifiée" in dialog.error_label.text()
    assert manager.load(run.run_id).to_dict() == original
    dialog.close()
