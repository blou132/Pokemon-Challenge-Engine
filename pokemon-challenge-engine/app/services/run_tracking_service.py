"""Run-owned sessions and read-only observations; call from the dedicated worker."""

from collections import Counter
from copy import deepcopy
from datetime import datetime
import math
from time import monotonic
from uuid import uuid4

from app.core.run_manager import RunManager
from app.models.profile import validate_json_data
from app.models.run import RUN_STATUSES, Run, history_event, utc_now, validate_timestamp, _pokemon


def set_inactive_run_status(manager: RunManager, run_id: str, status: str) -> Run:
    """Administrative edit without activating or switching the tracked playthrough.

    The worker routes its active run to ``tracker.set_status`` instead. A stored
    selection is not proof of a live tracker, so active.json is neither changed
    nor used as a runtime liveness check here.
    """
    if not isinstance(status, str) or status not in RUN_STATUSES:
        raise ValueError("Statut de partie inconnu.")

    def update(run: Run) -> None:
        stamp = utc_now()
        if run.history:
            previous = run.history[-1]["timestamp"]
            if datetime.fromisoformat(stamp.replace("Z", "+00:00")) < datetime.fromisoformat(previous.replace("Z", "+00:00")):
                stamp = previous
        for session in run.sessions:
            if session["ended_at"] is None:
                session["ended_at"] = session["last_heartbeat"]
                run.history.append(history_event("session_ended", "system", {
                    "session_id": session["session_id"], "duration": session["duration"],
                    "reason": "crash_recovery", "recovered_until": session["last_heartbeat"],
                }, stamp))
        run.total_play_seconds = sum(item["duration"] for item in run.sessions)
        if run.status != status:
            previous = run.status
            run.status = status
            run.finished_at = stamp if status == "finished" else None
            run.history.append(history_event("status_changed", "manual", {
                "previous": previous, "status": status,
            }, stamp))

    return manager.update(run_id, update)


