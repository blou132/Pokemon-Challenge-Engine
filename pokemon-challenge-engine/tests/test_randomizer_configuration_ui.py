"""Qt configuration and local worker tests; no Java, ROM or emulator executed."""
from copy import deepcopy
import os
from pathlib import Path
from threading import Event
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QThread, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QFileDialog

from app.core.challenge_engine import ChallengeEngine
from app.core.profile_manager import ProfileManager
from app.services.rom_transformation_service import CATEGORIES, RandomizerOptions, RandomizerToolStore
from app.ui.challenge_page import ChallengePage
from app.ui.widgets.randomizer_configuration import RandomizerConfiguration, RandomizerToolVerificationDialog


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def widget(qt_app):
    value = RandomizerConfiguration()
    value.set_context("white", 512)
    yield value
    value.close()
    value.deleteLater()
    qt_app.processEvents()


@pytest.fixture
def page(qt_app, tmp_path, catalog):
    value = ChallengePage(catalog, ProfileManager(tmp_path / "profiles"))
    value.mode_combo.setCurrentIndex(value.mode_combo.findData("custom"))
    for combo in value.state_controls.values():
        combo.setCurrentIndex(combo.findData("possible"))
    value.state_controls["randomizer"].setCurrentIndex(0)
    value.seed_edit.setText("512")
    yield value
    value.close()
    value.deleteLater()
    qt_app.processEvents()


