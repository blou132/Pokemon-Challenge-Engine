"""Replay explicit manual encounters without interpreting party or RAM changes."""

from app.core.manual_rule_event import EVENT_TYPE, active_declarations, declaration_positions, ENCOUNTER_OUTCOMES


def encounter_checks(run, zone_key, check):
    active = active_declarations(run.history)
    positions = declaration_positions(run.history)
    captures = {entry["capture_id"]: entry for entry in run.captures or []}
    located_captures = set()
    timeline = []
    for index, event in enumerate(run.history):
        payload = event.get("payload", {})
        if event["type"] == EVENT_TYPE:
            if event["event_id"] in active and payload["kind"] == "wild_encounter":
                timeline.append((positions[event["event_id"]], event, True))
        elif event["type"] == "manual_capture" and event["source"] == "manual" and payload.get("capture_id") in captures:
            capture_id = payload["capture_id"]
            if capture_id not in located_captures:
                timeline.append((index, dict(event, payload=captures[capture_id]), False))
                located_captures.add(capture_id)
    captured, used, uncertain = set(), {}, set()
    # Some old files contain captures without a journal position. They cannot
    # prove a prior capture for a later reroll, or an available first encounter.
    uncertain.update(zone_key(entry.get("zone")) for key, entry in captures.items() if key not in located_captures)
    for _, event, encounter in sorted(timeline, key=lambda row: row[0]):
        payload = event["payload"]
        zone = zone_key(payload.get("zone"))
        if not encounter:
            species = payload.get("pokemon", {}).get("species_id")
            if zone in used and "nuzlocke" in run.active_rules:
                yield check("nuzlocke", "review", "manual",
                    "Capture déclarée dans une zone déjà consommée ; type de rencontre non renseigné. Vérifier la convention des rencontres spéciales. Aucun événement automatique.",
                    payload.get("pokemon"), event["timestamp"])
            if zone is not None:
                uncertain.add(zone)  # An old capture lacks a documented encounter kind.
            if type(species) is int:
                captured.add(species)
            continue
        details = payload["details"]
        species, outcome = details["species_id"], details["outcome"]
        pokemon = {"species_id": species}
        stamp = event["timestamp"]
        if details["encounter_kind"] != "wild_standard":
            if "nuzlocke" in run.active_rules:
                yield check("nuzlocke", "review", "manual",
                    "Rencontre spéciale déclarée : exclue de la première rencontre sauvage ordinaire. Appliquer votre convention séparément.",
                    pokemon, stamp)
        elif outcome == "duplicate_ignored":
            verified = species in captured
            yield check("species_clause", "compliant" if verified else "unknown", "manual",
                "Doublon ignoré déclaré ; espèce déjà capturée dans le journal. Aucun droit supplémentaire consommé ; une zone déjà utilisée ne se rouvre pas."
                if verified else "Doublon ignoré déclaré, mais aucune capture antérieure de cette espèce ne le justifie. Droit de capture inconnu.",
                pokemon, stamp)
            if not verified and zone is not None:
                uncertain.add(zone)
        elif "nuzlocke" in run.active_rules:
            if zone is None:
                yield check("nuzlocke", "unknown", "manual", "Rencontre déclarée sans zone identifiable : droit de capture inconnu.", pokemon, stamp)
            elif zone in used:
                yield check("nuzlocke", "violation" if outcome == "captured" else "review", "manual",
                    "Zone déjà consommée par une rencontre antérieure déclarée : " + ENCOUNTER_OUTCOMES[outcome] + ".", pokemon, stamp)
            elif zone in uncertain:
                yield check("nuzlocke", "unknown", "manual", "Historique antérieur incomplet dans cette zone : première rencontre non vérifiable.", pokemon, stamp)
            else:
                yield check("nuzlocke", "review", "manual",
                    "Première rencontre du journal déclarée : " + ENCOUNTER_OUTCOMES[outcome] + ". Zone consommée ; les rencontres non déclarées restent inconnues.", pokemon, stamp)
            if zone is not None:
                used[zone] = event["event_id"]
        if outcome == "captured":
            captured.add(species)