class RunTrackingService:
    def __init__(self, manager: RunManager, *, clock=monotonic, utc_clock=utc_now,
                 debounce_seconds: float = 2.0, heartbeat_seconds: float = 15.0,
                 observation_timeout: float = 5.0):
        for value in (debounce_seconds, heartbeat_seconds, observation_timeout):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("Les délais de suivi doivent être positifs et finis.")
        self.manager, self._clock, self._utc_clock = manager, clock, utc_clock
        self.debounce_seconds, self.heartbeat_seconds = debounce_seconds, heartbeat_seconds
        self.observation_timeout = observation_timeout
        self._run: Run | None = None
        self.dirty = False
        self._data_dirty = False
        self._critical_dirty = False
        self.last_saved_at: str | None = None
        self.last_error: str | None = None
        self._dirty_since: float | None = None
        self._last_save = self._clock()
        self._last_tick: float | None = None
        self._last_observation: float | None = None
        self._previous_party: dict[str, dict] = {}
        self._session_id: str | None = None
        self._activation_pending = False
        self._activation_previous = None
        self._activation_same = False
        try:
            selected = manager.active_id
            if selected is not None:
                self._run = manager.load(selected)
                self._recover()
                self.flush(force=True)
        except (OSError, ValueError) as exc:
            self.last_error = str(exc)
            self._run = None

    @property
    def active_run(self) -> Run | None:
        return deepcopy(self._run)

    @property
    def pending_deaths(self) -> list[dict]:
        return deepcopy([item for item in self._run.pending_deaths if not item.get("resolved", False)]) if self._run else []

    @property
    def session_active(self) -> bool:
        return self._session_id is not None

    def _require(self) -> Run:
        if self._run is None:
            raise ValueError("Activez une partie avant de modifier son suivi.")
        return self._run

    def _now(self) -> str:
        stamp = self._utc_clock()
        if isinstance(stamp, datetime):
            stamp = stamp.isoformat()
        validate_timestamp(stamp)
        # Wall clock adjustments must not reorder the append-only chronology.
        if self._run and self._run.history:
            previous = self._run.history[-1]["timestamp"]
            if datetime.fromisoformat(stamp.replace("Z", "+00:00")) < datetime.fromisoformat(previous.replace("Z", "+00:00")):
                return previous
        return stamp

    def _mark(self, *, heartbeat_only: bool = False) -> None:
        if not self.dirty or not heartbeat_only and not self._data_dirty:
            self._dirty_since = self._clock()
        self.dirty = True
        self._data_dirty = self._data_dirty or not heartbeat_only

    def _event(self, kind: str, source: str, payload: dict) -> None:
        self._require().history.append(history_event(kind, source, payload, self._now()))
        self._mark()

    def _recover(self) -> None:
        run = self._require()
        for session in run.sessions:
            if session["ended_at"] is None:
                session["ended_at"] = session["last_heartbeat"]
                self._event("session_ended", "system", {"session_id": session["session_id"],
                            "duration": session["duration"], "reason": "crash_recovery",
                            "recovered_until": session["last_heartbeat"]})
        # The persisted duration is authoritative. No offline interval is added.
        run.total_play_seconds = sum(session["duration"] for session in run.sessions)

    def activate(self, run_id: str) -> Run:
        self.prepare_activation(run_id)
        try:
            return self.commit_activation(run_id)
        except (OSError, ValueError):
            self.cancel_activation()
            raise

    def prepare_activation(self, run_id: str) -> Run:
        """Stage a validated candidate; the selection is published after acknowledgement."""
        if self._activation_pending:
            self.cancel_activation()
        if self._run and self._run.run_id == run_id:
            self._activation_pending = self._activation_same = True
            return self.active_run
        selected = self.manager.load(run_id)
        if self._run:
            self._end_session("run_changed")
            self.flush(force=True)
        self._activation_previous = (self._run, self.last_saved_at, self.last_error)
        self._activation_pending = True
        self._activation_same = False
        self._run = selected
        self._previous_party.clear()
        self._last_observation = self._last_tick = None
        self._session_id = None
        self.dirty = False
        self._data_dirty = self._critical_dirty = False
        self._dirty_since = None
        self.last_saved_at = None
        try:
            self._recover()
            if selected.started_at is not None and selected.status == "active":
                self._event("run_resumed", "manual", {})
            self.flush(force=True)
        except (OSError, ValueError):
            self.cancel_activation()
            raise
        return self.active_run

    def commit_activation(self, run_id: str) -> Run:
        if not self._activation_pending or self._run is None or self._run.run_id != run_id:
            raise ValueError("La partie préparée ne correspond pas à celle demandée.")
        self.manager.set_active_id(run_id)
        self._activation_pending = False
        self._activation_previous = None
        self._activation_same = False
        return self.active_run

    def cancel_activation(self) -> None:
        if not self._activation_pending:
            return
        if not self._activation_same:
            self._run, self.last_saved_at, self.last_error = self._activation_previous
            self._previous_party.clear()
            self._last_observation = self._last_tick = self._session_id = None
            self.dirty = self._data_dirty = self._critical_dirty = False
            self._dirty_since = None
        self._activation_pending = False
        self._activation_previous = None
        self._activation_same = False

    def deactivate(self) -> None:
        self.cancel_activation()
        if self._run:
            self._end_session("tracking_stopped")
            self.flush(force=True)
        self.manager.set_active_id(None)
        self._run = None
        self._previous_party.clear()
        self._last_observation = self._last_tick = None

    def _session(self) -> dict | None:
        if not self._run or not self._session_id:
            return None
        return next(item for item in reversed(self._run.sessions) if item["session_id"] == self._session_id)

    def _start_session(self) -> None:
        run = self._require()
        stamp = self._now()
        if run.started_at is None:
            run.started_at = stamp
            run.status = "active"
            self._event("run_started", "automatic", {})
        elif run.status == "preparing":
            run.status = "active"
            self._event("status_changed", "automatic", {"previous": "preparing", "status": "active"})
        session = {"session_id": str(uuid4()), "started_at": stamp, "last_heartbeat": stamp,
                   "ended_at": None, "duration": 0.0}
        run.sessions.append(session)
        self._session_id = session["session_id"]
        self._last_tick = self._clock()
        run.last_played_at = stamp
        self._event("session_started", "automatic", {"session_id": self._session_id})
        self.flush(force=True)

    def _advance(self) -> None:
        session = self._session()
        if session is None:
            return
        now = self._clock()
        delta = now - self._last_tick
        if 0 <= delta <= self.observation_timeout:
            session["duration"] += delta
            session["last_heartbeat"] = self._now()
            self._run.total_play_seconds = sum(item["duration"] for item in self._run.sessions)
            self._run.last_played_at = session["last_heartbeat"]
            if delta:
                self._mark(heartbeat_only=True)
        self._last_tick = now

    def _end_session(self, reason: str) -> None:
        session = self._session()
        if session is not None:
            # Only time already covered by eligible heartbeats belongs to this session.
            session["ended_at"] = session["last_heartbeat"]
            self._event("session_ended", "system", {"session_id": session["session_id"],
                        "duration": session["duration"], "reason": reason})
            self._session_id = None
            self.flush(force=True)
        self._last_tick = None
        self._previous_party.clear()

    def _matches(self, game_id: str | None, game_code=None, region=None, revision=None) -> bool:
        run = self._run
        if run is None or game_id != run.game_id or run.status not in {"preparing", "active"}:
            return False
        for expected, actual in ((run.game_code, game_code), (run.region, region), (run.revision, revision)):
            if expected is not None and actual != expected:
                return False
        return True

    def heartbeat(self, emulator_running: bool, game_id: str | None, connected: bool = True) -> Run | None:
        if self._activation_pending:
            return self.active_run
        eligible = (self._run is not None and self._run.status in {"preparing", "active"}
                    and emulator_running is True and connected is True and game_id == self._run.game_id
                    and self._last_observation is not None
                    and 0 <= self._clock() - self._last_observation <= self.observation_timeout)
        if not eligible:
            self._end_session("unavailable")
            self._last_observation = None
        elif self._session_id:
            self._advance()
        self.flush()
        return self.active_run

    @staticmethod
    def _party(party: list[dict], generation: int) -> list[dict]:
        if not isinstance(party, (tuple, list)) or len(party) > (6 if generation == 5 else 24):
            raise ValueError("Équipe observée invalide.")
        result, slots = [], set()
        for index, item in enumerate(party):
            if not isinstance(item, dict):
                raise ValueError("Pokémon observé invalide.")
            value = deepcopy(item)
            hp = value.get("current_hp", value.get("hp"))
            value.update(slot=value.get("slot", index + 1), current_hp=hp, hp=hp)
            for key, lower, upper in (("species_id", 1, 649 if generation == 5 else 65535), ("slot", 1, 6 if generation == 5 else 24),
                                      ("level", 1, 100), ("max_hp", 1, 65535), ("hp", 0, 65535)):
                if type(value.get(key)) is not int or not lower <= value[key] <= upper:
                    raise ValueError(f"Observation Pokémon invalide : {key}.")
            if value["hp"] > value["max_hp"] or value["slot"] in slots:
                raise ValueError("PV ou emplacement Pokémon incohérent.")
            slots.add(value["slot"])
            for key in ("personality_id", "original_trainer_id"):
                if value.get(key) is not None and (type(value[key]) is not int or not 0 <= value[key] <= 0xffffffff):
                    raise ValueError("Identifiant Pokémon invalide.")
            validate_json_data(value)
            result.append(value)
        return sorted(result, key=lambda item: item["slot"])

    def observe(self, party: list[dict], zone: dict | str | None = None, *, game_id: str,
                game_code: str | None = None, region: str | None = None, revision: int | None = None,
                emulator_running: bool, valid: bool = True, connected: bool = True) -> Run | None:
        if self._activation_pending:
            return self.active_run
        if not (emulator_running is True and valid is True and connected is True
                and self._matches(game_id, game_code, region, revision)):
            self._end_session("identity_or_connection_unavailable")
            self._last_observation = None
            return self.active_run
        run = self._require()
        try:
            observed = self._party(party, run.generation)
            if zone is not None and not isinstance(zone, (dict, str)):
                raise ValueError("Zone observée invalide.")
            validate_json_data(zone)
        except (ValueError, TypeError):
            self._end_session("invalid_observation")
            self._last_observation = None
            raise
        now = self._clock()
        if self._last_observation is None or not 0 <= now - self._last_observation <= self.observation_timeout:
            self._end_session("observation_gap")
            self._previous_party.clear()
        self._last_observation = now
        if self._session_id is None:
            self._start_session()
        else:
            self._advance()
        if zone is not None and zone != run.current_zone:
            previous = deepcopy(run.current_zone)
            run.current_zone = deepcopy(zone)
            self._event("zone_changed", "automatic", {"previous": previous, "zone": zone})
        self._observe_party(observed)
        self.flush()
        return self.active_run

    def _dead(self, key: str | None) -> bool:
        return key is not None and any(item["pokemon_key"] == key and not item["corrected"] for item in self._run.deaths or [])

    def _review(self, pokemon: dict, reason: str) -> None:
        run = self._require()
        marker = pokemon.get("pokemon_key") or "weak:" + ":".join(str(pokemon.get(key)) for key in
                    ("slot", "species_id", "personality_id", "original_trainer_id"))
        if not any(item["marker"] == marker for item in run.pending_deaths):
            run.pending_deaths.append({"review_id": str(uuid4()), "marker": marker, "pokemon": deepcopy(pokemon),
                                       "reason": reason, "zone": deepcopy(run.current_zone), "timestamp": self._now()})
            self._mark()

    def _observe_party(self, observed: list[dict]) -> None:
        from app.core.pokemon_identity import pokemon_identity, documented_evolution
        run = self._require()
        keys = [pokemon_identity(item, run.generation) for item in observed]
        counts = Counter(key for key in keys if key is not None)
        current = {}
        permanent = {"nuzlocke", "permanent_death"} <= set(run.active_rules)
        for pokemon, key in zip(observed, keys):
            known = run.known_pokemon.get(key) if key else None
            reason = "Identité individuelle insuffisante : confirmation manuelle nécessaire."
            ambiguous = False
            if key is not None and counts[key] > 1:
                ambiguous = True
                reason = "Identifiants dupliqués dans l'équipe : confirmation manuelle nécessaire."
            if key is not None and known and known["species_id"] != pokemon["species_id"] and not documented_evolution(known["species_id"], pokemon["species_id"], run.generation):
                ambiguous = True
                reason = "Changement d'espèce hors évolution individuelle documentée : identité à vérifier manuellement."
            if key is not None and known and known.get("identity_ambiguous", False):
                ambiguous = True
                reason = known.get("identity_ambiguity_reason", "Identité déjà signalée ambiguë dans cette partie.")
            if ambiguous:
                changed = known is None or not known.get("identity_ambiguous", False) or known.get("identity_ambiguity_reason") != reason
                if known is None:
                    known = deepcopy(pokemon) | {"first_seen_at": self._now(), "last_seen_at": self._now(),
                             "species_history": [{"species_id": pokemon["species_id"], "timestamp": self._now()}],
                             "pokemon_key": key, "identity_confidence": "weak", "life_status": "unknown"}
                known.update(identity_ambiguous=True, identity_ambiguity_reason=reason, identity_confidence="weak")
                run.known_pokemon[key] = known
                if changed:
                    self._mark()
                key = None
            pokemon["pokemon_key"] = key
            pokemon["identity_confidence"] = "strong" if key else "weak"
            pokemon["life_status"] = "dead" if self._dead(key) else ("alive" if key and pokemon["hp"] > 0 else "unknown")
            previous = self._previous_party.get(key) if key else None
            transition = previous is not None and previous["hp"] > 0 and pokemon["hp"] == 0
            if transition:
                self._event("pokemon_fainted", "automatic", {"pokemon_key": key, "pokemon": pokemon, "zone": run.current_zone})
                if permanent and not self._dead(key):
                    self._mark_dead(pokemon, key, run.current_zone, self._now(), "", "automatic")
                    pokemon["life_status"] = "dead"
            elif pokemon["hp"] == 0 and permanent and not self._dead(key):
                self._review(pokemon, reason if key is None else "Première observation à 0 PV : transition non observée, confirmation nécessaire.")
            if key:
                current[key] = deepcopy(pokemon)
                if known is None:
                    known = {"first_seen_at": self._now(), "species_history": []}
                history = known["species_history"]
                if not history or history[-1]["species_id"] != pokemon["species_id"]:
                    history.append({"species_id": pokemon["species_id"], "timestamp": self._now()})
                known.update(deepcopy(pokemon), last_seen_at=self._now())
                run.known_pokemon[key] = known
        if observed != run.current_party:
            run.current_party = deepcopy(observed)
            self._event("party_changed", "automatic", {"party": observed})
        self._previous_party = current

    @staticmethod
    def _manual_pokemon(species_id=None, pokemon=None, *, generation=None) -> dict:
        if isinstance(pokemon, str):
            if not pokemon.strip() or len(pokemon) > 200:
                raise ValueError("Nom du Pokémon invalide.")
            data = {"name": pokemon.strip()}
        elif pokemon is None:
            data = {}
        elif isinstance(pokemon, dict):
            validate_json_data(pokemon)
            data = deepcopy(pokemon)
        else:
            raise ValueError("Pokémon manuel invalide.")
        if species_id is not None:
            if type(species_id) is not int or not 1 <= species_id <= 65535:
                raise ValueError("Espèce Pokémon invalide.")
            data["species_id"] = species_id
        if not data.get("species_id") and not data.get("name") and not data.get("species_name"):
            raise ValueError("Indiquez le Pokémon concerné.")
        _pokemon(data, generation=generation)
        return data

    @staticmethod
    def _text(value: str, *, empty: bool = True) -> str:
        if not isinstance(value, str) or len(value) > 10000 or (not empty and not value.strip()):
            raise ValueError("Texte de suivi invalide.")
        validate_json_data(value)
        return value.strip()

    def _manual_context(self, zone, date, note):
        run = self._require()
        zone = deepcopy(run.current_zone if zone is None else zone)
        if zone is not None and not isinstance(zone, (str, dict)):
            raise ValueError("Zone manuelle invalide.")
        validate_json_data(zone)
        date = date or self._now()
        validate_timestamp(date)
        return zone, date, self._text(note)

    def manual_capture(self, species_id=None, zone=None, date=None, note="", *, pokemon=None) -> Run:
        run = self._require()
        data = self._manual_pokemon(species_id, pokemon, generation=run.generation)
        zone, date, note = self._manual_context(zone, date, note)
        entry = {"capture_id": str(uuid4()), "pokemon": data, "zone": zone, "date": date, "note": note, "source": "manual"}
        if run.captures is None:
            run.captures = []
        run.captures.append(entry)
        self._event("manual_capture", "manual", entry)
        self.flush(force=True)
        return self.active_run

    def set_badges(self, count: int) -> Run:
        run = self._require()
        if type(count) is not int or not 0 <= count <= (8 if run.generation == 5 else 99):
            raise ValueError("Nombre de badges hors limites pour cette génération.")
        if count != run.badges:
            previous = run.badges
            run.badges = count
            self._event("manual_badge", "manual", {"previous": previous, "count": count})
            self.flush(force=True)
        return self.active_run

    def add_note(self, text: str) -> Run:
        entry = {"note_id": str(uuid4()), "text": self._text(text, empty=False), "timestamp": self._now()}
        self._require().notes.append(entry)
        self._event("note_added", "manual", entry)
        self.flush(force=True)
        return self.active_run

    def _mark_dead(self, pokemon: dict, key: str | None, zone, date, note: str, source: str,
                   review_id: str | None = None) -> dict | None:
        run = self._require()
        if self._dead(key):
            return None
        entry = {"death_id": str(uuid4()), "pokemon_key": key, "pokemon": deepcopy(pokemon),
                 "zone": deepcopy(zone), "date": date, "note": note, "source": source, "corrected": False}
        if review_id is not None:
            entry["review_id"] = review_id
        if run.deaths is None:
            run.deaths = []
        run.deaths.append(entry)
        self._critical_dirty = True
        if key in run.known_pokemon:
            run.known_pokemon[key]["life_status"] = "dead"
        if key:
            for member in run.current_party:
                if member.get("pokemon_key") == key:
                    member["life_status"] = "dead"
            for review in run.pending_deaths:
                if review["marker"] == key and not review.get("resolved", False):
                    review.update(resolved=True, death_id=entry["death_id"])
        self._event("pokemon_marked_dead" if source == "automatic" else "manual_death", source, entry)
        return entry

    def manual_death(self, pokemon_key=None, species_id=None, zone=None, date=None, note="", *, pokemon=None,
                     review_id: str | None = None) -> Run:
        run = self._require()
        review = None
        if review_id is not None:
            review = next((item for item in run.pending_deaths if item["review_id"] == review_id), None)
            if review is None or review.get("resolved", False):
                raise ValueError("Cette observation à confirmer est inconnue ou déjà traitée.")
            review_key = review["pokemon"].get("pokemon_key")
            if pokemon_key is not None and pokemon_key != review_key:
                raise ValueError("L'individu choisi ne correspond pas à l'observation à confirmer.")
            pokemon_key = review_key
            if pokemon is None and species_id is None:
                pokemon = review["pokemon"]
        if pokemon_key is not None:
            if not isinstance(pokemon_key, str) or pokemon_key not in run.known_pokemon:
                raise ValueError("Cet individu n'est pas connu dans cette partie.")
            data = deepcopy(run.known_pokemon[pokemon_key])
        else:
            data = self._manual_pokemon(species_id, pokemon, generation=run.generation)
        zone, date, note = self._manual_context(zone, date, note)
        entry = self._mark_dead(data, pokemon_key, zone, date, note, "manual", review_id=review_id)
        if review is not None:
            if entry is None:
                entry = next(item for item in run.deaths if item["pokemon_key"] == pokemon_key and not item["corrected"])
            review.update(resolved=True, death_id=entry["death_id"])
            self._mark()
        if entry is not None:
            self.flush(force=True)
        return self.active_run

    def correct_death(self, death_id: str, note: str = "", confirmed: bool = False) -> Run:
        if confirmed is not True:
            raise ValueError("Confirmez explicitement la correction de cette mort.")
        run = self._require()
        note = self._text(note)
        entry = next((item for item in run.deaths or [] if item["death_id"] == death_id), None)
        if entry is None:
            raise ValueError("Mort inconnue dans cette partie.")
        if not entry["corrected"]:
            entry.update(corrected=True, corrected_at=self._now(), correction_note=note)
            key = entry["pokemon_key"]
            if key in run.known_pokemon:
                run.known_pokemon[key]["life_status"] = "alive" if run.known_pokemon[key].get("hp", 0) > 0 else "unknown"
            for pokemon in run.current_party:
                if key is not None and pokemon.get("pokemon_key") == key:
                    pokemon["life_status"] = "alive" if pokemon["hp"] > 0 else "unknown"
            self._event("death_corrected", "manual", {"death_id": death_id, "note": note})
            self.flush(force=True)
        return self.active_run

    def set_status(self, status: str) -> Run:
        if not isinstance(status, str) or status not in RUN_STATUSES:
            raise ValueError("Statut de partie inconnu.")
        run = self._require()
        if status != run.status:
            if status not in {"active", "preparing"}:
                self._end_session("status_changed")
                self._last_observation = None
            previous = run.status
            run.status = status
            run.finished_at = self._now() if status == "finished" else None
            self._event("status_changed", "manual", {"previous": previous, "status": status})
            self.flush(force=True)
        return self.active_run

    def adjust_badges(self, delta: int) -> Run:
        run = self._require()
        if type(delta) is not int or delta not in {-1, 1}:
            raise ValueError("Variation de badges invalide.")
        if run.badges is None:
            raise ValueError("Renseignez d'abord le nombre de badges.")
        return self.set_badges(max(0, min(8 if run.generation == 5 else 99, run.badges + delta)))

    def update_launch_reference(self, profile: dict, rom_fingerprint: str | None = None) -> Run:
        run = self._require()
        if not isinstance(profile, dict):
            raise ValueError("Référence de lancement invalide.")
        validate_json_data(profile)
        candidate = deepcopy(run)
        candidate.launch_profile = deepcopy(profile)
        candidate.save_path = profile.get("save_path") or None
        if rom_fingerprint is not None:
            candidate.rom_fingerprint = rom_fingerprint
        candidate.to_dict()
        self._run = candidate
        self._mark()
        self.flush(force=True)
        return self.active_run

    def record_backup(self, payload: dict) -> Run:
        if not isinstance(payload, dict):
            raise ValueError("Référence de backup invalide.")
        validate_json_data(payload)
        self._event("backup_created", "system", payload)
        self.flush(force=True)
        return self.active_run

    def flush(self, force: bool = False) -> bool:
        if self._run is None or not self.dirty:
            return False
        now = self._clock()
        if (not force and not self._critical_dirty
                and (not self._data_dirty or now - self._dirty_since < self.debounce_seconds)
                and now - self._last_save < self.heartbeat_seconds):
            return False
        try:
            self.manager.save(self._run)
        except (OSError, ValueError) as exc:
            self.last_error = str(exc)
            raise
        self.dirty = False
        self._data_dirty = self._critical_dirty = False
        self._dirty_since = None
        self._last_save = now
        self.last_saved_at = self._now()
        self.last_error = None
        return True

    def close(self) -> None:
        self.cancel_activation()
        self._end_session("pce_closed")
        self.flush(force=True)