def wait_until(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def test_categories_are_exact_backend_capabilities_with_limits(widget):
    assert tuple(widget.category_checks) == CATEGORIES
    assert widget.options() == RandomizerOptions()
    assert "champions compris" in widget.category_checks["trainers"].text()
    assert "CT" in widget.category_checks["movesets"].toolTip()
    assert "terrain" in widget.category_checks["field_items"].text()
    assert "IRAF" in widget.compatibility_label.text()
    assert "à vérifier" in widget.compatibility_label.text()
    assert "sans import de sauvegarde" in widget.safety_label.text()
    assert "original" in widget.safety_label.text()


@pytest.mark.parametrize("game,code", [("black", "IRBF"), ("white", "IRAF"), ("black2", "IREF"), ("white2", "IRDF")])
def test_context_uses_distinct_game_identity_and_shared_challenge_seed(widget, game, code):
    widget.set_context(game, 0)
    assert code in widget.compatibility_label.text()
    assert "FR · révision 0" in widget.compatibility_label.text()
    assert "Seed du challenge : 0" in widget.seed_label.text()
    widget.set_context(game, 2**63 - 1)
    assert str(2**63 - 1) in widget.seed_label.text()


def test_unknown_context_is_not_compatible_and_invalid_seed_not_accepted(widget):
    widget.set_context("unknown", 2**63)
    assert "non pris en charge" in widget.compatibility_label.text()
    assert not widget.enabled_check.isEnabled()
    assert not widget.options_widget.isEnabled()
    assert "à définir" in widget.seed_label.text()
    with pytest.raises(ValueError, match="non pris en charge"):
        widget.configuration()


def test_balancing_cannot_remain_enabled_for_types_only(widget):
    widget.set_options(RandomizerOptions(("wild", "types"), balanced=True))
    widget.category_checks["wild"].setChecked(False)
    assert not widget.balanced_check.isEnabled()
    assert widget.options() == RandomizerOptions(("types",), balanced=False)
    widget.balanced_check.setChecked(True)
    assert not widget.balanced_check.isChecked()


def test_no_category_is_rejected_and_explicit_disable_returns_no_operation(widget):
    for check in widget.category_checks.values():
        check.setChecked(False)
    with pytest.raises(ValueError, match="au moins une"):
        widget.configuration()
    widget.enabled_check.setChecked(False)
    assert widget.configuration() is None
    assert not widget.options_widget.isEnabled()


def test_paths_stay_out_of_options_and_verification_is_explicit(widget):
    spy = QSignalSpy(widget.verify_tool_requested)
    changed = QSignalSpy(widget.changed)
    widget.set_tool_paths("C:/local/java.exe", "C:/local/PokeRandoZX.jar")
    assert spy.count() == 0 and changed.count() == 0
    assert widget._tool_state == "unverified"
    assert set(widget.configuration()) == {"kind", "categories", "balanced"}
    widget.verify_button.click()
    assert spy.count() == 1
    assert spy.at(0) == ["C:/local/java.exe", "C:/local/PokeRandoZX.jar"]
    widget.set_tool_status("verified", "Vérifiés")
    widget.java_edit.setText("C:/different/java.exe")
    assert widget._tool_state == "unverified"


def test_file_picker_cancellation_preserves_user_choice(widget, monkeypatch):
    widget.set_tool_paths("java.exe", "tool.jar")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    widget.browse_buttons[0].click()
    assert widget.tool_paths()["java_path"] == "java.exe"
    assert widget._tool_state == "unverified"


def test_checking_prevents_tool_path_changes_and_duplicate_verification(widget):
    widget.set_tool_paths("java.exe", "tool.jar")
    widget.set_tool_status("checking", "Vérification…")
    assert not widget.java_edit.isEnabled()
    assert not widget.jar_edit.isEnabled()
    assert not widget.verify_button.isEnabled()
    assert widget.tool_status_label.textFormat() == Qt.TextFormat.PlainText
    widget.set_tool_status("error", "JAR incompatible")
    assert widget.verify_button.isEnabled()


def test_worker_dialog_cannot_close_while_verification_is_running(qt_app):
    release = Event()
    dialog = RandomizerToolVerificationDialog(lambda: release.wait(timeout=5))
    try:
        dialog.begin()
        dialog.show()
        qt_app.processEvents()
        dialog.reject()
        dialog.close()
        assert dialog.runner.is_busy and dialog.isVisible()
        release.set()
        wait_until(qt_app, lambda: not dialog.runner.is_busy)
        assert dialog.result() == dialog.DialogCode.Accepted
    finally:
        release.set()
        wait_until(qt_app, lambda: not dialog.runner.is_busy)
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()


def test_worker_failure_is_visible_and_does_not_claim_verification(qt_app):
    def fail():
        raise ValueError("JAR non reconnu")
    dialog = RandomizerToolVerificationDialog(fail)
    try:
        dialog.begin()
        wait_until(qt_app, lambda: not dialog.runner.is_busy)
        assert dialog.error == "JAR non reconnu"
        assert dialog.status_label.text() == "JAR non reconnu"
        assert dialog.buttons.isEnabled()
        assert dialog.result() != dialog.DialogCode.Accepted
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()


def test_new_configuration_contains_real_requested_transformation_and_unique_seed(page):
    page.randomizer_widget.set_options(RandomizerOptions(("types", "wild"), balanced=True))
    page.randomizer_widget.set_tool_paths("C:/private/java.exe", "C:/private/tool.jar")
    page.generate()
    assert page.challenge is not None
    assert page.challenge.settings["rom_transformation"] == {
        "kind": "zx", "categories": ["wild", "types"], "balanced": True}
    assert page.challenge.seed == 512
    assert "private" not in str(page.challenge.to_dict())
    assert "aucune transformation encore appliquée" in page.preview.toPlainText()
    assert "Seed de la ROM : 512" in page.preview.toPlainText()


def test_seed_or_options_change_invalidates_preview_without_losing_options(page):
    page.generate()
    page.seed_edit.setText("513")
    assert page.challenge is None and not page.save_button.isEnabled()
    assert "513" in page.randomizer_widget.seed_label.text()
    page.generate()
    assert page.challenge.seed == 513
    page.randomizer_widget.category_checks["types"].setChecked(True)
    assert page.challenge is None
    page.generate()
    assert "types" in page.challenge.settings["rom_transformation"]["categories"]


def test_randomizer_disabled_does_not_leave_transform_in_snapshot(page):
    page.generate()
    page.state_controls["randomizer"].setCurrentIndex(2)
    assert page.randomizer_widget.isHidden()
    page.generate()
    assert "randomizer" not in page.challenge.active_rules
    assert "rom_transformation" not in page.challenge.settings


def test_loading_historical_randomizer_never_enables_transform_implicitly(page, catalog):
    old = ChallengeEngine(catalog).generate("white", "custom", {"randomizer": "required"}, 0, 42)
    expected = deepcopy(old.to_dict())
    page.load_challenge(old)
    assert page.challenge.to_dict() == expected
    assert not page.randomizer_widget.enabled_check.isChecked()
    assert "historique" in page.preview.toPlainText()
    page.seed_edit.setText("43")
    page.generate()
    assert "rom_transformation" not in page.challenge.settings
    page.randomizer_widget.enabled_check.setChecked(True)
    page.generate()
    assert page.challenge.settings["rom_transformation"]["kind"] == "zx"


def test_saved_randomizer_roundtrip_retains_categories_balancing_and_seed(page, qt_app, catalog):
    page.randomizer_widget.set_options(RandomizerOptions(("trainers", "evolutions"), balanced=True))
    page.generate()
    expected = deepcopy(page.challenge.to_dict())
    saved = page.profiles.create("Randomizer", page.challenge)
    other = ChallengePage(catalog, page.profiles)
    try:
        other.load_challenge(page.profiles.load(saved.id).challenge)
        assert other.challenge.to_dict() == expected
        assert other.randomizer_widget.options() == RandomizerOptions(("trainers", "evolutions"), balanced=True)
        other.generate()
        regenerated = other.challenge.to_dict()
        # Generation creates a fresh challenge date; the reproducible settings
        # and seed must remain exactly those loaded from the saved model.
        assert {key: value for key, value in regenerated.items() if key != "created_at"} == {
            key: value for key, value in expected.items() if key != "created_at"}
    finally:
        other.close()
        other.deleteLater()
        qt_app.processEvents()


def test_tool_validation_runs_outside_qt_thread_and_uses_local_store(page, qt_app, monkeypatch):
    calls = []
    def save(store, java, jar):
        calls.append((store.path, java, jar, QThread.currentThread() == qt_app.thread()))
    monkeypatch.setattr(RandomizerToolStore, "save", save)
    page.randomizer_widget.set_tool_paths("java.exe", "PokeRandoZX.jar")
    page.randomizer_widget.verify_button.click()
    assert calls == [(page.profiles.root.parent / "randomizer.local.json", "java.exe", "PokeRandoZX.jar", False)]
    assert page.randomizer_widget._tool_state == "verified"
    assert "ROM encore à vérifier" in page.randomizer_widget.tool_status_label.text()


def test_configuration_editor_without_base_never_guesses_development_directory(qt_app, catalog):
    editor = ChallengePage(catalog, None, configuration_only=True)
    try:
        editor._verify_randomizer_tools("java.exe", "tool.jar")
        assert editor._randomizer_base_dir is None
        assert editor.randomizer_widget._tool_state == "error"
        assert "stockage local" in editor.randomizer_widget.tool_status_label.text()
    finally:
        editor.close()
        editor.deleteLater()
        qt_app.processEvents()
