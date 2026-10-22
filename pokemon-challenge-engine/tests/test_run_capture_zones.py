"""Synthetic zone/capture evidence through the real worker and manual dialog."""

from copy import deepcopy
from dataclasses import replace

import pytest

from app.services.run_controller import _RunWorker
from app.ui.run_dialogs import ManualRunEventDialog, zone_name
from test_rule_observation import tracking, results
from test_run_integration import qt_app, sample


def setup(tmp_path):
    manager, run, service = tracking(tmp_path, ["nuzlocke", "catch_limit"], params={"catch_limit": {"per_zone": 1}})
    return manager, run, service


def zone_checks(run):
    return {rule: item.checks for rule, item in results(run).items()}


def test_worker_zone_captures_share_identity_across_maps_and_survive_reload(qt_app, tmp_path):
    manager, run, service = setup(tmp_path)
    worker = _RunWorker(manager.root)
    worker.tracker, worker.running, worker.game_id = service, True, "white"
    for sequence, map_id in enumerate((1, 2), 1):
        worker.consume(replace(sample(sequence=sequence), observation={"capture_zone_id": "striaton_city",
                               "zone_name": "Same city", "map_id": map_id}))
        assert len(service.active_run.captures or []) == sequence - 1
        worker.action(run.run_id, "manual_capture", {"species_id": 498 + sequence})
        assert not worker.error
        assert all(len(items) == sequence - 1 for items in zone_checks(service.active_run).values())
    saved = manager.load(run.run_id)
    assert all(capture["zone"]["id"] == "striaton_city" for capture in saved.captures)
    assert all(len(items) == 1 and items[0].state == "review" for items in zone_checks(saved).values())
    path = manager.root / run.run_id / "run.json"
    before = path.read_bytes()
    original = saved.to_dict()
    zone_checks(manager.load(run.run_id))
    assert path.read_bytes() == before and saved.to_dict() == original


def test_unknown_map_after_known_zone_does_not_inherit_its_capture_count(qt_app, tmp_path):
    manager, run, service = setup(tmp_path)
    worker = _RunWorker(manager.root)
    worker.tracker, worker.running, worker.game_id = service, True, "white"
    worker.consume(replace(sample(sequence=1), observation={"capture_zone_id": "striaton_city", "map_id": 1}))
    service.manual_capture(498)
    worker.consume(replace(sample(sequence=2), observation={"map_id": 65535}))
    service.manual_capture(499)
    service.manual_capture(500)
    checks = zone_checks(manager.load(run.run_id))
    assert all([check.state for check in items] == ["unknown", "unknown"] for items in checks.values())
    assert service.active_run.current_zone == {"map_id": 65535}
    assert service.active_run.captures[0]["zone"]["id"] == "striaton_city"


def test_captures_before_first_known_zone_stay_unknown(qt_app, tmp_path):
    manager, run, service = setup(tmp_path)
    service.manual_capture(498)
    service.manual_capture(499)
    worker = _RunWorker(manager.root)
    worker.tracker, worker.running, worker.game_id = service, True, "white"
    worker.consume(replace(sample(), observation={"capture_zone_id": "striaton_city", "map_id": 1}))
    service.manual_capture(500)
    assert all([check.state for check in items] == ["unknown", "unknown"] for items in zone_checks(service.active_run).values())
    assert [capture["zone"] for capture in manager.load(run.run_id).captures[:2]] == [None, None]


@pytest.mark.parametrize("first,second", [("id", "capture_zone_id"), ("capture_zone_id", "zone_id"), ("zone_id", "id")])
def test_persisted_zone_aliases_count_together_without_rewriting(tmp_path, first, second):
    manager, run, service = setup(tmp_path)
    service.manual_capture(498, zone={first: "route_1", "map_id": 12, "name": "Old name"})
    service.manual_capture(499, zone={second: "route_1", "map_id": 13, "name": "New name"})
    loaded = manager.load(run.run_id)
    original = loaded.to_dict()
    assert all(len(items) == 1 and items[0].state == "review" for items in zone_checks(loaded).values())
    assert loaded.to_dict() == original
    assert first in loaded.captures[0]["zone"] and second in loaded.captures[1]["zone"]


