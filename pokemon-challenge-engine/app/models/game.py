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

    @property
    def supports_melonds(self) -> bool:
        return self.platform == "Nintendo DS" and self.status in {"supported", "classic_only"}

    @property
    def supports_live_tracking(self) -> bool:
        return self.generation == 5 and self.status == "supported"

    @property
    def compatibility_summary(self) -> str:
        if self.status == "classic_only":
            return ("Partie classique avec melonDS. Suivi d'équipe, règles de challenge et "
                    "transformations ROM non disponibles pour la génération IV.")
        if self.supports_live_tracking:
            return ("Classique et challenges Gen V ; suivi selon les événements disponibles. "
                    "Randomizer et Monotype : ROM françaises révision 0. "
                    "Taux shiny expérimental : Blanc FR révision 0 uniquement.")
        return "Jeu prévu pour une version ultérieure."
