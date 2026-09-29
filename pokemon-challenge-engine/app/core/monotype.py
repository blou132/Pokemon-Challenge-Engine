"""Tirage reproductible et équitable parmi les types autorisés en génération V."""

import random

GEN5_TYPE_IDS = (
    "normal", "fire", "water", "electric", "grass", "ice", "fighting", "poison",
    "ground", "flying", "psychic", "bug", "rock", "ghost", "dragon", "dark", "steel",
)
MONOTYPE_MODES = ("soft", "strict", "pure")


def validate_allowed_types(allowed_types: list[str]) -> None:
    if not isinstance(allowed_types, list) or not allowed_types:
        raise ValueError("Autorisez au moins un type pour le tirage Monotype.")
    if any(not isinstance(item, str) or item not in GEN5_TYPE_IDS for item in allowed_types):
        raise ValueError("Le Monotype accepte uniquement les 17 types de la génération V.")
    if len(set(allowed_types)) != len(allowed_types):
        raise ValueError("La liste des types autorisés contient des doublons.")


def select_type(allowed_types: list[str], seed: int, roll_index: int = 0) -> str:
    """L'animation ne participe jamais au choix; chaque relance a son index."""
    validate_allowed_types(allowed_types)
    if type(seed) is not int or seed < 0:
        raise ValueError("La seed doit être un entier positif ou nul.")
    if type(roll_index) is not int or roll_index < 0:
        raise ValueError("L'index de relance doit être un entier positif ou nul.")
    # Un ordre canonique rend le résultat indépendant de l'ordre des cases cochées.
    population = [item for item in GEN5_TYPE_IDS if item in allowed_types]
    return random.Random(f"pokemon-challenge-engine:monotype:{seed}:{roll_index}").choice(population)


def matches_type(pokemon_types: list[str], target: str, mode: str = "soft") -> bool:
    """Aide future pure; cette fonction ne lit ni ne modifie le jeu."""
    if target not in GEN5_TYPE_IDS or mode not in MONOTYPE_MODES:
        raise ValueError("Type ou mode Monotype inconnu.")
    if not pokemon_types or any(item not in GEN5_TYPE_IDS for item in pokemon_types):
        return False
    if mode == "strict":
        return pokemon_types[0] == target
    if mode == "pure":
        return all(item == target for item in pokemon_types)
    return target in pokemon_types
