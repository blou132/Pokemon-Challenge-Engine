"""Interface de bibliothèque avec service injecté, sans découverte personnelle."""

import os
from pathlib import Path
from threading import Event
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from app.services.config_service import AppConfig, ConfigService
from app.ui.rom_library_panel import RomLibraryPanel
from app.ui.settings_page import SettingsPage


class FakeLibrary:
    def __init__(self, root: Path):
        self.root = root
        self.entries = ()
        self.results = ()
        self.calls = []
        self.verify_started = Event()
        self.verify_release = Event()
        self.verify_release.set()
        self.import_error = None
        self.import_results = ()

    def list_entries(self):
        self.calls.append(("list", QThread.currentThread()))
        return self.entries

    def master_path(self, entry):
        return self.root / f"{entry.game_id}.nds"

    def verify(self):
        self.calls.append(("verify", QThread.currentThread()))
        self.verify_started.set()
        if not self.verify_release.wait(5):
            raise TimeoutError("Test worker did not receive release")
        return self.results

    def import_directory(self, folder):
        self.calls.append(("import", QThread.currentThread(), folder))
        if self.import_error:
            raise ValueError(self.import_error)
        return self.import_results


def wait_idle(application, panel):
    for _ in range(500):
        application.processEvents()
        if not panel.is_busy:
            return
        QTest.qWait(10)
    pytest.fail("Library worker did not finish")


@pytest.fixture
def library_ui(tmp_path, catalog):
    application = QApplication.instance() or QApplication([])
    service = FakeLibrary(tmp_path)
    page = SettingsPage(ConfigService(tmp_path / "config.json"), AppConfig(),
                        catalog.games.values(), library_service=service)
    wait_idle(application, page.library_panel)
    yield application, page, service
    service.verify_release.set()
    assert page.shutdown_library()
    application.processEvents()
    page.close()
    page.deleteLater()
    application.processEvents()


def add_entry(service, game_id="white", *, present=True, valid=True, error=None):
    codes = {"diamond": "ADAF", "pearl": "APAF", "white": "IRAF", "black": "IRBF"}
    entry = SimpleNamespace(game_id=game_id, sha256="a" * 64, game_code=codes.get(game_id, "IRAF"),
                            region="FR", revision=5 if game_id in {"diamond", "pearl"} else 0,
                            generation=4 if game_id in {"diamond", "pearl"} else 5)
    service.entries += (entry,)
    if present:
        service.master_path(entry).write_bytes(b"synthetic UI fixture")
    service.results += (SimpleNamespace(entry=entry, valid=valid, error=error),)
    return entry


def test_nine_games_have_separate_presence_modes_and_run_counts(library_ui):
    application, page, service = library_ui
    panel = page.library_panel
    add_entry(service)
    add_entry(service, "diamond")
    panel.set_context(melonds_available=True, run_counts={"white": 3, "diamond": 2})
    panel.refresh(verify=True)
    wait_idle(application, panel)
    assert len(panel.rows) == 9
    assert "Génération 4" in panel.rows["diamond"]["name"].text()
    assert "classique" in panel.rows["diamond"]["modes"].text()
    assert "non disponibles" in panel.rows["diamond"]["modes"].text()
    assert "Blanc FR0" in panel.rows["white"]["modes"].text()
    assert "original uniquement" in panel.rows["black"]["modes"].text()
    assert "Présente" in panel.rows["white"]["source"].text()
    assert "Absente" in panel.rows["pearl"]["source"].text()
    assert "conforme" in panel.rows["white"]["integrity"].text()
    assert "Disponible" in panel.rows["white"]["emulator"].text()
    assert panel.rows["white"]["runs"].text().endswith("3")
    assert panel.rows["diamond"]["runs"].text().endswith("2")
    assert all(call[1] != application.thread() for call in service.calls)


def test_verification_runs_outside_gui_and_blocks_overlapping_import(library_ui):
    application, page, service = library_ui
    panel = page.library_panel
    add_entry(service)
    service.verify_release.clear()
    page.library_panel.verify_button.click()
    assert service.verify_started.wait(2)
    timer_fired = []
    QTimer.singleShot(0, lambda: timer_fired.append(True))
    application.processEvents()
    assert timer_fired
    assert panel.is_busy
    assert not panel.verify_button.isEnabled()
    assert not panel.import_button.isEnabled()
    assert not panel.import_directory(service.root)
    service.verify_release.set()
    wait_idle(application, panel)
    assert panel.verify_button.isEnabled()
    assert not any(call[0] == "import" for call in service.calls)


