"""Read-only evaluations of run evidence, never deductions of battle actions.

Results are reproducible from the existing, atomically saved run observations.
No second writer or hidden mutation of the immutable challenge is needed.
"""
from dataclasses import dataclass

from app.core.gen5_species import is_unevolved, species_types
from app.core.monotype import GEN5_TYPE_IDS, matches_type
from app.core.pokemon_identity import documented_evolution, pokemon_identity
from app.core.shiny import shiny_status
from app.models.run import _pokemon


@dataclass(frozen=True)
class RuleCapability:
    level: str
    explanation: str


CAPABILITIES = {
    "nuzlocke": RuleCapability("partial", "Captures déclarées et limite par zone suivies. Première rencontre, fuite et capture vers le PC non observables automatiquement."),
    "permanent_death": RuleCapability("partial", "K.O. suivi si le même individu passe de PV positifs à zéro. Première observation à zéro ou identité ambiguë : confirmation requise. Aucun blocage dans le jeu."),
    "species_clause": RuleCapability("partial", "Doublons d'espèce dans les captures déclarées. Rencontres et droit de relance non vérifiables automatiquement."),
    "level_cap": RuleCapability("automatic", "Niveau observé comparé au plafond configuré. Aucune déduction d'utilisation en combat."),
    "monotype": RuleCapability("automatic", "Types de l'espèce et de la forme comparés à la convention choisie. Effets temporaires de combat non observés."),
    "no_items": RuleCapability("unavailable", "L'utilisation d'un objet du sac en combat n'est pas lue de façon fiable. Aucun événement n'est déduit des PV."),
    "no_healing": RuleCapability("unavailable", "Une hausse de PV ne prouve pas la cause du soin. Aucune violation automatique."),
    "no_pokemon_center": RuleCapability("unavailable", "La présence dans un Centre Pokémon ne prouve pas l'utilisation de son service de soin."),
    "no_evolution": RuleCapability("partial", "Changement d'espèce compatible avec une évolution documentée pour un individu identifié. Aucun blocage des évolutions dans le jeu."),
    "solo_run": RuleCapability("partial", "Taille de l'équipe observée. L'individu autorisé et son utilisation en combat restent à confirmer."),
    "shiny_only": RuleCapability("partial", "Statut shiny calculé avec PID et identifiants du dresseur d'origine. Présence dans l'équipe vérifiée ; utilisation en combat non observée. Taux d'apparition inchangé."),
    "randomizer": RuleCapability("configured", "La sélection de cette règle ne prouve pas qu'une transformation a été appliquée à la ROM."),
    "catch_limit": RuleCapability("partial", "Limite comparée aux captures déclarées par zone identifiée. Captures non déclarées et envois au PC non observés."),
    "starter_only": RuleCapability("unavailable", "L'espèce et la place dans l'équipe ne prouvent pas qu'un individu est le starter reçu. Identité et utilisation à confirmer."),
    "unevolved": RuleCapability("automatic", "Convention : espèce sans stade évolutif antérieur, y compris celles qui n'évoluent jamais. Pas de déduction sur l'histoire de cet individu."),
}


@dataclass(frozen=True)
class RuleCheck:
    rule_id: str
    state: str
    scope: str
    message: str
    species_id: int | None = None
    slot: int | None = None
    pokemon_key: str | None = None
    timestamp: str | None = None


@dataclass(frozen=True)
class RuleEvaluation:
    rule_id: str
    capability: RuleCapability
    checks: tuple[RuleCheck, ...]


