"""Parcours Qt synthétiques de l'installation automatique, sans fichier utilisateur."""

from copy import deepcopy
import os
from time import monotonic, sleep

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.config_service import AppConfig, ConfigService
from app.ui.settings_page import SettingsPage
from app.ui.setup_dialog import InstallationDialog


def report():
    emulator = "C:/fixture/RetroBat/emulators/desmume/DeSmuME.exe"
    save = "C:/fixture/RetroBat/saves/Blanc.dsv"
    return {
        "installations": [{"root": "C:/fixture/RetroBat"}],
        "emulators": [{"path": emulator, "version": "test", "architecture": "x64",
                       "lua_status": "verified", "ini_path": "C:/fixture/desmume.ini", "dlls": []}],
        "games": [{"id": "white-local", "game_id": "white", "label": "Pokémon Blanc · FR · rev0",
                   "source_path": "C:/fixture/RetroBat/roms/nds/Blanc.zip", "source_kind": "zip",
                   "archive_member": "Blanc.nds", "requires_choice": False, "supported": True,
                   "proposed_save": save, "saves": [{"path": save, "confidence": "high"}]}],
        "game_states": {
            "white": {"status": "ready", "candidate_id": "white-local", "emulator_path": emulator,
                      "save_path": save, "health": {"ready": True}},
            **{game: {"status": "not_found", "message": "Jeu non trouvé"}
               for game in ("black", "black2", "white2")}},
        "ready": True, "prepared_games": ["white"], "warnings": [],
    }


class AutomaticSetup:
    def __init__(self):
        self.report = report()
        self.calls = []

    def automatic_setup(self, force=False, game_id=None):
        self.calls.append(("automatic", force, game_id))
        return deepcopy(self.report)

    def scan(self, **options):
        self.calls.append(("scan", options))
        result = deepcopy(self.report)
        result.pop("game_states", None)
        return result

    def prepare(self, selection):
        self.calls.append(("prepare", selection))
        candidate = next(item for item in self.report["games"] if item["id"] == selection["candidate_id"])
        game = candidate["game_id"]
        self.report["game_states"][game] = {
            "status": "ready", "candidate_id": candidate["id"], "emulator_path": selection["emulator_path"],
            "save_path": selection["save_path"], "health": {"ready": True}}
        return {"game_id": game, "health": {"ready": True, "lua_status": {"status": "verified"}}}

    def repair(self, selection, replace_confirmed=False):
        self.calls.append(("repair", replace_confirmed))
        for emulator in self.report["emulators"]:
            if emulator["path"] == selection["emulator_path"]:
                emulator["lua_status"] = "verified"
        return self.prepare(selection)


def until(app, predicate):
    limit = monotonic() + 5
    while not predicate() and monotonic() < limit:
        app.processEvents()
        QTest.qWait(5)
        sleep(0.001)
    assert predicate()


@pytest.fixture
def installation():
    app = QApplication.instance() or QApplication([])
    service = AutomaticSetup()
    dialog = InstallationDialog(service)
    yield app, dialog, service
    until(app, lambda: not dialog.is_busy)
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_unique_game_emulator_and_save_are_ready_without_manual_action(installation):
    app, dialog, service = installation
    emitted = QSignalSpy(dialog.detection_completed)
    dialog.start()
    until(app, lambda: not dialog.is_busy)
    assert service.calls == [("automatic", False, None)]
    assert emitted.count() == 1
    assert dialog.play_button.isEnabled()
    assert dialog.summary["save"].text() == "Blanc.dsv"
    assert dialog.summary["game"].text() == "Prêt"
    assert dialog.summary["lua"].text().startswith("Prêt")
    assert dialog.game_states["white"].text() == "Pokémon Blanc · Prêt"
    assert "Jeu non trouvé" in dialog.game_states["black"].text()
    assert dialog.manual_controls.isHidden() and dialog.prepare_button.isHidden()
    assert all(combo.isHidden() for combo in (dialog.installation_combo, dialog.emulator_combo,
                                              dialog.game_combo, dialog.save_combo))
    assert dialog.repair_button.isHidden()


def test_shared_report_does_not_restart_worker_or_emit_detection(installation):
    _, dialog, service = installation
    emitted = QSignalSpy(dialog.detection_completed)
    dialog.set_detection_state(service.report)
    dialog.start()
    assert not service.calls
    assert emitted.count() == 0
    assert dialog.play_button.isEnabled()