def test_failed_integrity_remains_visible_and_emits_update(library_ui):
    application, page, service = library_ui
    entry = add_entry(service, valid=False, error="Empreinte modifiée : génération refusée")
    original = service.master_path(entry).read_bytes()
    changes = []
    page.library_changed.connect(lambda: changes.append(True))
    page.library_panel.verify_button.click()
    wait_idle(application, page.library_panel)
    assert "1 erreur" in page.library_panel.status_label.text()
    assert "génération refusée" in page.library_panel.rows["white"]["integrity"].text()
    assert changes == [True]
    assert service.master_path(entry).read_bytes() == original


def test_local_import_reports_existing_copies_and_refreshes(library_ui, monkeypatch):
    application, page, service = library_ui
    entry = add_entry(service)
    service.import_results = (SimpleNamespace(entry=entry, imported=False),)
    monkeypatch.setattr("app.ui.rom_library_panel.QFileDialog.getExistingDirectory",
                        lambda *args: str(service.root))
    page.library_panel.import_button.click()
    wait_idle(application, page.library_panel)
    assert "0 copie(s) ajoutée(s), 1 déjà présente(s)" in page.library_panel.status_label.text()
    assert "conforme" in page.library_panel.rows["white"]["integrity"].text()
    assert any(call[0] == "import" and call[2] == service.root for call in service.calls)


def test_partial_import_error_rereads_published_entries(library_ui):
    application, page, service = library_ui
    add_entry(service)
    service.import_error = "Deux ROM différentes pour le même jeu ; aucun remplacement"
    changes = []
    page.library_changed.connect(lambda: changes.append(True))
    page.library_panel.import_directory(service.root)
    wait_idle(application, page.library_panel)
    assert "aucun remplacement" in page.library_panel.status_label.text()
    assert "Présente" in page.library_panel.rows["white"]["source"].text()
    assert "À vérifier" in page.library_panel.rows["white"]["integrity"].text()
    assert changes == [True]


def test_busy_shutdown_waits_without_killing_worker(library_ui):
    application, page, service = library_ui
    service.verify_release.clear()
    page.library_panel.verify_button.click()
    assert service.verify_started.wait(2)
    assert not page.shutdown_library(timeout_ms=0)
    assert page.library_panel.is_busy
    assert "se termine" in page.library_panel.status_label.text()
    service.verify_release.set()
    wait_idle(application, page.library_panel)
    assert page.shutdown_library(timeout_ms=100)


def test_refresh_after_external_import_is_deferred_during_work(library_ui):
    application, page, service = library_ui
    service.verify_release.clear()
    page.library_panel.verify_button.click()
    assert service.verify_started.wait(2)
    assert not page.library_panel.refresh()
    add_entry(service, "pearl")
    service.verify_release.set()
    wait_idle(application, page.library_panel)
    assert "Présente" in page.library_panel.rows["pearl"]["source"].text()
    assert [call[0] for call in service.calls].count("list") >= 3


def test_library_installation_report_has_no_legacy_dependency(library_ui):
    _, page, _ = library_ui
    page.set_detection_state({"library": True, "ready": True,
                              "game_states": {}, "games": [{"game_id": "white"}],
                              "emulators": [{"kind": "melonds"}]})
    assert "Prête" in page.installation_state.text()
    labels = [label.text() for label in page.installation_summary.values()]
    assert any("melonDS · Disponible" == label for label in labels)
    assert any("1 / 9" in label for label in labels)
    assert all("RetroBat" not in label and "Lua" not in label for label in labels)


def test_external_verification_is_bound_to_displayed_master_hash(library_ui):
    application, page, service = library_ui
    panel = page.library_panel
    entry = add_entry(service)
    panel.apply_verification({"white": {"sha256": entry.sha256, "valid": True, "error": None}})
    panel.refresh()
    wait_idle(application, panel)
    assert "conforme" in panel.rows["white"]["integrity"].text()
    # Un résultat antérieur ne valide pas une autre identité de copie maîtresse.
    entry.sha256 = "b" * 64
    panel.refresh()
    wait_idle(application, panel)
    assert "À vérifier" in panel.rows["white"]["integrity"].text()
    panel.apply_verification({"white": {"sha256": entry.sha256, "valid": False, "error": "Copie altérée"}})
    assert "Copie altérée" in panel.rows["white"]["integrity"].text()
    assert not any(call[0] == "verify" for call in service.calls)


def test_library_cards_fit_settings_scroll(library_ui):
    application, page, _ = library_ui
    page.resize(1110, 680)
    page.show()
    application.processEvents()
    scroll = page.findChild(QScrollArea)
    assert scroll.horizontalScrollBar().maximum() == 0
    scroll.ensureWidgetVisible(page.library_panel.rows["white2"]["runs"])
    application.processEvents()
    label = page.library_panel.rows["white2"]["runs"]
    assert scroll.viewport().rect().contains(label.mapTo(scroll.viewport(), label.rect().center()))


