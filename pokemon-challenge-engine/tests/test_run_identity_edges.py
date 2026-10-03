"""Adversarial synthetic run observations: ambiguity must never kill a wrong individual."""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.pokemon_identity import pokemon_identity
from app.core.run_manager import RunManager
from app.models.challenge import Challenge
from app.models.run import Run
from app.services.run_tracking_service import RunTrackingService


class Clock:
    def __init__(self):
        self.seconds = 0.0

    def monotonic(self):
        return self.seconds

    def utc(self):
        return (datetime(2030, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=self.seconds)).isoformat()

    def advance(self, seconds=1.0):
        self.seconds += seconds


def pokemon(*, species=498, pid=123, trainer=456, slot=1, hp=20, level=15):
    return {"slot": slot, "species_id": species, "level": level, "hp": hp, "max_hp": 40,
            "personality_id": pid, "original_trainer_id": trainer}


@pytest.fixture
def tracking(tmp_path):
    manager = RunManager(tmp_path / "runs")
    challenge = Challenge("white", "custom", ["nuzlocke", "permanent_death"], {},
                          {"enforcement": "soft", "rule_parameters": {}}, None, 1)
    run = manager.create("Identity edges", "white", challenge=challenge, game_code="IRAF", region="FR", revision=0)
    clock = Clock()
    service = RunTrackingService(manager, clock=clock.monotonic, utc_clock=clock.utc)
    service.activate(run.run_id)
    return service, manager, clock


def observe(tracking, party, **changes):
    service, _, clock = tracking
    clock.advance()
    args = {"game_id": "white", "game_code": "IRAF", "region": "FR", "revision": 0,
            "emulator_running": True, "valid": True, "connected": True}
    return service.observe(party, "Route 3", **(args | changes))


def events(run, kind):
    return [item for item in run.history if item["type"] == kind]


def test_two_same_species_are_independent_despite_party_reordering(tracking):
    observe(tracking, [pokemon(pid=1, slot=1), pokemon(pid=2, slot=2)])
    run = observe(tracking, [pokemon(pid=2, slot=1, hp=0), pokemon(pid=1, slot=2)])
    assert run.death_count == 1
    assert run.deaths[0]["pokemon_key"] == pokemon_identity(pokemon(pid=2))
    assert [item["life_status"] for item in run.current_party] == ["dead", "alive"]


def test_same_pid_different_original_trainer_is_a_new_individual(tracking):
    observe(tracking, [pokemon(trainer=1)])
    run = observe(tracking, [pokemon(trainer=2, hp=0)])
    assert run.death_count is None
    assert not events(run, "pokemon_fainted")
    assert len(run.pending_deaths) == 1


@pytest.mark.parametrize("first,second", [(498, 499), (498, 500), (133, 197), (290, 291)])
def test_forward_evolution_keeps_identity_and_detected_faint(tracking, first, second):
    observe(tracking, [pokemon(species=first)])
    run = observe(tracking, [pokemon(species=second, hp=0, level=25)])
    assert run.death_count == 1
    key = pokemon_identity(pokemon())
    assert [entry["species_id"] for entry in run.known_pokemon[key]["species_history"]] == [first, second]


@pytest.mark.parametrize("first,second", [(291, 292), (290, 292), (292, 291), (134, 135), (500, 498), (498, 501)])
def test_species_replacement_is_not_a_documented_individual_evolution(tracking, first, second):
    observe(tracking, [pokemon(species=first)])
    run = observe(tracking, [pokemon(species=second, hp=0)])
    assert run.death_count is None
    assert not events(run, "pokemon_fainted")
    assert run.current_party[0]["identity_confidence"] == "weak"
    assert run.pending_deaths


def test_duplicate_pair_in_one_snapshot_never_creates_an_automatic_death(tracking):
    observe(tracking, [pokemon()])
    run = observe(tracking, [pokemon(slot=1, hp=0), pokemon(slot=2, hp=20)])
    assert run.death_count is None
    assert not events(run, "pokemon_fainted")
    assert all(member["identity_confidence"] == "weak" for member in run.current_party)


