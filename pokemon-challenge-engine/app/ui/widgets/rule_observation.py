"""Shared presentation of checks; all decisions belong to the domain engine."""
from app.core.rule_observation import evaluate_rules
from app.core.shiny import shiny_status
from app.ui.widgets.nuzlocke import species_name


CAPABILITY_LABELS = {"automatic": "Suivi automatique", "partial": "Suivi partiel",
                     "unavailable": "Non disponible", "configured": "Configuré"}
STATE_LABELS = {"compliant": "Conforme", "violation": "Non conforme", "unknown": "Non vérifiable", "review": "À vérifier"}
SCOPE_LABELS = {"party": "Équipe", "known": "Dernière observation connue", "history": "Historique", "manual": "Déclaration manuelle", "rom": "ROM de cette partie"}


def shiny_label(pokemon, generation=5):
    state = shiny_status(pokemon, generation)
    return "Shiny : inconnu" if state is None else "★ Shiny" if state else "Normal · non shiny"


def rule_observation_text(run, catalog, *, detailed=False, transformation=None):
    if not run.active_rules:
        return "Partie classique · aucun contrôle de challenge."
    sections = ["Contrôles des dernières observations enregistrées.\nLa présence dans l'équipe ne prouve pas l'utilisation en combat."]
    for evaluation in evaluate_rules(run, include_history=detailed, transformation=transformation):
        rule = catalog.rules.get(evaluation.rule_id)
        title = rule.name if rule else evaluation.rule_id
        lines = [f"{title} · {CAPABILITY_LABELS[evaluation.capability.level]}"]
        if detailed:
            lines.append(evaluation.capability.explanation)
        counts = {state: sum(item.state == state for item in evaluation.checks if item.scope != "history") for state in STATE_LABELS}
        if any(counts.values()):
            lines.append(" · ".join(f"{count} {STATE_LABELS[state].lower()}" for state, count in counts.items() if count))
        else:
            lines.append("Aucune conclusion sur la conformité de la partie.")
        historical = [item for item in evaluation.checks if item.scope == "history"]
        if historical:
            lines.append(f"Historique : {len(historical)} observation(s) à consulter dans les règles de la partie.")
        items = evaluation.checks if detailed else [item for item in evaluation.checks if item.scope == "rom" or item.state in {"violation", "review", "unknown"} and item.scope == "party"]
        for item in items:
            name = species_name(item.species_id) + " · " if item.species_id is not None else ""
            context = SCOPE_LABELS[item.scope]
            if item.timestamp and detailed:
                context += " · " + item.timestamp
            lines.append(f"{context} · {name}{item.message}")
        if not detailed and evaluation.capability.level in {"partial", "unavailable", "configured"}:
            lines.append(evaluation.capability.explanation)
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