class RunPokemonData:
    """Pure lookups bound to the provider's verified game/ROM/configuration.

    The provider owns disk/hash validation. A stale or absent context never
    authorizes vanilla assumptions for a Randomizer adventure.
    """

    def __init__(self, run, transformation=None):
        self.run = run
        self.randomized = "randomizer" in run.active_rules
        self.verified = False
        self.categories = frozenset()
        self.rows = {}
        self.parents = None
        self.identity_graph = None
        config = run.rules_snapshot.get("settings", {}).get("rom_transformation")
        if (not self.randomized or run.generation != 5 or not isinstance(config, dict)
                or not isinstance(transformation, dict) or transformation.get("source") != "verified-derived-rom"
                or transformation.get("game_id") != run.game_id
                or not run.rom_fingerprint or transformation.get("rom_sha256") != run.rom_fingerprint):
            return
        categories = transformation.get("categories")
        requested = config.get("categories")
        if (config.get("kind") != "zx" or not isinstance(categories, list) or not categories
                or any(not isinstance(item, str) for item in categories)
                or len(set(categories)) != len(categories) or not isinstance(requested, list)
                or any(not isinstance(item, str) for item in requested) or set(categories) != set(requested)):
            return
        rows = transformation.get("pokemon")
        if not isinstance(rows, list):
            return
        parents, graph = set(), {}
        identity_complete = True
        for row in rows:
            if not isinstance(row, dict):
                return
            species, form, types = row.get("species_id"), row.get("form"), row.get("types")
            edges, identity_edges = row.get("evolutions"), row.get("identity_evolutions")
            if (type(species) is not int or not 1 <= species <= 649 or type(form) is not int or not 0 <= form <= 31
                    or (species, form) in self.rows or not isinstance(types, list) or not 1 <= len(types) <= 2
                    or any(not isinstance(item, str) or item not in GEN5_TYPE_IDS for item in types)
                    or len(set(types)) != len(types) or not isinstance(edges, list)
                    or any(type(item) is not int or not 1 <= item <= 649 for item in edges)):
                self.rows = {}
                return
            self.rows[species, form] = tuple(types)
            parents.update(edges)
            if (not isinstance(identity_edges, list)
                    or any(type(item) is not int or item not in edges for item in identity_edges)):
                identity_complete = False
            elif form == 0:
                # Species-only history cannot prove an evolution tied to an
                # alternate form; do not merge those branches into the base.
                graph[species] = frozenset(identity_edges)
        if any((species, 0) not in self.rows for species in range(1, 650)):
            self.rows = {}
            return
        self.categories = frozenset(categories)
        self.parents = parents
        self.identity_graph = graph if identity_complete else None
        self.verified = True

    def types(self, species, form=None):
        if not self.randomized or self.verified and "types" not in self.categories:
            return species_types(species, self.run.game_id, form)
        if not self.verified or type(species) is not int or type(form) is not int:
            return None
        return self.rows.get((species, form))

    def unevolved(self, species):
        if not self.randomized or self.verified and "evolutions" not in self.categories:
            return is_unevolved(species, self.run.game_id)
        if not self.verified or type(species) is not int or not 1 <= species <= 649:
            return None
        return species not in self.parents

    @staticmethod
    def _reachable(graph, first, second):
        waiting, seen = [first], set()
        while waiting:
            species = waiting.pop()
            if species in seen:
                continue
            seen.add(species)
            targets = graph.get(species, ())
            if second in targets:
                return True
            waiting.extend(targets)
        return False

    def evolution(self, first, second, first_form=None, second_form=None):
        if not self.randomized or self.verified and "evolutions" not in self.categories:
            return documented_evolution(first, second, self.run.generation)
        if not self.verified or self.identity_graph is None:
            return None
        # The extracted edges identify target species, not their alternate
        # forms. Old species-only histories cannot prove this relationship.
        if type(first_form) is not int or first_form != 0 or type(second_form) is not int or second_form != 0:
            return None
        if any(type(item) is not int or not 1 <= item <= 649 for item in (first, second)) or first == second:
            return False
        return (self._reachable(self.identity_graph, first, second)
                and not self._reachable(self.identity_graph, second, first))


def _parameters(run, rule):
    value = run.rules_snapshot.get("settings", {}).get("rule_parameters", {}).get(rule)
    return value if isinstance(value, dict) else {}


def level_cap(run) -> int | None:
    value = _parameters(run, "level_cap").get("max_level")
    return value if "level_cap" in run.active_rules and type(value) is int and 1 <= value <= 100 else None


def _check(rule, state, scope, message, pokemon=None, timestamp=None):
    pokemon = pokemon or {}
    return RuleCheck(rule, state, scope, message, pokemon.get("species_id"), pokemon.get("slot"),
                     pokemon.get("pokemon_key"), timestamp)