@pytest.mark.parametrize("restart", [False, True])
def test_disappearing_clone_does_not_erase_known_ambiguity(tracking, restart):
    service, manager, clock = tracking
    observe(tracking, [pokemon()])
    observe(tracking, [pokemon(slot=1), pokemon(slot=2)])
    if restart:
        service.flush(force=True)
        service = RunTrackingService(RunManager(manager.root), clock=clock.monotonic, utc_clock=clock.utc)
        tracking = service, service.manager, clock
    observe(tracking, [pokemon(hp=20)])
    run = observe(tracking, [pokemon(hp=0)])
    assert run.death_count is None
    assert not events(run, "pokemon_fainted")
    assert run.current_party[0]["identity_confidence"] == "weak"
    assert run.pending_deaths


def test_collision_in_first_observation_is_remembered_without_a_prior_known_individual(tracking):
    observe(tracking, [pokemon(slot=1), pokemon(slot=2)])
    observe(tracking, [pokemon()])
    run = observe(tracking, [pokemon(hp=0)])
    assert run.death_count is None
    assert not events(run, "pokemon_fainted")
    assert run.current_party[0]["identity_confidence"] == "weak"


def test_identity_conflict_stays_ambiguous_when_the_original_species_returns(tracking):
    observe(tracking, [pokemon(species=498)])
    observe(tracking, [pokemon(species=501)])
    observe(tracking, [pokemon(species=498)])
    run = observe(tracking, [pokemon(species=498, hp=0)])
    assert run.death_count is None
    assert not events(run, "pokemon_fainted")
    assert run.pending_deaths


def test_clone_collision_neither_resurrects_nor_misidentifies_a_known_dead_individual(tracking):
    observe(tracking, [pokemon()])
    observe(tracking, [pokemon(hp=0)])
    observe(tracking, [pokemon(slot=1), pokemon(slot=2)])
    run = observe(tracking, [pokemon(hp=40)])
    assert run.death_count == 1
    assert len(events(run, "pokemon_marked_dead")) == 1
    assert run.current_party[0]["identity_confidence"] == "weak"
    assert run.current_party[0]["life_status"] == "unknown"
    assert run.known_pokemon[pokemon_identity(pokemon())]["life_status"] == "dead"


@pytest.mark.parametrize("barrier", ["invalid", "disconnect", "closed", "wrong_game", "wrong_code", "wrong_revision", "timeout", "absent"])
def test_invalid_or_missing_observation_breaks_positive_to_zero_transition(tracking, barrier):
    service, _, clock = tracking
    observe(tracking, [pokemon()])
    if barrier == "invalid":
        with pytest.raises(ValueError):
            observe(tracking, [pokemon(hp=41)])
    elif barrier == "disconnect":
        observe(tracking, [pokemon()], connected=False)
    elif barrier == "closed":
        observe(tracking, [pokemon()], emulator_running=False)
    elif barrier == "wrong_game":
        observe(tracking, [pokemon()], game_id="black")
    elif barrier == "wrong_code":
        observe(tracking, [pokemon()], game_code="IRBF")
    elif barrier == "wrong_revision":
        observe(tracking, [pokemon()], revision=1)
    elif barrier == "timeout":
        clock.advance(service.observation_timeout + 1)
    elif barrier == "absent":
        observe(tracking, [])
    run = observe(tracking, [pokemon(hp=0)])
    assert run.death_count is None
    assert not events(run, "pokemon_fainted")
    assert len(run.pending_deaths) == 1


def test_crash_does_not_join_old_positive_hp_to_a_new_zero_observation(tracking):
    service, manager, clock = tracking
    observe(tracking, [pokemon()])
    service.flush(force=True)
    clock.advance(8 * 3600)
    reopened = RunTrackingService(RunManager(manager.root), clock=clock.monotonic, utc_clock=clock.utc)
    run = observe((reopened, reopened.manager, clock), [pokemon(hp=0)])
    assert run.death_count is None
    assert not events(run, "pokemon_fainted")
    assert run.pending_deaths
    assert run.total_play_seconds < 10


