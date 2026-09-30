"""Jeux décrits dans le catalogue, sans dépendance envers l'interface."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Game:
    id: str
    name: str
    generation: int
    platform: str
    type_count: int
    supports_monotype: bool
    supports_desmume: bool
    status: str
    game_code: str | None = None
    region: str | None = None
    revision: int | None = None
