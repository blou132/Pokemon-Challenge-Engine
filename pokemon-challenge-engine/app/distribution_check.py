"""Opt-in packaged UI/persistence check; never an emulation or gameplay claim."""

import json
import logging
from pathlib import Path
import sys

from app import __version__
from app.core.run_manager import RunManager
from app.core.gen5_species import species_types
from app.services.config_service import ConfigService
from app.ui.runs_page import RunCard


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
        application.processEvents()
        assert window.pages.currentWidget() is window.runs_page
        assert any(card.run_id == run.run_id for card in window.runs_page.findChildren(RunCard))
        assert len(window.catalog.games) >= 4 and len(window.catalog.rules) >= 15
        assert species_types(1, "black")
        for name in ("black.lua", "white.lua", "black2.lua", "white2.lua", "common/bridge.lua"):
            assert (paths.resources / "lua" / name).is_file()
        assert (paths.resources / "tools/randomizer/PceRandomizer.java").is_file()
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