@pytest.mark.parametrize("zone", [{}, {"map_id": 1}, {"name": "Route 1"}, {"zone_name": "Route 1"},
    {"id": 1}, {"id": " "}, {"zone_id": ""}, {"capture_zone_id": None},
    {"capture_zone_id": "route_1", "id": "route_2"}, {"zone_id": "route_1", "id": ""}])
def test_unknown_or_conflicting_zone_ids_never_merge_captures(tmp_path, zone):
    _, _, service = setup(tmp_path)
    service.manual_capture(498, zone=zone)
    service.manual_capture(499, zone=zone)
    assert all([check.state for check in items] == ["unknown", "unknown"] for items in zone_checks(service.active_run).values())


def test_equal_aliases_are_one_id_but_names_and_maps_do_not_identify_zones(tmp_path):
    _, _, service = setup(tmp_path)
    service.manual_capture(498, zone={"id": "route_1", "name": "Shared name", "map_id": 12})
    service.manual_capture(499, zone={"id": "route_2", "name": "Shared name", "map_id": 12})
    service.manual_capture(500, zone="Shared name")
    assert all(not items for items in zone_checks(service.active_run).values())
    service.manual_capture(501, zone={"capture_zone_id": "route_1", "zone_id": "route_1", "id": "route_1"})
    assert all(len(items) == 1 and items[0].state == "review" for items in zone_checks(service.active_run).values())


@pytest.mark.parametrize("key", ["id", "zone_id", "capture_zone_id"])
def test_manual_dialog_keeps_unchanged_structured_zone_detached(qt_app, tmp_path, key):
    _, _, service = setup(tmp_path)
    run = service.active_run
    run.current_zone = {key: "route_1", "name": "Route 1", "map_id": 12}
    original = deepcopy(run.current_zone)
    dialog = ManualRunEventDialog("manual_capture", run)
    try:
        dialog.pokemon_combo.setEditText("Known name")
        run.current_zone[key] = "route_2"  # A new snapshot must not change the opened declaration.
        payload = dialog.payload()
        assert payload["zone"] == original
        payload["zone"][key] = "changed"
        assert dialog.payload()["zone"] == original
        dialog.zone_edit.setText("Other manual zone")
        assert dialog.payload()["zone"] == "Other manual zone"
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()


def test_clearing_manual_zone_records_unknown_instead_of_current_zone(qt_app, tmp_path):
    _, _, service = setup(tmp_path)
    service.observe([], {"id": "route_1", "name": "Route 1"}, game_id="white", emulator_running=True)
    service.manual_capture(498)
    dialog = ManualRunEventDialog("manual_capture", service.active_run)
    try:
        dialog.pokemon_combo.setEditText("New individual")
        dialog.zone_edit.clear()
        payload = dialog.payload()
        assert payload["zone"] == ""
        service.manual_capture(**payload)
        assert all(len(items) == 1 and items[0].state == "unknown" for items in zone_checks(service.active_run).values())
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()


def test_zone_display_recognizes_canonical_id_without_inventing_a_name():
    assert zone_name({"capture_zone_id": "route_1"}) == "route_1"


@pytest.mark.parametrize("zone", [None, {}, {"map_id": 65535}, {"name": "Named but unidentified"}])
def test_unidentified_dialog_zone_remains_unknown_if_tracking_changes(qt_app, tmp_path, zone):
    _, _, service = setup(tmp_path)
    run = service.active_run
    run.current_zone = deepcopy(zone)
    dialog = ManualRunEventDialog("manual_capture", run)
    try:
        dialog.pokemon_combo.setEditText("New individual")
        service.observe([], {"id": "route_1", "name": "Route 1"}, game_id="white", emulator_running=True)
        service.manual_capture(498)
        payload = dialog.payload()
        assert payload["zone"] == ("" if zone is None else zone)
        service.manual_capture(**payload)
        assert all(len(items) == 1 and items[0].state == "unknown" for items in zone_checks(service.active_run).values())
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()