def test_missing_games_are_states_without_error_popup(installation, monkeypatch):
    app, dialog, service = installation
    service.report["games"] = []
    service.report["game_states"] = {game: {"status": "not_found"} for game in dialog.game_states}
    service.report["ready"] = False
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: pytest.fail("Pas de popup pour les jeux absents"))
    dialog.start()
    until(app, lambda: not dialog.is_busy)
    assert not dialog.play_button.isEnabled()
    assert all("Jeu non trouvé" in widget.text() and "bibliothèque RetroBat" in widget.text()
               for widget in dialog.game_states.values())


def test_multiple_emulators_only_require_resolving_the_choice(installation):
    app, dialog, service = installation
    second = dict(service.report["emulators"][0], path="D:/fixture/DeSmuME.exe")
    service.report["emulators"].append(second)
    service.report["game_states"]["white"] = {"status": "needs_choice", "candidate_id": "white-local",
        "message": "Plusieurs installations DeSmuME", "emulator_path": "", "save_path": ""}
    dialog.start()
    until(app, lambda: not dialog.is_busy)
    assert not dialog.emulator_combo.isHidden()
    assert dialog.emulator_combo.currentData() is None
    assert not dialog.play_button.isEnabled()
    dialog.emulator_combo.setCurrentIndex(dialog.emulator_combo.findData(second["path"]))
    until(app, lambda: not dialog.is_busy)
    assert dialog.play_button.isEnabled()
    prepared = next(call[1] for call in service.calls if call[0] == "prepare")
    assert prepared["emulator_path"] == second["path"]


def test_multiple_saves_do_not_silently_select_none(installation):
    app, dialog, service = installation
    game = service.report["games"][0]
    game["saves"].append({"path": "C:/fixture/Blanc-old.dsv", "confidence": "high"})
    game["proposed_save"] = ""
    service.report["game_states"]["white"] = {"status": "needs_choice", "candidate_id": game["id"],
        "emulator_path": service.report["emulators"][0]["path"], "save_path": "",
        "message": "Plusieurs sauvegardes trouvées"}
    dialog.start()
    until(app, lambda: not dialog.is_busy)
    assert not dialog.save_combo.isHidden()
    assert dialog.save_combo.currentData() is None
    assert not any(call[0] == "prepare" for call in service.calls)
    chosen = game["saves"][1]["path"]
    dialog.save_combo.setCurrentIndex(dialog.save_combo.findData(chosen))
    until(app, lambda: not dialog.is_busy)
    assert dialog.play_button.isEnabled()
    assert next(call[1] for call in service.calls if call[0] == "prepare")["save_path"] == chosen


def test_single_multi_member_archive_keeps_visible_choice(installation):
    app, dialog, service = installation
    service.report["games"][0]["requires_choice"] = True
    service.report["game_states"]["white"] = {"status": "needs_choice", "candidate_id": ""}
    dialog.start()
    until(app, lambda: not dialog.is_busy)
    assert dialog.game_combo.currentData() is None
    assert not dialog.game_combo.isHidden()
    assert not dialog.play_button.isEnabled()


def test_explicit_no_save_choice_is_retained_after_refresh(installation):
    app, dialog, service = installation
    service.report["game_states"]["white"]["save_path"] = ""
    dialog.start()
    until(app, lambda: not dialog.is_busy)
    assert dialog.save_combo.currentData() == ""
    assert dialog.play_button.isEnabled()
    assert dialog.summary["save"].text() == "Aucune sauvegarde associée"


def test_each_ready_game_uses_its_own_emulator_and_save(installation):
    app, dialog, service = installation
    second_emulator = dict(service.report["emulators"][0], path="D:/fixture/DeSmuME.exe")
    service.report["emulators"].append(second_emulator)
    second_game = dict(service.report["games"][0], id="black2-local", game_id="black2", label="Pokémon Noir 2",
                       source_path="D:/fixture/Noir2.nds", source_kind="nds", saves=[], proposed_save="")
    service.report["games"].append(second_game)
    service.report["game_states"]["black2"] = {"status": "ready", "candidate_id": second_game["id"],
        "emulator_path": second_emulator["path"], "save_path": "", "health": {"ready": True}}
    dialog.start()
    until(app, lambda: not dialog.is_busy)
    dialog.game_combo.setCurrentIndex(dialog.game_combo.findData(second_game["id"]))
    assert dialog.play_button.isEnabled()
    assert dialog._last_ready_game == "black2"
    assert dialog.emulator_combo.currentData() == second_emulator["path"]
    assert dialog.save_combo.currentData() == ""
    dialog.game_combo.setCurrentIndex(dialog.game_combo.findData("white-local"))
    assert dialog.play_button.isEnabled()
    assert dialog._last_ready_game == "white"
    assert dialog.emulator_combo.currentData() == service.report["emulators"][0]["path"]
    assert dialog.save_combo.currentData() == service.report["games"][0]["proposed_save"]
    assert not any(call[0] == "prepare" for call in service.calls)


