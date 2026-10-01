"""Pure encounter state machine. It never reads or writes emulator memory."""

from copy import deepcopy

from app.events.game_event import GameEvent, GameObservation, stable_id
from app.models.profile import Profile, validate_progress


class NuzlockeTracker:
    """Apply only documented observations to one profile, without I/O."""

    def consume(self, profile: Profile, observation: GameObservation, *, session_id: str,
                sequence: int, timestamp: int | None = None) -> list[GameEvent]:
        if "nuzlocke" not in profile.challenge.active_rules:
            return []
        if not session_id or type(sequence) is not int or sequence < 1:
            raise ValueError("Identité d'observation absente ou invalide.")
        profile.progress = validate_progress(profile.progress)
        tracking = profile.progress["nuzlocke"]
        if sequence <= tracking["source_cursors"].get(session_id, 0):
            return []
        tracking["source_cursors"][session_id] = sequence
        events: list[GameEvent] = []
        source = stable_id(session_id, sequence)

        def emit(name: str, key: str, encounter: dict | None = None, result: str | None = None) -> None:
            encounter = encounter or {}
            event = GameEvent(stable_id(profile.id, name, key), name, timestamp,
                              encounter.get("zone_id", observation.capture_zone_id), observation.map_id,
                              encounter.get("battle_id", observation.battle_id),
                              encounter.get("species_id", observation.species_id),
                              encounter.get("level", observation.level), result)
            if not any(item.get("id") == event.id for item in profile.history):
                profile.history.append(event.to_dict())
                events.append(event)

        zone_id = observation.capture_zone_id
        previous_zone = tracking["current_zone_id"]
        tracking["current_map_id"] = observation.map_id
        tracking["current_zone_id"] = zone_id
        zone = None
        if zone_id is not None:
            zone = tracking["zones"].setdefault(zone_id, {"name": observation.zone_name, "used": False,
                       "status": "unused", "first_encounter": None, "last_ignored": None})
            if observation.zone_name is not None:
                zone["name"] = observation.zone_name
            if previous_zone != zone_id:
                emit("zone_entered", source)

        def finish(result: str) -> None:
            active = tracking["active_encounter"]
            if active is None:
                return
            active["result"] = result
            origin = tracking["zones"][active["zone_id"]]
            origin["used"] = True
            origin["status"] = "captured" if result == "captured" else "failed"
            origin["first_encounter"] = deepcopy(active)
            tracking["seen_battles"][active["id"]] = result
            name = {"captured": "capture_success", "fainted": "wild_fainted",
                    "escaped": "wild_escaped", "player_fled": "player_fled",
                    "battle_ended_unknown": "battle_ended_unknown"}[result]
            emit(name, active["id"], active, result)
            if result == "captured" and active["species_id"] not in tracking["captured_species"]:
                tracking["captured_species"].append(active["species_id"])
            tracking["active_encounter"] = None

        active = tracking["active_encounter"]
        same_battle = active is not None and observation.battle_id == active["battle_id"]
        if active is not None:
            contradictory = (observation.battle_type not in (None, "unknown", "wild")
                             or observation.encounter_kind not in (None, "unknown", "wild_standard"))
            if same_battle and contradictory:
                finish("battle_ended_unknown")
            elif same_battle and observation.outcome is not None:
                finish(observation.outcome)
            elif same_battle and observation.battle_active is True and observation.hp == 0:
                finish("fainted")
            elif observation.battle_active is False:
                # An explicit ended battle has an unknown outcome unless positively identified above.
                finish("battle_ended_unknown")
            elif observation.battle_active is True and observation.battle_id is not None and not same_battle:
                finish("battle_ended_unknown")
            else:
                # Null readings and disconnects never imply the battle ended.
                return events

        if observation.battle_active is not True or observation.battle_id is None:
            return events
        if zone is None or observation.species_id is None:
            return events
        encounter_id = stable_id(profile.challenge.game_id, observation.battle_id)
        if encounter_id in tracking["seen_battles"]:
            return events
        encounter = {"id": encounter_id, "battle_id": observation.battle_id, "zone_id": zone_id,
                     "species_id": observation.species_id, "level": observation.level,
                     "result": None, "timestamp": timestamp}

        def ignore(result: str) -> None:
            encounter["result"] = result
            tracking["seen_battles"][encounter_id] = result
            emit(result, encounter_id, encounter, result)

        if observation.battle_type is None or observation.battle_type == "unknown":
            return events  # A later, reliable observation may still identify this battle.
        if observation.battle_type != "wild":
            ignore("invalid_encounter")
            return events
        if observation.encounter_kind in (None, "unknown"):
            return events
        if observation.encounter_kind != "wild_standard":
            ignore("special_encounter_ignored")
            return events
        if zone["used"]:
            ignore("zone_already_used")
            return events
        captured = set(tracking["captured_species"])
        captured.update(item["species_id"] for item in profile.progress["captures"]
                        if type(item.get("species_id")) is int and 1 <= item["species_id"] <= 649)
        if "species_clause" in profile.challenge.active_rules and observation.species_id in captured:
            ignore("duplicate_ignored")
            zone["status"] = "ignored_by_clause"
            zone["last_ignored"] = encounter
            return events
        zone["status"] = "encounter_started"
        zone["first_encounter"] = deepcopy(encounter)
        tracking["active_encounter"] = encounter
        emit("wild_encounter_started", encounter_id, encounter)
        if observation.outcome is not None:
            finish(observation.outcome)
        elif observation.hp == 0:
            finish("fainted")
        return events
