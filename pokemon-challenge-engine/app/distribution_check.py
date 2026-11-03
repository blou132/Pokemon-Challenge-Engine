"""Opt-in packaged UI/persistence check; never an emulation or gameplay claim."""

import json
import logging
from pathlib import Path
import sys
import time

from PySide6.QtCore import QThread

from app import __version__
from app.core.run_manager import RunManager
from app.core.gen5_species import species_types
from app.services.config_service import ConfigService


def wait_for_run_card_layout(application, page, run_id: str, *, timeout: float = 2.0) -> dict:
    """Wait for both card layout and its scroll area's deferred layout request."""
    deadline = time.monotonic() + timeout
    while True:
        application.processEvents()
        widget = next((item for item in page.cards if item.run_id == run_id), None)
        geometry = {}
        if widget is not None and widget.isVisible():
            for name, child in (("card", widget), ("name", widget.name_label),
                                ("stats", widget.stats_label), ("rules", widget.rules_label),
                                ("resume", widget.resume_button)):
                required = child.heightForWidth(child.width()) if child.hasHeightForWidth() else child.sizeHint().height()
                geometry[name] = {"height": child.height(), "required_height": required, "width": child.width()}
            if all(item["width"] > 0 and item["height"] >= item["required_height"] for item in geometry.values()):
                return geometry
        if time.monotonic() >= deadline:
            raise AssertionError(f"The adventure card did not reach readable dimensions: {geometry}")
        QThread.msleep(10)


def run_check(application, window, paths, report_path: Path) -> None:
    report = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False)), "ok": False,
              "resources": str(paths.resources), "data": str(paths.data), "portable": paths.portable,
              "scope": "Qt UI and synthetic persistence; no game or emulator launched"}
    try:
        marker = paths.data / ".distribution-check.json"
        runs = window.runs.list_runs()
        if runs and not marker.exists():
            raise ValueError("Le test de distribution exige un dossier neuf ou déjà réservé à ce test.")
        if marker.exists():
            identifier = json.loads(marker.read_text(encoding="utf-8"))["run_id"]
            run = window.runs.load(identifier)
            if run.name != "Validation distribution" or run.badges != 3:
                raise ValueError("La progression synthétique n'a pas été conservée.")
            report["reopened"] = True
        else:
            if any(paths.data.iterdir()) and any(path.name not in {"logs", "runs"} for path in paths.data.iterdir()):
                raise ValueError("Le dossier de test contient déjà des données personnelles.")
            run = window.runs.create("Validation distribution", "black")
            window.runs.update(run.run_id, lambda item: setattr(item, "badges", 3))
            marker.write_text(json.dumps({"run_id": run.run_id}), encoding="utf-8")
            report["reopened"] = False
        assert RunManager(paths.data / "runs").load(run.run_id).badges == 3
        window.config_service.save(window.config)
        assert ConfigService(paths.data / "config.json").load() == window.config
        window.nav_buttons[4].click()
        assert window.pages.currentWidget() is window.settings_page
        window.runs_button.click()
        window.runs_page.refresh()
        assert window.pages.currentWidget() is window.runs_page
        report["card_layout"] = wait_for_run_card_layout(application, window.runs_page, run.run_id)
        assert len(window.catalog.games) >= 4 and len(window.catalog.rules) >= 15
        assert species_types(1, "black")
        for name in ("black.lua", "white.lua", "black2.lua", "white2.lua", "common/bridge.lua"):
            assert (paths.resources / "lua" / name).is_file()
        for name in ("PceRandomizer.java", "PceBlzDecode.java", "PceBlzEncode.java"):
            assert (paths.resources / "tools/randomizer" / name).is_file()
        from tools.shiny_field_trial import ENCODER, patch_body
        from tools.shiny_arm9_inspect import DECODER
        assert ENCODER.is_file() and DECODER.is_file()
        assert patch_body(1) != patch_body(4096)
        report["shiny_resources"] = {"imported": True, "java_sources_present": True,
                                     "scope": "packaged resources only; no ROM patched by this check"}
        if (paths.installation / "third-party/randomizer").is_dir():
            from app.services.rom_transformation_service import RomTransformationService
            tool = RomTransformationService.from_local_config(paths.data)
            assert tool.java_path.is_relative_to(paths.installation / "third-party/randomizer")
            assert tool.jar_path.is_relative_to(paths.installation / "third-party/randomizer")
            report["bundled_randomizer"] = {"verified": True, "java": str(tool.java_path), "jar": str(tool.jar_path)}
        report["screenshot"] = str(report_path.with_suffix(".png"))
        if not window.grab().save(report["screenshot"]):
            raise OSError("Capture de contrôle impossible.")
        report.update(ok=True, run_id=run.run_id, badges=3, games=len(window.catalog.games), rules=len(window.catalog.rules))
    except Exception as exc:
        logging.exception("Échec du contrôle de distribution")
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            logging.exception("Impossible d'écrire le rapport de distribution")
            report["ok"] = False
        window.close()
        application.exit(0 if report["ok"] else 2)
