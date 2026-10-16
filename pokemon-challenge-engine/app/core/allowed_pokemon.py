"""Manual individual designation for a run, separate from its immutable rules."""

from collections import Counter

from app.core.pokemon_identity import pokemon_identity


DESIGNATION_EVENT = "allowed_pokemon_changed"


def designation_purpose(active_rules):
    if "starter_only" in active_rules:
        return "starter"
    if "solo_run" in active_rules:
        return "solo"
    return None


def latest_designation(run):
    return next((event for event in reversed(run.history)
                 if isinstance(event, dict) and event.get("type") == DESIGNATION_EVENT), None)


def eligible_individuals(run):
    """Only the last team's strong, registered, non-colliding observations.

    A known individual with stale identifiers cannot override a weak current
    observation, nor can a species or slot become an individual identifier.
    """
    from app.models.run import _pokemon

    counts = Counter(pokemon_identity(item, run.generation) for item in run.current_party)
    result = {}
    for pokemon in run.current_party:
        key = pokemon_identity(pokemon, run.generation)
        if key is None or counts[key] != 1 or pokemon.get("pokemon_key") != key:
            continue
        known = run.known_pokemon.get(key)
        if (not known or known.get("identity_ambiguous") or pokemon.get("identity_ambiguous")
                or known.get("identity_confidence") != "strong"
                or pokemon.get("identity_confidence") != "strong"
                or known.get("pokemon_key") != key
                or known.get("species_id") != pokemon.get("species_id")
                or known.get("form") != pokemon.get("form")):
            continue
        history = known.get("species_history")
        if (not isinstance(history, list) or not history or not isinstance(history[-1], dict)
                or history[-1].get("species_id") != pokemon.get("species_id")):
            continue
        try:
            _pokemon(pokemon, observed=True, generation=run.generation)
            _pokemon(known, observed=True, generation=run.generation)
        except ValueError:
            continue
        result[key] = pokemon
    return result