def test_no_existing_save_is_not_a_missing_configuration(installation):
    app, dialog, service = installation
    service.report["games"][0].update(saves=[], proposed_save="")
    service.report["game_states"]["white"]["save_path"] = ""
    dialog.start()
    until(app, lambda: not dialog.is_busy)
    assert dialog.play_button.isEnabled()
    assert dialog.summary["save"].text() == "Aucune sauvegarde existante trouvée"
    assert dialog.save_combo.isHidden()


def test_manual_rom_choice_prepares_that_source_without_extra_button(installation, monkeypatch):
    app, dialog, service = installation
    dialog.set_detection_state(service.report)
    second = deepcopy(service.report["games"][0])
    second.update(id="white-manual", source_path="D:/fixture/Blanc.nds", source_kind="nds", archive_member="")
    service.report["games"].append(second)
    monkeypatch.setattr("app.ui.setup_dialog.QFileDialog.getOpenFileName", lambda *args: (second["source_path"], ""))
    dialog._choose_rom()
    until(app, lambda: not dialog.is_busy)
    assert next(call[1] for call in service.calls if call[0] == "prepare")["candidate_id"] == second["id"]
    assert dialog.play_button.isEnabled()


def test_manual_folder_search_prepares_unique_candidate_automatically(installation, monkeypatch):
    app, dialog, service = installation
    root = service.report["installations"][0]["root"]
    monkeypatch.setattr("app.ui.setup_dialog.QFileDialog.getExistingDirectory", lambda *args: root)
    dialog._choose_folder()
    until(app, lambda: not dialog.is_busy)
    assert service.calls[0] == ("scan", {"retrobat_path": root, "emulator_path": "", "rom_path": ""})
    assert next(call[1] for call in service.calls if call[0] == "prepare")["retrobat_root"] == root
    assert dialog.play_button.isEnabled()


def test_lua_installation_still_requires_explicit_consent(installation, monkeypatch):
    app, dialog, service = installation
    service.report["emulators"][0]["lua_status"] = "missing"
    service.report["game_states"]["white"].update(status="lua_required", health={"ready": False})
    dialog.start()
    until(app, lambda: not dialog.is_busy)
    assert not dialog.repair_button.isHidden()
    assert dialog.summary["lua"].text() == "Support Lua requis"
    assert not any(call[0] == "repair" for call in service.calls)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    dialog.repair_button.click()
    assert not any(call[0] == "repair" for call in service.calls)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog.repair_button.click()
    until(app, lambda: not dialog.is_busy)
    assert dialog.play_button.isEnabled()
    assert dialog.repair_button.isHidden()


def test_settings_summary_is_primary_and_keeps_manual_drafts(catalog, tmp_path):
    app = QApplication.instance() or QApplication([])
    page = SettingsPage(ConfigService(tmp_path / "config.json"), AppConfig(), catalog.games.values())
    try:
        page.show()
        page.rom_edits["white"].setText("D:/manual/Blanc.nds")
        page.set_detection_state(report())
        app.processEvents()
        assert page.installation_state.text() == "Installation PCE · Prête"
        assert page.installation_summary["games"].text() == "Jeux · 1 / 4 trouvés"
        assert page.rom_edits["white"].text() == "D:/manual/Blanc.nds"
        unbound = report()
        unbound["game_states"]["white"]["save_path"] = ""
        page.set_detection_state(unbound)
        assert "Fichiers détectés" in page.installation_summary["saves"].text()
        assert "Aucune sauvegarde associée" in page.installation_summary["saves"].text()
        assert not page.test_button.isVisible() and not page.save_button.isVisible()
        assert not page.desmume_edit.isVisible()
        requested = QSignalSpy(page.detection_requested)
        page.advanced_toggle.click()
        assert page.test_button.isVisible() and page.save_button.isVisible()
        assert page.desmume_edit.isVisible()
        page.detection_button.click()
        assert requested.count() == 1
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
