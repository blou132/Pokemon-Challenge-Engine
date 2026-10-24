"""Synthetic Qt run/profile contexts; no game or successful autosave is claimed."""

import pytest
from PySide6.QtWidgets import QLabel

from app.bridge.state import BridgeState
from app.core.profile_manager import ProfileManager
from app.core.run_manager import RunManager
from app.models.challenge import Challenge
from app.services.config_service import AppConfig
from app.ui.main_window import MainWindow
from test_bridge_ui import connection, qt_app, until


def make_profile(tmp_path):
    return ProfileManager(tmp_path / "profiles").create("Modèle conservé", Challenge(
        "white", "normal", [], {}, {"enforcement": "soft", "rule_parameters": {}}, None, 42))


def make_run(tmp_path, kind="desmume", name="Aventure A", profile=None):
    return RunManager(tmp_path / "runs").create(name, "white", profile_id=profile.id if profile else None,
        challenge=profile.challenge if profile else None, launch_profile={"emulator_kind": kind})


def visible_labels(page):
    return [widget.text() for widget in page.findChildren(QLabel) if widget.isVisibleTo(page)]


@pytest.mark.parametrize("kind", ["desmume", "melonds"])
def test_main_window_connection_does_not_call_an_active_run_diagnostic(qt_app, catalog, tmp_path, kind):
    window = MainWindow(catalog, tmp_path)
    try:
        run = make_run(tmp_path, kind)
        window._set_bridge_run(run)
        texts = visible_labels(window.bridge_page)
        assert not any("diagnostic uniquement" in text or "aucune progression" in text for text in texts)
        assert any(run.name in text for text in texts)
    finally:
        window.close()
        qt_app.processEvents()


@pytest.mark.parametrize("kind", ["desmume", "melonds"])
@pytest.mark.parametrize("from_profile", [False, True])
def test_run_context_is_independent_of_legacy_profile(connection, tmp_path, monkeypatch, kind, from_profile):
    app, page, controller, _, _ = connection
    profile = make_profile(tmp_path)
    page.set_profiles([profile])
    run = make_run(tmp_path, kind, profile=profile if from_profile else None)
    before = RunManager(tmp_path / "runs").load(run.run_id).to_dict()
    selections = []
    monkeypatch.setattr(controller, "select_profile", selections.append)
    page.set_persistent_run(run)
    page.set_emulator_kind(kind)
    page.update_state(BridgeState(status="waiting", game_id="white"))
    page.show()
    app.processEvents()
    assert page.run_label.text() == "Partie sélectionnée : " + run.name
    assert not page.run_label.isHidden() and not page.run_help.isHidden()
    assert page.profile_combo.isHidden() and page.profile_title.isHidden() and page.profile_help.isHidden()
    assert page.tracking_panel.isHidden()
    assert "état de sauvegarde" in page.run_help.text()
    assert not any("aucune progression" in text or "diagnostic uniquement" in text for text in visible_labels(page))
    assert selections == []
    assert controller.tracking_state.profile_id is None
    assert RunManager(tmp_path / "runs").load(run.run_id).to_dict() == before


def test_same_game_run_switch_and_rename_refresh_name_without_profile_selection(connection, tmp_path, monkeypatch):
    _, page, controller, _, _ = connection
    one = make_run(tmp_path, "melonds")
    two = make_run(tmp_path, "melonds", "Aventure B")
    selections = []
    monkeypatch.setattr(controller, "select_profile", selections.append)
    page.set_persistent_run(one)
    page.set_emulator_kind("melonds")
    page.set_persistent_run(two)
    page.set_emulator_kind("melonds")
    assert page.run_label.text().endswith("Aventure B")
    two.name = "Nouveau nom"
    page.set_persistent_run(two)
    assert page.run_label.text().endswith("Nouveau nom")
    assert page.persistent_game == "white" and not page.game_combo.isEnabled()
    assert selections == []


def test_profile_refresh_keeps_run_context_and_detach_restores_legacy_choices(connection, tmp_path, monkeypatch):
    _, page, controller, _, _ = connection
    profile = make_profile(tmp_path)
    page.set_profiles([profile])
    selections = []
    monkeypatch.setattr(controller, "select_profile", selections.append)
    page.profile_combo.setCurrentIndex(page.profile_combo.findData(profile.id))
    assert selections == [profile.id]
    selections.clear()
    run = make_run(tmp_path, profile=profile)
    page.set_persistent_run(run)
    page.set_profiles([])
    page.set_profiles([profile])
    assert selections == []
    assert page.run_label.text().endswith(run.name)
    assert page.tracking_panel.isHidden() and page.profile_combo.isHidden()
    page.set_persistent_run(None)
    assert page.run_label.isHidden() and page.run_help.isHidden()
    assert not page.profile_combo.isHidden() and not page.profile_help.isHidden()
    assert not page.profile_title.isHidden() and not page.tracking_panel.isHidden()
    assert page.persistent_game is None
    assert page.profile_combo.isEnabled() and page.game_combo.isEnabled()
    assert "aucune progression" in page.profile_help.text()
    assert page.profile_combo.itemText(0) == "Aucun profil — diagnostic uniquement"
    page.profile_combo.setCurrentIndex(page.profile_combo.findData(profile.id))
    assert selections == [profile.id]


@pytest.mark.parametrize("kind", ["desmume", "melonds"])
@pytest.mark.parametrize("detach_selected", [True, False])
def test_detaching_restored_selection_updates_only_its_connection_context(
        qt_app, catalog, tmp_path, kind, detach_selected):
    selected = make_run(tmp_path, kind, "Sélection restaurée")
    other = make_run(tmp_path, kind, "Autre aventure")
    RunManager(tmp_path / "runs").set_active_id(selected.run_id)
    window = MainWindow(catalog, tmp_path)
    try:
        until(qt_app, lambda: window.run_controller.active_run is not None
              and not window.run_controller.activation_pending)
        assert window.run_controller.active_run.run_id == selected.run_id
        assert window.game_mode_window is None
        page = window.bridge_page
        assert page.run_label.text().endswith(selected.name)
        assert page.persistent_game == selected.game_id
        assert page.emulator_kind == kind
        owned_config = AppConfig(desmume_path="owned-emulator.exe")
        page.set_config(owned_config)
        window._detach_run(selected.run_id if detach_selected else other.run_id)
        qt_app.processEvents()
        if detach_selected:
            assert window.run_controller.active_run is None
            assert window.runs.active_id is None
            assert page.run_label.isHidden() and page.run_help.isHidden()
            assert page.run_label.text() == ""
            assert page.persistent_game is None
            assert not page.profile_combo.isHidden() and not page.profile_help.isHidden()
            assert not page.profile_title.isHidden() and not page.tracking_panel.isHidden()
            assert page.game_combo.isEnabled() and page.profile_combo.isEnabled()
            assert page.emulator_kind == "desmume"
            assert page.title_label.text() == "Connexion DeSmuME"
            assert "DeSmuME" in window.nav_buttons[5].text()
            assert page.prepare_button.text() == "Préparer la connexion"
            assert page.config is window.config
        else:
            assert window.run_controller.active_run.run_id == selected.run_id
            assert window.runs.active_id == selected.run_id
            assert not page.run_label.isHidden() and page.run_label.text().endswith(selected.name)
            assert page.persistent_game == selected.game_id
            assert page.profile_combo.isHidden() and page.tracking_panel.isHidden()
            assert not page.game_combo.isEnabled() and not page.profile_combo.isEnabled()
            assert page.emulator_kind == kind
            assert page.config is owned_config
        assert window.game_mode_window is None
    finally:
        window.close()
        qt_app.processEvents()