def _state(value):
    return "unknown" if value is None else "compliant" if value else "violation"


def _zone_key(zone):
    # Only explicit stable identifiers or exact manual names; no fuzzy map merge.
    if isinstance(zone, str) and zone.strip():
        return ("name", zone.strip())
    if isinstance(zone, dict):
        for key in ("capture_zone_id", "zone_id"):
            if isinstance(zone.get(key), str) and zone[key]:
                return (key, zone[key])
    return None


def _pokemon_checks(run, pokemon, scope, data, *, timestamp=None):
    active = run.active_rules
    species = pokemon.get("species_id")
    if "shiny_only" in active:
        shiny = shiny_status(pokemon, run.generation)
        message = ("Statut shiny inconnu : identité incomplète." if shiny is None else
                   "Shiny : autorisé selon la convention de présence." if shiny else
                   "Pokémon normal présent : non conforme à Shiny Only. Utilisation en combat inconnue.")
        yield _check("shiny_only", _state(shiny), scope, message, pokemon, timestamp)
    if "level_cap" in active:
        cap, level = level_cap(run), pokemon.get("level")
        valid = None if cap is None or type(level) is not int or not 1 <= level <= 100 else level <= cap
        message = ("Plafond ou niveau non renseigné." if valid is None else
                   f"Niveau {level} / plafond {cap}" + (" : dépassement observé." if not valid else " : conforme."))
        yield _check("level_cap", _state(valid), scope, message, pokemon, timestamp)
    if "monotype" in active:
        config = run.rules_snapshot.get("monotype")
        types = data.types(species, pokemon.get("form")) if run.generation == 5 else None
        valid = matches_type(list(types), config["type_id"], config["mode"]) if config and types else None
        message = ("Types non vérifiables : espèce, forme ou types de la ROM inconnus." if valid is None else
                   f"Monotype {config['type_id']} ({config['mode']}) : " + ("conforme." if valid else "non conforme."))
        yield _check("monotype", _state(valid), scope, message, pokemon, timestamp)
    if "unevolved" in active:
        valid = data.unevolved(species) if run.generation == 5 else None
        message = ("Stade non vérifiable pour cette ROM." if valid is None else
                   "Espèce au stade initial : conforme." if valid else "Espèce possédant un stade antérieur : non conforme.")
        yield _check("unevolved", _state(valid), scope, message, pokemon, timestamp)
    if "permanent_death" in active:
        key = pokemon.get("pokemon_key")
        dead = bool(key) and any(entry.get("pokemon_key") == key and not entry.get("corrected") for entry in run.deaths or [])
        if dead and scope == "party":
            yield _check("permanent_death", "violation", scope,
                         "Individu déclaré mort dans PCE, encore présent dans cette observation. Utilisation en combat inconnue.", pokemon, timestamp)


