"""Unavailable ROM patches cannot be selected or serialized as applied settings."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core.challenge_engine import ChallengeEngine
from app.services.rom_transformation_service import RomTransformationService
from app.ui.challenge_page import ChallengePage


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def page(qt_app, catalog, monkeypatch):
    def no_tool(*args, **kwargs):
        pytest.fail("The editor must not construct Java or a ROM transformation service")

    monkeypatch.setattr(RomTransformationService, "__init__", no_tool)
    widget = ChallengePage(catalog, None, configuration_only=True)
    yield widget
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


def shiny_challenge(catalog, game="white"):
    states = {rule: "required" if rule == "shiny_only" else "forbidden" for rule in catalog.rules}
    return ChallengeEngine(catalog).generate(game, "custom", states, 1, 42)


@pytest.mark.parametrize("game", ["black", "white", "black2", "white2"])
def test_shiny_editor_exposes_original_and_unavailable_rates(page, catalog, game):
    challenge = shiny_challenge(catalog, game)
    before = challenge.to_dict()
    page.load_challenge(challenge)
    assert not page.shiny_rate_group.isHidden()
    assert not page.extras_card.isHidden()
    combo = page.shiny_rate_combo
    assert combo.currentData() == "original"
    assert "1/8192" in combo.currentText()
    assert [combo.itemData(index) for index in range(1, combo.count())] == [4096, 1024, 512, 128, 1]
    assert combo.model().flags(combo.model().index(0, 0)) & Qt.ItemFlag.ItemIsEnabled
    reason = RomTransformationService.shiny_rate_support(game)["reason"]
    assert reason in page.shiny_rate_note.text()
    assert "bonus" in page.shiny_rate_note.text()
    for index in range(1, combo.count()):
        assert not combo.model().flags(combo.model().index(index, 0)) & Qt.ItemFlag.ItemIsEnabled
        assert reason in combo.itemData(index, Qt.ItemDataRole.ToolTipRole)
    assert challenge.to_dict() == before


def test_unavailable_rate_cannot_be_selected_or_written_to_challenge(page, catalog):
    page.load_challenge(shiny_challenge(catalog))
    combo = page.shiny_rate_combo
    QTest.keyClick(combo, Qt.Key.Key_End)
    assert combo.currentData() == "original"
    # Qt can set a disabled item programmatically: guard this route as well.
    combo.setCurrentIndex(combo.findData(512))
    assert combo.currentData() == "original"
    page.generate()
    assert page.challenge is not None, page.feedback.text()
    assert page.challenge.settings["rule_parameters"] == {}
    assert "taux" in page.preview.toPlainText().lower()
    assert "aucun patch" in page.preview.toPlainText().lower()


def test_shiny_group_follows_active_rule_and_normal_mode(page, catalog):
    assert page.shiny_rate_group.isHidden()
    page.load_challenge(shiny_challenge(catalog))
    assert not page.shiny_rate_group.isHidden()
    page.mode_combo.setCurrentIndex(page.mode_combo.findData("normal"))
    assert page.shiny_rate_group.isHidden()
    page.generate()
    assert "shiny_only" not in page.challenge.active_rules
    assert "1/8192" not in page.preview.toPlainText()


def test_backend_reason_is_visible_without_constructing_service(page, catalog, monkeypatch):
    monkeypatch.setattr(RomTransformationService, "shiny_rate_support", staticmethod(
        lambda game: {"original": True, "custom_denominators": [], "reason": "Profil FR : aucun patch vérifié."}))
    page.load_challenge(shiny_challenge(catalog))
    assert "Profil FR : aucun patch vérifié." in page.shiny_rate_note.text()
