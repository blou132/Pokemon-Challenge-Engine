"""Explicit declarations for actions no verified RAM reader currently exposes."""

from dataclasses import dataclass


EVENT_TYPE = "manual_rule_event"


@dataclass(frozen=True)
class DeclaredAction:
    label: str
    rules: tuple[str, ...]
    violation: bool = True


ACTIONS = {
    "battle_bag_item": DeclaredAction("Objet du sac hors Poké Ball, en combat", ("no_items",)),
    "battle_healing_item": DeclaredAction("Objet de soin volontaire, en combat", ("no_items", "no_healing")),
    "field_healing_item": DeclaredAction("Objet de soin volontaire, hors combat", ("no_healing",)),
    "healing_move": DeclaredAction("Capacité de soin volontaire", ("no_healing",)),
    "pokemon_center": DeclaredAction("Service de soin d'un Centre Pokémon", ("no_pokemon_center",)),
    "unauthorized_battler": DeclaredAction("Combat avec un autre individu que celui autorisé", ("solo_run", "starter_only")),
    "non_shiny_battler": DeclaredAction("Combat avec un Pokémon non shiny", ("shiny_only",)),
    "pokemon_evolved": DeclaredAction("Évolution effectuée", ("no_evolution",)),
    "wild_encounter": DeclaredAction("Rencontre / résultat / capture", ("nuzlocke", "species_clause", "catch_limit"), False),
}
MANUAL_RULES = frozenset(rule for action in ACTIONS.values() for rule in action.rules)
ENCOUNTER_OUTCOMES = {
    "captured": "Capturé", "fainted": "Adversaire K.O.", "player_fled": "Fuite du joueur",
    "escaped": "Fuite de l'adversaire", "unknown": "Résultat inconnu",
    "duplicate_ignored": "Doublon ignoré (Species Clause)",
}
ENCOUNTER_KINDS = {"wild_standard": "Rencontre sauvage ordinaire", "wild_special": "Rencontre spéciale",
                   "static": "Pokémon statique", "gift": "Cadeau", "egg": "Œuf", "scripted": "Scénario"}


def available_actions(active_rules):
    return {kind: action for kind, action in ACTIONS.items() if set(action.rules).intersection(active_rules)}


def active_declarations(history):
    """Replay the append-only correction chain, without editing older entries."""
    active = {}
    for event in history:
        if event.get("type") != EVENT_TYPE:
            continue
        payload = event["payload"]
        target = payload.get("corrects_event_id")
        if target is not None:
            active.pop(target, None)
        if payload.get("kind") is not None:
            active[event["event_id"]] = event
    return active


def declaration_positions(history):
    """Corrections keep the original action's position, not the correction date."""
    positions = {}
    for index, event in enumerate(history):
        if event.get("type") == EVENT_TYPE:
            target = event["payload"].get("corrects_event_id")
            positions[event["event_id"]] = positions.get(target, index)
    return positions


def ordered_declarations(history):
    positions = declaration_positions(history)
    return sorted(active_declarations(history).values(), key=lambda event: positions[event["event_id"]])


def capture_records(run):
    """Manual captures plus captures explicitly declared in the encounter journal."""
    positions = declaration_positions(run.history)
    capture_positions = {event["payload"].get("capture_id"): index
                         for index, event in enumerate(run.history)
                         if event["type"] == "manual_capture" and event["source"] == "manual"}
    records = [(capture_positions.get(record["capture_id"], -1), record) for record in run.captures or []]
    for event in ordered_declarations(run.history):
        payload = event["payload"]
        details = payload.get("details", {})
        if payload["kind"] == "wild_encounter" and details["outcome"] == "captured":
            records.append((positions[event["event_id"]], {
                "capture_id": event["event_id"], "pokemon": {"species_id": details["species_id"]},
                "zone": payload["zone"], "date": event["timestamp"], "note": payload["note"], "source": "manual",
                "encounter_kind": details["encounter_kind"],
            }))
    return [record for _, record in sorted(records, key=lambda row: row[0])]


def validate_declaration(payload, active_rules, active):
    """Validate before mutation, and again when a run is loaded from disk."""
    required = {"kind", "note", "zone", "corrects_event_id"}
    if not isinstance(payload, dict) or set(payload) not in (required, required | {"details"}):
        raise ValueError("Déclaration d'action incomplète.")
    kind, target, note = payload["kind"], payload["corrects_event_id"], payload["note"]
    if target is not None and (not isinstance(target, str) or target not in active):
        raise ValueError("La déclaration a déjà été corrigée ou n'appartient pas à cette partie. Rouvrez le formulaire.")
    if kind is None:
        if target is None:
            raise ValueError("Choisissez une déclaration existante à retirer.")
    elif not isinstance(kind, str) or kind not in available_actions(active_rules):
        raise ValueError("Cette action ne concerne aucune règle active de la partie.")
    if not isinstance(note, str) or len(note) > 10000:
        raise ValueError("Note de déclaration invalide ou trop longue.")
    if target is not None and not note.strip():
        raise ValueError("Indiquez la raison de cette correction.")
    if payload["zone"] is not None and not isinstance(payload["zone"], (str, dict)):
        raise ValueError("Zone de déclaration invalide.")
    details = payload.get("details")
    if kind == "wild_encounter":
        if not isinstance(details, dict) or set(details) != {"species_id", "outcome", "encounter_kind"}:
            raise ValueError("Renseignez l'espèce, le type de rencontre et son résultat.")
        if type(details["species_id"]) is not int or not 1 <= details["species_id"] <= 649:
            raise ValueError("Espèce de rencontre invalide (1 à 649).")
        if not isinstance(details["outcome"], str) or details["outcome"] not in ENCOUNTER_OUTCOMES:
            raise ValueError("Résultat de rencontre invalide.")
        if not isinstance(details["encounter_kind"], str) or details["encounter_kind"] not in ENCOUNTER_KINDS:
            raise ValueError("Type de rencontre invalide.")
        if details["outcome"] == "duplicate_ignored" and (
                "species_clause" not in active_rules or details["encounter_kind"] != "wild_standard"):
            raise ValueError("Ignorer un doublon exige Species Clause et une rencontre sauvage ordinaire.")
    elif details is not None:
        raise ValueError("Les détails de rencontre exigent une déclaration de rencontre.")