def test_dead_individual_stays_dead_after_crash_heal_and_evolution(tracking):
    service, manager, clock = tracking
    observe(tracking, [pokemon()])
    dead = observe(tracking, [pokemon(hp=0)])
    assert manager.load(dead.run_id).death_count == 1  # critical autosave
    clock.advance(8 * 3600)
    reopened = RunTrackingService(RunManager(manager.root), clock=clock.monotonic, utc_clock=clock.utc)
    run = observe((reopened, reopened.manager, clock), [pokemon(species=499, hp=40, level=20)])
    assert run.death_count == 1
    assert run.current_party[0]["life_status"] == "dead"
    assert run.known_pokemon[pokemon_identity(pokemon())]["life_status"] == "dead"
    assert len(events(run, "pokemon_marked_dead")) == 1
    assert run.total_play_seconds < 10


def test_dead_individual_leaving_party_keeps_graveyard_record(tracking):
    observe(tracking, [pokemon()])
    observe(tracking, [pokemon(hp=0)])
    run = observe(tracking, [pokemon(pid=321)])
    assert run.death_count == 1 and len(run.deaths) == 1
    assert run.known_pokemon[pokemon_identity(pokemon())]["life_status"] == "dead"
    assert run.current_party[0]["life_status"] == "alive"


def test_correction_retains_original_history_and_prevents_repeated_zero_from_rekilling(tracking):
    service, _, _ = tracking
    observe(tracking, [pokemon()])
    dead = observe(tracking, [pokemon(hp=0)])
    original_events = [entry["event_id"] for entry in dead.history]
    with pytest.raises(ValueError):
        service.correct_death(dead.deaths[0]["death_id"])
    service.correct_death(dead.deaths[0]["death_id"], "False reading", confirmed=True)
    run = observe(tracking, [pokemon(hp=0)])
    assert run.death_count == 0
    assert all(event in [entry["event_id"] for entry in run.history] for event in original_events)
    assert len(events(run, "death_corrected")) == 1
    assert len(events(run, "pokemon_marked_dead")) == 1


@pytest.mark.parametrize("field,value", [
    ("species_id", None), ("species_id", "498"), ("species_id", 650),
    ("species_history", None), ("species_history", [None]),
    ("species_history", [{"species_id": 498}]),
    ("life_status", "resurrected"), ("identity_ambiguous", "false"),
])
def test_corrupt_persisted_individual_is_rejected_before_live_observation(tracking, field, value):
    run = observe(tracking, [pokemon()])
    data = run.to_dict()
    key = pokemon_identity(pokemon())
    data["known_pokemon"][key][field] = value
    with pytest.raises(ValueError):
        Run.from_dict(data)


def test_missing_known_individual_fields_cannot_be_loaded_as_valid_progress(tracking):
    run = observe(tracking, [pokemon()])
    data = run.to_dict()
    data["known_pokemon"][pokemon_identity(pokemon())] = {}
    with pytest.raises(ValueError):
        Run.from_dict(data)


@pytest.mark.parametrize("key", [[], {}, True, 123])
def test_corrupt_death_identity_is_rejected_before_correction(tracking, key):
    observe(tracking, [pokemon()])
    run = observe(tracking, [pokemon(hp=0)])
    data = run.to_dict()
    data["deaths"][0]["pokemon_key"] = key
    with pytest.raises(ValueError):
        Run.from_dict(data)


def test_corrupt_run_file_is_preserved_and_never_partially_loaded(tmp_path):
    import json
    manager = RunManager(tmp_path / "runs")
    run = manager.create("Preserve corrupt identity", "white")
    manager.set_active_id(run.run_id)
    path = manager.root / run.run_id / "run.json"
    data = run.to_dict()
    data["known_pokemon"] = {"gen5:00000001:00000002": {}}
    payload = json.dumps(data).encode("utf-8")
    path.write_bytes(payload)
    service = RunTrackingService(RunManager(manager.root))
    assert service.active_run is None and service.last_error
    assert path.read_bytes() == payload