def test_no_injected_library_does_not_discover_or_create_data(tmp_path, catalog):
    application = QApplication.instance() or QApplication([])
    panel = RomLibraryPanel(catalog.games.values())
    try:
        assert len(panel.rows) == 9
        assert not panel.verify_button.isEnabled()
        assert not panel.import_button.isEnabled()
        assert not panel.is_busy
        assert not list(tmp_path.iterdir())
    finally:
        panel.close()
        panel.deleteLater()
        application.processEvents()


def test_main_window_applies_library_report_and_real_run_counts(tmp_path, catalog):
    from app.ui.main_window import MainWindow

    application = QApplication.instance() or QApplication([])
    service = FakeLibrary(tmp_path)
    entry = add_entry(service)
    window = MainWindow(catalog, tmp_path / "data", library_service=service)
    panel = window.settings_page.library_panel
    try:
        wait_idle(application, panel)
        window.runs.create("Première aventure", "white")
        window.runs.create("Deuxième aventure", "white")
        window._discovery_completed({
            "library": True, "ready": True, "game_states": {"white": {"status": "ready"}},
            "games": [{"game_id": "white"}], "emulators": [{"emulator_kind": "melonds"}],
            "library_integrity": {"white": {"sha256": entry.sha256, "valid": True, "error": None}},
        })
        wait_idle(application, panel)
        assert panel.rows["white"]["runs"].text().endswith("2")
        assert panel.rows["diamond"]["runs"].text().endswith("0")
        assert "conforme" in panel.rows["white"]["integrity"].text()
        assert "Disponible" in panel.rows["white"]["emulator"].text()
        assert len(panel.rows) == 9
        window.open_installation()
        wait_idle(application, panel)
        assert window.pages.currentWidget() is window.settings_page
        assert window.installation_dialog is None
        assert not any(call[0] in {"verify", "import"} for call in service.calls)
    finally:
        wait_idle(application, panel)
        window.close()
        window.deleteLater()
        application.processEvents()


@pytest.mark.parametrize("game_id", ["white", "diamond"])
def test_new_adventure_uses_library_profile_and_identified_revision(tmp_path, catalog, monkeypatch, game_id):
    from PySide6.QtWidgets import QDialog
    from app.services.game_mode_config import GameModeConfigStore
    from app.ui.main_window import MainWindow
    from app.ui.run_dialogs import NewRunDialog

    application = QApplication.instance() or QApplication([])
    service = FakeLibrary(tmp_path)
    entry = add_entry(service, game_id)
    executable = tmp_path / "fixture-melonds.exe"
    monkeypatch.setattr("app.services.melonds_runtime.find_installation", lambda *args: executable)
    window = MainWindow(catalog, tmp_path / "data", library_service=service)
    panel = window.settings_page.library_panel
    resumed = []
    monkeypatch.setattr(window, "resume_run", resumed.append)
    monkeypatch.setattr(NewRunDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    # Creation records a frozen reference; actual copying/launch belongs to the
    # preparation service tests, so this test never executes an emulator.
    window._setup_service = SimpleNamespace(library=service)
    profiles = GameModeConfigStore(window.base_dir, window.config).load()["launch_profiles"]
    profiles[game_id].update(rom_path=str(service.master_path(entry)), emulator_kind="melonds",
                              emulator_path=str(executable), save_path="")
    try:
        wait_idle(application, panel)
        window._discovery_completed({
            "library": True, "ready": True,
            "game_states": {game_id: {"status": "ready", "candidate_id": entry.sha256}},
            "games": [{"game_id": game_id}], "emulators": [{"emulator_kind": "melonds"}],
            "launch_profiles": profiles,
            "library_integrity": {game_id: {"sha256": entry.sha256, "valid": True, "error": None}},
        })
        wait_idle(application, panel)
        run = window.new_run(game_id=game_id)
        assert run is not None
        assert resumed == [run.run_id]
        recorded = window.runs.load(run.run_id)
        assert recorded.launch_profile["rom_path"] == str(service.master_path(entry))
        assert recorded.launch_profile["emulator_kind"] == "melonds"
        assert recorded.launch_profile["_isolation_pending"] is True
        assert recorded.launch_profile["_library_source"]["sha256"] == entry.sha256
        assert recorded.game_code == entry.game_code
        assert recorded.revision == entry.revision
        assert recorded.save_path is None
        assert recorded.rules_snapshot["active_rules"] == []
    finally:
        wait_idle(application, panel)
        window.close()
        window.deleteLater()
        application.processEvents()
