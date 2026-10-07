"""Secondary template management preserves reusable profiles and legacy data."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.challenge_engine import ChallengeEngine
from app.core.profile_manager import ProfileManager
from app.ui.challenge_page import ChallengePage
from app.ui.profile_page import ProfilePage


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def manager(tmp_path):
    return ProfileManager(tmp_path / "profiles")


@pytest.fixture
def profile(catalog, manager):
    challenge = ChallengeEngine(catalog).generate("white", "normal", {}, 0, 42)
    profile = manager.create("Modèle Blanc", challenge)
    profile.progress["badges"] = ["Badge conservé"]
    manager.save(profile)
    return profile


@pytest.fixture
def page(qt_app, catalog, manager):
    page = ProfilePage(catalog, manager)
    page.show()
    qt_app.processEvents()
    yield page
    page.close()
    page.deleteLater()
    qt_app.processEvents()


def test_empty_manager_offers_return_and_create_without_profile_actions(page):
    back = QSignalSpy(page.back_requested)
    create = QSignalSpy(page.create_requested)
    page.back_button.click()
    page.create_button.click()
    assert back.count() == create.count() == 1
    assert "modèle" in page.summary.text().casefold()
    assert not page.start_run_button.isEnabled()
    assert not page.open_button.isEnabled()
    assert not page.launch_button.isEnabled()
    assert not page.progress_button.isEnabled()


def test_model_actions_keep_existing_configuration_and_progress(page, profile, manager):
    page.refresh(select_profile_id=profile.id)
    expected_challenge = manager.load(profile.id).challenge.to_dict()
    expected_progress = manager.load(profile.id).progress
    started = QSignalSpy(page.start_run_requested)
    opened = QSignalSpy(page.open_requested)
    page.start_run_button.click()
    page.open_button.click()
    assert started.count() == opened.count() == 1
    assert started.at(0)[0].id == opened.at(0)[0].id == profile.id
    assert len(manager.list_profiles()) == 1
    assert manager.load(profile.id).challenge.to_dict() == expected_challenge
    assert manager.load(profile.id).progress == expected_progress
    assert "modèle" in page.open_button.text().casefold()


def test_legacy_progress_and_launch_remain_available_behind_fold(
    page, profile, manager, monkeypatch, qt_app,
):
    page.refresh(select_profile_id=profile.id)
    assert not page.legacy_toggle.isChecked()
    assert page.legacy_card.isHidden()
    assert not page.launch_button.isVisible()
    assert not page.progress_button.isVisible()
    page.legacy_toggle.click()
    qt_app.processEvents()
    assert page.legacy_card.isVisible()
    assert page.launch_button.isVisible()
    assert page.progress_button.isVisible()
    assert page.badges.value() == 1

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    page.badges.setValue(2)
    page.progress_button.click()
    saved = manager.load(profile.id)
    assert saved.progress["badges"] == ["Badge conservé", "Badge 2"]
    assert saved.history[-1]["event"] == "manual_progress_update"
    assert saved.challenge.to_dict() == profile.challenge.to_dict()

    launched = QSignalSpy(page.launch_requested)
    page.launch_button.click()
    assert launched.count() == 1
    assert launched.at(0)[0].to_dict() == profile.challenge.to_dict()
    page.legacy_toggle.click()
    assert page.legacy_card.isHidden()
    assert page.badges.value() == 2


def test_model_editor_creates_distinct_profile_and_can_return(qt_app, catalog, manager, profile):
    editor = ChallengePage(catalog, manager)
    try:
        returned = QSignalSpy(editor.back_requested)
        editor.back_button.click()
        assert returned.count() == 1
        editor.load_challenge(profile.challenge, profile.name)
        saved = QSignalSpy(editor.saved)
        editor.save_button.click()
        assert saved.count() == 1
        copied = saved.at(0)[0]
        assert copied.id != profile.id
        assert copied.challenge.to_dict() == profile.challenge.to_dict()
        assert manager.load(profile.id).progress["badges"] == ["Badge conservé"]
        assert "modèle" in editor.save_button.text().casefold()
        assert "modèle" in editor.feedback.text().casefold()
    finally:
        editor.close()
        editor.deleteLater()
        qt_app.processEvents()


def test_model_editor_legacy_launch_requires_expanding_its_section(qt_app, catalog, manager):
    editor = ChallengePage(catalog, manager)
    try:
        editor.show()
        editor.seed_edit.setText("42")
        editor.generate_button.click()
        assert editor.challenge is not None
        assert not editor.launch_button.isVisible()
        editor.legacy_toggle.click()
        assert editor.launch_button.isVisible()
        launched = QSignalSpy(editor.launch_requested)
        editor.launch_button.click()
        assert launched.count() == 1
        assert launched.at(0)[0] is editor.challenge
        assert manager.list_profiles() == []
    finally:
        editor.close()
        editor.deleteLater()
        qt_app.processEvents()


def test_custom_run_editor_has_no_model_navigation_or_legacy_launch(qt_app, catalog):
    editor = ChallengePage(catalog, None, configuration_only=True)
    try:
        assert editor.back_button.isHidden()
        assert editor.legacy_toggle.isHidden()
        assert editor.launch_button.isHidden()
        assert editor.save_button.isHidden()
        editor.seed_edit.setText("42")
        editor.generate_button.click()
        assert editor.challenge is not None
        assert "création de votre partie" in editor.feedback.text()
        saved = QSignalSpy(editor.saved)
        launched = QSignalSpy(editor.launch_requested)
        editor.save_profile()
        editor.request_launch()
        assert saved.count() == launched.count() == 0
    finally:
        editor.close()
        editor.deleteLater()
        qt_app.processEvents()
