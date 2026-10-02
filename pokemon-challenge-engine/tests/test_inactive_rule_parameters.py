"""Une préférence possible n'est ni une règle active ni une contrainte sauvegardée."""

from copy import deepcopy
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.core.challenge_engine import ChallengeEngine
from app.core.profile_manager import ProfileManager
from app.models.challenge import Challenge
from app.ui.challenge_page import ChallengePage, challenge_summary


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def page(qt_app, catalog, tmp_path):
    widget = ChallengePage(catalog, ProfileManager(tmp_path / "profiles"))
    widget.mode_combo.setCurrentIndex(widget.mode_combo.findData("custom"))
    widget.seed_edit.setText("482193")
    yield widget
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


@pytest.mark.parametrize("state", ["possible", "forbidden"])
def test_inactive_parameters_never_reach_model_or_serialization(catalog, state):
    engine = ChallengeEngine(catalog)
    draft = {"level_cap": {"max_level": 1}, "catch_limit": {"per_zone": 99}}
    mono = engine.generate("white", "custom", {"monotype": "required"}, 1, 1).monotype
    result = engine.generate("white", "custom", {"monotype": state, "level_cap": state, "catch_limit": state},
                             0, 482193, settings={"rule_parameters": draft}, monotype=mono)
    assert result.active_rules == []
    assert result.monotype is None
    assert result.settings["rule_parameters"] == {}
    assert result.to_dict()["settings"]["rule_parameters"] == {}
    assert draft == {"level_cap": {"max_level": 1}, "catch_limit": {"per_zone": 99}}


def test_legacy_inactive_drafts_normalize_without_rewriting_source(catalog, tmp_path):
    engine = ChallengeEngine(catalog)
    value = engine.generate("white", "normal", {}, 0, 42).to_dict()
    value["settings"]["rule_parameters"] = {"level_cap": {"max_level": 1}, "catch_limit": {"per_zone": 99}}
    value["monotype"] = engine.generate("white", "custom", {"monotype": "required"}, 1, 42).monotype
    path = tmp_path / "legacy-profile.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    before = path.read_bytes()
    loaded = Challenge.from_dict(json.loads(path.read_text(encoding="utf-8")))
    assert loaded.monotype is None and loaded.settings["rule_parameters"] == {}
    assert path.read_bytes() == before


@pytest.mark.parametrize("rule,key,value", [("level_cap", "max_level", 37), ("catch_limit", "per_zone", 3)])
def test_active_parameters_survive_manager_restart(catalog, tmp_path, rule, key, value):
    challenge = ChallengeEngine(catalog).generate("white2", "custom", {rule: "required"}, 1, 482193,
        settings={"rule_parameters": {rule: {key: value}}})
    saved = ProfileManager(tmp_path).create("Paramètre actif", challenge)
    loaded = ProfileManager(tmp_path).load(saved.id).challenge
    assert loaded.settings["rule_parameters"] == {rule: {key: value}}
    assert loaded.active_rules == [rule]
    assert loaded.game_id == "white2" and loaded.seed == 482193 and loaded.mode == "custom"


def test_possible_and_forbidden_rule_editors_are_hidden(page):
    for rule in ("monotype", "level_cap", "catch_limit"):
        for state in ("possible", "forbidden"):
            page.state_controls[rule].setCurrentIndex(page.state_controls[rule].findData(state))
            if rule == "monotype":
                assert page.monotype_row.isHidden()
                assert not page.wheel_button.isEnabled()
                assert "tirage" not in page.monotype_label.text()
            else:
                for control in page.parameter_controls[rule].values():
                    assert control.isHidden()
                    assert not control.isEnabled()


def test_monotype_draft_is_hidden_when_rule_is_disabled(page):
    page.state_controls["monotype"].setCurrentIndex(0)
    page.generate()
    original = deepcopy(page.monotype_config)
    assert original and not page.monotype_row.isHidden()
    page.state_controls["monotype"].setCurrentIndex(1)
    assert page.monotype_row.isHidden()
    page.generate()
    assert page.challenge.monotype is None
    assert "Monotype :" not in page.preview.toPlainText()
    page.state_controls["monotype"].setCurrentIndex(0)
    page.generate()
    assert page.challenge.monotype == original


@pytest.mark.parametrize("mode,label", [("soft", "Souple"), ("strict", "Strict"), ("pure", "Pur")])
def test_active_monotype_displays_type_and_mode_only_while_active(page, mode, label):
    page.state_controls["monotype"].setCurrentIndex(0)
    page.generate()
    page.monotype_config["mode"] = mode
    page.invalidate()
    page.generate()
    type_name = next(item["name"] for item in page.catalog.types if item["id"] == page.challenge.monotype["type_id"])
    assert f"{type_name} · {label}" in page.monotype_label.text()
    assert f"{type_name} · {label}" in page.preview.toPlainText()
    page.state_controls["monotype"].setCurrentIndex(1)
    assert page.monotype_row.isHidden()
    assert type_name not in page.monotype_label.text()


def test_active_level_cap_field_is_editable_but_inactive_value_is_ignored(page):
    control = page.parameter_controls["level_cap"]["max_level"]
    page.state_controls["level_cap"].setCurrentIndex(0)
    assert control.isEnabled() and not control.isHidden()
    control.setValue(37)
    page.generate()
    assert page.challenge.settings["rule_parameters"]["level_cap"]["max_level"] == 37
    page.state_controls["level_cap"].setCurrentIndex(1)
    page.generate()
    assert "level_cap" not in page.challenge.settings["rule_parameters"]
    assert "Niveau maximum" not in page.preview.toPlainText()


def test_random_possible_becomes_editable_only_when_actually_selected(page, catalog):
    page.mode_combo.setCurrentIndex(page.mode_combo.findData("random"))
    for rule, combo in page.state_controls.items():
        combo.setCurrentIndex(combo.findData("possible" if rule == "level_cap" else "forbidden"))
    page.count_spin.setValue(1)
    assert not page.parameter_controls["level_cap"]["max_level"].isEnabled()
    page.generate()
    assert page.challenge.active_rules == ["level_cap"]
    control = page.parameter_controls["level_cap"]["max_level"]
    assert control.isEnabled() and not control.isHidden()
    control.setValue(44)
    page.generate()
    assert page.challenge.settings["rule_parameters"]["level_cap"]["max_level"] == 44


def test_support_terminology_is_current_and_does_not_claim_enforcement(page, catalog):
    assert page.rules_table.horizontalHeaderItem(1).text() == "Niveau de support"
    page.generate()
    summary = challenge_summary(page.challenge, catalog)
    assert "Suivi uniquement" in summary
    assert "Règles imposées directement dans le jeu : aucune" in summary
    assert "V0.1" not in summary and "SOFT" not in summary