def evaluate_rules(run, *, include_history=False, transformation=None) -> tuple[RuleEvaluation, ...]:
    """Evaluate saved evidence; an absent check never means global compliance.

The normal view checks current team and latest known individuals. The detailed
view also retains past team violations, deduplicated by individual and message.
Neither a team addition nor a disappearance is interpreted as a capture.
"""
    checks = {rule: [] for rule in run.active_rules}
    data = RunPokemonData(run, transformation)
    if "randomizer" in checks:
        checks["randomizer"].append(_check("randomizer", "compliant" if data.verified else "unknown", "rom",
            "ROM dérivée vérifiée ; catégories : " + ", ".join(sorted(data.categories)) + "."
            if data.verified else "Transformation ROM non vérifiable pour cette partie : données effectives indisponibles."))
    if ("no_evolution" in checks and data.randomized
            and (not data.verified or "evolutions" in data.categories and data.identity_graph is None)):
        checks["no_evolution"].append(_check("no_evolution", "unknown", "rom",
            "Évolutions individuelles non vérifiables : graphe effectif avec distinction des créations indisponible."))
    current_keys = set()
    for pokemon in run.current_party:
        current_keys.add(pokemon.get("pokemon_key"))
        for item in _pokemon_checks(run, pokemon, "party", data):
            checks[item.rule_id].append(item)
    for key, pokemon in run.known_pokemon.items():
        if key not in current_keys:
            for item in _pokemon_checks(run, pokemon, "known", data, timestamp=pokemon.get("last_seen_at")):
                checks[item.rule_id].append(item)
        if "no_evolution" in checks:
            history = pokemon.get("species_history", [])
            proven_identity = (not pokemon.get("identity_ambiguous") and pokemon.get("identity_confidence") == "strong"
                               and pokemon_identity(pokemon, run.generation) == key)
            for previous, current in zip(history, history[1:]):
                relation = data.evolution(previous.get("species_id"), current.get("species_id"),
                                          previous.get("form"), current.get("form"))
                proven = proven_identity and relation is True
                if proven:
                    checks["no_evolution"].append(_check("no_evolution", "violation", "history",
                        f"Évolution observée entre les espèces {previous['species_id']} et {current['species_id']} pour le même individu.",
                        pokemon, current.get("timestamp")))
                elif proven_identity and relation is None:
                    checks["no_evolution"].append(_check("no_evolution", "unknown", "history",
                        "Changement d'espèce historique : forme ou graphe individuel effectif non vérifiable.",
                        pokemon, current.get("timestamp")))
    if "solo_run" in checks and run.current_party:
        checks["solo_run"].append(_check("solo_run", "review" if len(run.current_party) > 1 else "unknown", "party",
            f"{len(run.current_party)} Pokémon présent(s). Cela ne prouve pas lesquels sont utilisés en combat."))
    counts, species_seen = {}, set()
    for entry in run.captures or []:
        pokemon = entry.get("pokemon", {})
        zone = _zone_key(entry.get("zone"))
        if zone is not None:
            counts[zone] = counts.get(zone, 0) + 1
        for rule in ("nuzlocke", "catch_limit"):
            if rule not in checks:
                continue
            limit = 1 if rule == "nuzlocke" else _parameters(run, rule).get("per_zone")
            if zone is None or type(limit) is not int or not 1 <= limit <= 99:
                checks[rule].append(_check(rule, "unknown", "manual", "Capture déclarée : zone ou limite non renseignée.", pokemon, entry.get("date")))
            elif counts[zone] > limit:
                checks[rule].append(_check(rule, "review", "manual",
                    f"{counts[zone]} captures déclarées dans {zone[1]} pour une limite de {limit}. Vérifier les clauses et les déclarations.", pokemon, entry.get("date")))
        species = pokemon.get("species_id")
        if "species_clause" in checks and species is not None and species in species_seen:
            checks["species_clause"].append(_check("species_clause", "review", "manual", "Espèce déjà présente dans les captures déclarées. Vérifier la Species Clause.", pokemon, entry.get("date")))
        species_seen.add(species)
    if include_history:
        seen = set()
        for event in run.history:
            if event.get("type") != "party_changed" or event.get("source") != "automatic":
                continue
            party = event.get("payload", {}).get("party")
            if not isinstance(party, list) or len(party) > 6 or any(not isinstance(item, dict) for item in party):
                for rule in checks:
                    checks[rule].append(_check(rule, "unknown", "history", "Observation d'équipe historique inexploitable.", timestamp=event.get("timestamp")))
                continue
            for pokemon in party:
                try:
                    _pokemon(pokemon, observed=True, generation=run.generation)
                except ValueError:
                    for rule in checks:
                        checks[rule].append(_check(rule, "unknown", "history", "Observation d'équipe historique inexploitable : Pokémon historique incomplet ou invalide.", timestamp=event.get("timestamp")))
                    continue
                for item in _pokemon_checks(run, pokemon, "history", data, timestamp=event.get("timestamp")):
                    # Death status is current; never retroactively mark a living past member dead.
                    if item.state != "violation" or item.rule_id == "permanent_death":
                        continue
                    marker = (item.rule_id, item.pokemon_key, item.species_id, item.slot if not item.pokemon_key else None, item.message)
                    if marker not in seen:
                        checks[item.rule_id].append(item)
                        seen.add(marker)
    return tuple(RuleEvaluation(rule, CAPABILITIES.get(rule, RuleCapability("unavailable", "Règle inconnue du moteur de suivi.")), tuple(items))
                 for rule, items in checks.items())
