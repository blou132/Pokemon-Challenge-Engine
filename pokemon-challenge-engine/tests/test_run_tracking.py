"""Synthetic domain observations, never a claim of real emulator validation."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.core.run_manager import RunManager
from app.models.challenge import Challenge
from app.services.run_tracking_service import RunTrackingService, set_inactive_run_status


class Clock:
    def __init__(self):
        self.seconds = 0.0

    def __call__(self):
        return self.seconds

    def utc(self):
        return (datetime(2030, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=self.seconds)).isoformat()

    def advance(self, value=1):
        self.seconds += value


def pokemon(pid=123, trainer=456, *, hp=30, species=498, slot=1, level=5):
    return {"species_id": species, "slot": slot, "level": level, "hp": hp, "max_hp": 30,
            "personality_id": pid, "original_trainer_id": trainer}


@pytest.fixture
def setup_run(tmp_path):
    manager = RunManager(tmp_path / "runs")
    rules = Challenge("white", "custom", ["nuzlocke", "permanent_death"], {},
                      {"enforcement": "soft", "rule_parameters": {}}, None, 123)
    run = manager.create("Blanc Test", "white", challenge=rules, game_code="IRAF", region="FR", revision=0)
    clock = Clock()
    service = RunTrackingService(manager, clock=clock, utc_clock=clock.utc)
    service.activate(run.run_id)
    return manager, run, service, clock


def observe(service, party=None, **kwargs):
    options = dict(game_id="white", game_code="IRAF", region="FR", revision=0, emulator_running=True)
    options.update(kwargs)
    return service.observe([pokemon()] if party is None else party, **options)


def types(run):
    return [entry["type"] for entry in run.history]


def test_start_heartbeat_stop_resume_and_total(setup_run):
    manager, run, service, clock = setup_run
    assert not service.session_active
    service.heartbeat(True, "white")
    assert service.active_run.total_play_seconds == 0
    observe(service)
    assert service.session_active and service.active_run.status == "active"
    clock.advance(3)
    service.heartbeat(True, "white")
    assert service.active_run.total_play_seconds == 3
    service.heartbeat(False, "white")
    assert not service.session_active
    clock.advance(10000)
    observe(service)
    clock.advance(2)
    service.heartbeat(True, "white")
    service.close()
    stored = manager.load(run.run_id)
    assert stored.total_play_seconds == 5 and len(stored.sessions) == 2
    assert all(item["ended_at"] for item in stored.sessions)


@pytest.mark.parametrize("options", [{"emulator_running": False}, {"connected": False}, {"valid": False},
                                     {"game_id": "black"}, {"game_code": "IRBF"}, {"region": "US"},
                                     {"revision": 1}, {"game_code": None}])
def test_wrong_or_unproven_environment_never_counts(setup_run, options):
    _, _, service, clock = setup_run
    observe(service, **options)
    clock.advance(100)
    service.heartbeat(True, "white")
    assert service.active_run.total_play_seconds == 0 and service.active_run.sessions == []
    assert service.active_run.current_party == []


def test_no_eight_hour_gap_when_machine_or_pce_sleeps(setup_run):
    _, _, service, clock = setup_run
    observe(service)
    clock.advance(2)
    service.heartbeat(True, "white")
    clock.advance(8 * 3600)
    observe(service)
    assert service.active_run.total_play_seconds == 2
    assert len(service.active_run.sessions) == 2


def test_crash_recovery_uses_last_persisted_heartbeat_only(setup_run):
    manager, run, service, clock = setup_run
    observe(service)
    clock.advance(2)
    service.heartbeat(True, "white")
    service.flush(force=True)
    clock.advance(2)
    observe(service)
    clock.advance(8 * 3600)
    restarted = RunTrackingService(RunManager(manager.root), clock=clock, utc_clock=clock.utc)
    recovered = restarted.active_run
    assert recovered.run_id == run.run_id and recovered.total_play_seconds == 2
    assert recovered.sessions[0]["ended_at"] == recovered.sessions[0]["last_heartbeat"]
    assert not restarted.session_active
    assert recovered.history[-1]["payload"]["reason"] == "crash_recovery"


def test_switch_stops_previous_and_does_not_reuse_old_identity(setup_run):
    manager, first, service, clock = setup_run
    second = manager.create("B", "white")
    observe(service)
    clock.advance(1)
    service.heartbeat(True, "white")
    service.activate(second.run_id)
    assert manager.load(first.run_id).total_play_seconds == 1
    assert manager.load(first.run_id).sessions[0]["ended_at"] is not None
    service.heartbeat(True, "white")
    assert service.active_run.total_play_seconds == 0 and not service.session_active


def test_autosave_data_debounce_and_heartbeat_frequency(setup_run, monkeypatch):
    manager, _, service, clock = setup_run
    calls = []
    original = manager.save
    def record(run):
        calls.append(clock())
        original(run)
    monkeypatch.setattr(manager, "save", record)
    observe(service, zone="Route 1")
    assert calls == [0] and service.dirty
    clock.advance(0.1)
    observe(service, zone="Route 1")
    assert calls == [0]
    clock.advance(1.9)
    service.heartbeat(True, "white")
    assert calls == [0, 2] and not service.dirty
    for _ in range(14):
        clock.advance()
        observe(service, zone="Route 1")
    assert calls == [0, 2]
    clock.advance()
    observe(service, zone="Route 1")
    assert calls == [0, 2, 17]


def test_autosave_failure_keeps_dirty_then_can_retry(setup_run, monkeypatch):
    manager, run, service, clock = setup_run
    original = manager.save
    def fail(item):
        raise OSError("disk unavailable")
    monkeypatch.setattr(manager, "save", fail)
    with pytest.raises(OSError):
        service.add_note("Keep this note")
    assert service.dirty and service.last_error == "disk unavailable"
    assert manager.load(run.run_id).notes == []
    monkeypatch.setattr(manager, "save", original)
    service.flush(force=True)
    assert manager.load(run.run_id).notes[0]["text"] == "Keep this note"
    assert not service.dirty and service.last_error is None


def test_zone_and_party_history_do_not_repeat_each_frame(setup_run):
    _, _, service, clock = setup_run
    for _ in range(10):
        observe(service, zone={"zone_id": "route_1", "name": "Route 1"})
        clock.advance(0.1)
    assert types(service.active_run).count("zone_changed") == 1
    assert types(service.active_run).count("party_changed") == 1
    assert service.active_run.captures is None


def test_same_species_individuals_stay_separate_on_slot_swap(setup_run):
    _, _, service, _ = setup_run
    observe(service, [pokemon(pid=1), pokemon(pid=2, slot=2)])
    first_keys = set(service.active_run.known_pokemon)
    observe(service, [pokemon(pid=1, slot=2, hp=20), pokemon(pid=2, slot=1, level=6)])
    assert len(first_keys) == 2 and set(service.active_run.known_pokemon) == first_keys
    assert sorted(item["hp"] for item in service.active_run.current_party) == [20, 30]


def test_evolution_keeps_identity_and_history(setup_run):
    _, _, service, _ = setup_run
    observe(service)
    key = service.active_run.current_party[0]["pokemon_key"]
    observe(service, [pokemon(species=499, level=17)])
    observe(service, [pokemon(species=500, level=36)])
    assert len(service.active_run.known_pokemon) == 1
    assert service.active_run.current_party[0]["pokemon_key"] == key
    assert [item["species_id"] for item in service.active_run.known_pokemon[key]["species_history"]] == [498, 499, 500]


def test_faint_transition_marks_dead_once_then_healed_remains_dead(setup_run):
    manager, run, service, _ = setup_run
    observe(service)
    observe(service, [pokemon(hp=0)], zone="Route 4")
    dead = service.active_run
    assert dead.death_count == 1 and dead.current_party[0]["life_status"] == "dead"
    assert manager.load(run.run_id).death_count == 1  # critical event flushes immediately
    observe(service, [pokemon(hp=0)])
    observe(service, [pokemon(hp=30)])
    assert service.active_run.current_party[0]["life_status"] == "dead"
    assert types(service.active_run).count("pokemon_marked_dead") == 1
    assert types(service.active_run).count("pokemon_fainted") == 1
    observe(service, [])
    assert service.active_run.current_party == [] and service.active_run.death_count == 1
    service.close()
    assert RunTrackingService(RunManager(manager.root)).active_run.death_count == 1


def test_dead_evolved_individual_remains_dead(setup_run):
    _, _, service, _ = setup_run
    observe(service)
    observe(service, [pokemon(hp=0)])
    observe(service, [pokemon(species=499, hp=30, level=17)])
    assert service.active_run.current_party[0]["life_status"] == "dead"
    assert len(service.active_run.known_pokemon) == 1


def test_inactive_permanent_rule_records_faint_only(tmp_path):
    manager = RunManager(tmp_path)
    run = manager.create("Classic", "white")
    service = RunTrackingService(manager)
    service.activate(run.run_id)
    observe(service)
    observe(service, [pokemon(hp=0)])
    assert service.active_run.deaths is None
    assert types(service.active_run).count("pokemon_fainted") == 1
    assert service.pending_deaths == []


def test_initial_zero_hp_requires_review_not_death(setup_run):
    _, _, service, _ = setup_run
    observe(service, [pokemon(hp=0)])
    observe(service, [pokemon(hp=0)])
    assert service.active_run.deaths is None and len(service.pending_deaths) == 1
    assert "pokemon_fainted" not in types(service.active_run)


@pytest.mark.parametrize("missing", ["personality_id", "original_trainer_id"])
def test_weak_identity_never_marks_wrong_individual(setup_run, missing):
    _, _, service, _ = setup_run
    member = pokemon()
    member.pop(missing)
    observe(service, [member])
    member["hp"] = 0
    observe(service, [member])
    assert service.active_run.deaths is None and len(service.pending_deaths) == 1
    assert service.active_run.current_party[0]["pokemon_key"] is None


def test_duplicate_ids_and_unrelated_family_are_ambiguous(setup_run):
    _, _, service, _ = setup_run
    observe(service)
    observe(service, [pokemon(), pokemon(hp=0, slot=2)])
    assert service.active_run.deaths is None
    assert all(item["identity_confidence"] == "weak" for item in service.active_run.current_party)
    observe(service, [pokemon(species=25, hp=0)])
    assert service.active_run.current_party[0]["identity_confidence"] == "weak"
    assert service.active_run.deaths is None


def test_disconnect_removes_positive_baseline_before_zero(setup_run):
    _, _, service, _ = setup_run
    observe(service)
    service.heartbeat(False, "white")
    observe(service, [pokemon(hp=0)])
    assert service.active_run.deaths is None and len(service.pending_deaths) == 1


def test_manual_death_is_sticky_and_correction_is_auditable(setup_run):
    _, _, service, _ = setup_run
    observe(service)
    key = service.active_run.current_party[0]["pokemon_key"]
    service.manual_death(key, note="Confirmed by player")
    death_id = service.active_run.deaths[0]["death_id"]
    service.manual_death(key)
    assert service.active_run.death_count == 1
    observe(service)
    assert service.active_run.current_party[0]["life_status"] == "dead"
    original = deepcopy(service.active_run.history)
    with pytest.raises(ValueError, match="Confirmez"):
        service.correct_death(death_id)
    service.correct_death(death_id, "Wrong individual", confirmed=True)
    corrected = service.active_run
    assert corrected.death_count == 0 and len(corrected.deaths) == 1
    assert corrected.history[:len(original)] == original
    assert corrected.history[-1]["type"] == "death_corrected"
    assert corrected.current_party[0]["life_status"] == "alive"


def test_manual_unknown_individual_enters_graveyard_without_slot_guess(setup_run):
    _, _, service, _ = setup_run
    observe(service)
    service.manual_death(pokemon="Gruikui", zone="Route 4")
    assert service.active_run.death_count == 1
    assert service.active_run.current_party[0]["life_status"] == "alive"
    assert service.active_run.deaths[0]["pokemon_key"] is None


def test_manual_captures_badges_notes_and_backups_have_explicit_sources(setup_run):
    manager, run, service, _ = setup_run
    service.manual_capture(498, "Route 1", note="Manual entry")
    service.set_badges(0)
    service.set_badges(1)
    service.set_badges(1)
    service.add_note("First badge")
    service.record_backup({"path": "isolated/backup.dsv", "reason": "manual"})
    stored = manager.load(run.run_id)
    assert len(stored.captures) == 1 and stored.badges == 1 and stored.deaths is None
    assert types(stored).count("manual_badge") == 2
    assert all(item["source"] == "manual" for item in stored.history if item["type"] in {"manual_badge", "manual_capture", "note_added"})
    assert stored.history[-1]["source"] == "system"


@pytest.mark.parametrize("method,args", [("set_badges", (9,)), ("set_badges", (True,)), ("add_note", (" ",)),
                                        ("manual_capture", (0,)), ("manual_death", ("unknown",)),
                                        ("set_status", ("lost",))])
def test_invalid_manual_input_leaves_run_unmodified(setup_run, method, args):
    _, _, service, _ = setup_run
    before = service.active_run
    with pytest.raises(ValueError):
        getattr(service, method)(*args)
    assert service.active_run == before


@pytest.mark.parametrize("status", ["finished", "abandoned", "archived"])
def test_terminal_status_stops_timer_until_explicit_reactivation(setup_run, status):
    _, _, service, clock = setup_run
    observe(service)
    service.set_status(status)
    assert not service.session_active
    clock.advance(10)
    observe(service)
    assert service.active_run.total_play_seconds == 0
    service.set_status("active")
    observe(service)
    assert service.session_active


def test_detached_views_cannot_mutate_service(setup_run):
    _, _, service, _ = setup_run
    view = service.active_run
    view.name = "Changed externally"
    view.rules_snapshot["active_rules"].clear()
    assert service.active_run.name != view.name and service.active_run.active_rules


def test_launch_reference_saved_without_changing_snapshot(setup_run):
    manager, run, service, _ = setup_run
    rules = service.active_run.rules_snapshot
    service.update_launch_reference({"save_path": "C:/isolated/copied.dsv", "_source": {"rom": "game.zip"}}, "a" * 64)
    stored = manager.load(run.run_id)
    assert stored.rules_snapshot == rules and stored.save_path.endswith("copied.dsv")
    assert stored.rom_fingerprint == "a" * 64


def test_invalid_party_never_causes_death_and_drops_previous_baseline(setup_run):
    _, _, service, _ = setup_run
    observe(service)
    bad = pokemon(hp=31)
    with pytest.raises(ValueError):
        observe(service, [bad])
    observe(service, [pokemon(hp=0)])
    assert service.active_run.deaths is None


def test_repeated_changes_never_forge_a_capture(setup_run):
    _, _, service, _ = setup_run
    observe(service, [])
    observe(service, [pokemon()])
    observe(service, [pokemon(), pokemon(pid=999, species=501, slot=2)])
    assert service.active_run.captures is None and "manual_capture" not in types(service.active_run)


@pytest.mark.parametrize("strong", [True, False])
def test_manual_review_resolved_without_repeated_prompt_and_remains_auditable(setup_run, strong):
    _, _, service, _ = setup_run
    member = pokemon(hp=0)
    if not strong:
        member.pop("original_trainer_id")
    observe(service, [member])
    review = service.pending_deaths[0]
    service.manual_death(review_id=review["review_id"], note="Confirmed on screen")
    assert service.pending_deaths == []
    assert service.active_run.pending_deaths[0]["resolved"] is True
    assert service.active_run.deaths[0]["review_id"] == review["review_id"]
    observe(service, [member])
    assert service.pending_deaths == [] and service.active_run.death_count == 1
    with pytest.raises(ValueError, match="déjà traitée"):
        service.manual_death(review_id=review["review_id"])


def test_review_cannot_be_applied_to_another_known_individual(setup_run):
    _, _, service, _ = setup_run
    observe(service, [pokemon(hp=0), pokemon(pid=999, slot=2)])
    review = service.pending_deaths[0]
    other = service.active_run.current_party[1]["pokemon_key"]
    with pytest.raises(ValueError, match="ne correspond pas"):
        service.manual_death(pokemon_key=other, review_id=review["review_id"])
    assert service.active_run.deaths is None


def test_gen_v_slot_seven_is_not_a_valid_observation(setup_run):
    _, _, service, _ = setup_run
    with pytest.raises(ValueError):
        observe(service, [pokemon(slot=7)])
    assert service.active_run.current_party == []


def test_persisted_strong_key_must_match_its_pid_and_trainer(setup_run):
    from app.models.run import Run
    _, _, service, _ = setup_run
    observed = observe(service).to_dict()
    observed["current_party"][0]["personality_id"] += 1
    with pytest.raises(ValueError, match="identité forte"):
        Run.from_dict(observed)


@pytest.mark.parametrize("status", ["preparing", "active", "finished", "abandoned", "archived"])
def test_inactive_status_edit_preserves_other_active_run_and_pointer(setup_run, status):
    manager, active, service, _ = setup_run
    observe(service)
    inactive = manager.create("Other adventure", "white")
    pointer = (manager.root / "active.json").read_bytes()
    active_bytes = (manager.root / active.run_id / "run.json").read_bytes()
    changed = set_inactive_run_status(manager, inactive.run_id, status)
    assert changed.status == status and changed.sessions == []
    assert (manager.root / "active.json").read_bytes() == pointer
    assert (manager.root / active.run_id / "run.json").read_bytes() == active_bytes
    assert service.active_run.run_id == active.run_id and service.session_active
    if status != "preparing":
        assert changed.history[-1]["type"] == "status_changed"
        assert changed.history[-1]["source"] == "manual"
    assert (changed.finished_at is not None) == (status == "finished")


@pytest.mark.parametrize("original", ["finished", "abandoned", "archived"])
def test_inactive_terminal_run_can_be_reactivated_without_resume_deadlock(tmp_path, original):
    manager = RunManager(tmp_path)
    run = manager.create("Inactive", "white")
    set_inactive_run_status(manager, run.run_id, original)
    reactivated = set_inactive_run_status(manager, run.run_id, "preparing")
    assert reactivated.status == "preparing" and reactivated.finished_at is None
    assert manager.active_id is None
    assert not (tmp_path / "active.json").exists()
    assert reactivated.history[-1]["payload"] == {"previous": original, "status": "preparing"}


def test_inactive_status_recovers_crashed_session_at_persisted_heartbeat(setup_run):
    manager, run, service, clock = setup_run
    observe(service)
    clock.advance(3)
    service.heartbeat(True, "white")
    service.flush(force=True)
    selected = (manager.root / "active.json").read_bytes()
    clock.advance(8 * 3600)
    changed = set_inactive_run_status(RunManager(manager.root), run.run_id, "archived")
    assert changed.total_play_seconds == 3
    assert changed.sessions[-1]["ended_at"] == changed.sessions[-1]["last_heartbeat"]
    assert changed.history[-2]["payload"]["reason"] == "crash_recovery"
    assert changed.history[-1]["type"] == "status_changed"
    assert (manager.root / "active.json").read_bytes() == selected


def test_inactive_identical_status_is_a_noop_and_invalid_status_preserves_file(tmp_path):
    manager = RunManager(tmp_path)
    run = manager.create("Inactive", "white")
    path = tmp_path / run.run_id / "run.json"
    before = path.read_bytes()
    set_inactive_run_status(manager, run.run_id, "preparing")
    assert path.read_bytes() == before
    with pytest.raises(ValueError):
        set_inactive_run_status(manager, run.run_id, "game_over")
    assert path.read_bytes() == before
