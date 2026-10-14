"""Gen V shiny identity, independent of encounter probability and battle use.

Source: PKHeX PK5.PSV/TSV and PKM.IsShiny, pinned in docs/gen5-rule-observation.md.
The trainer here is the Pokemon's original trainer, not the current player.
"""


def shiny_status(pokemon: dict, generation: int = 5) -> bool | None:
    """None means insufficient evidence; zero is a valid PID or trainer ID."""
    if type(generation) is not int or generation != 5:
        return None
    pid = pokemon.get("personality_id")
    trainer = pokemon.get("original_trainer_id")
    if any(type(value) is not int or not 0 <= value <= 0xFFFFFFFF for value in (pid, trainer)):
        return None
    return ((pid >> 16) ^ (pid & 0xFFFF) ^ (trainer >> 16) ^ (trainer & 0xFFFF)) < 8
