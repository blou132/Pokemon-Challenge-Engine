"""État exposé par la passerelle, indépendant des composants d'interface."""

from dataclasses import dataclass
from typing import Literal

BridgeStatus = Literal["stopped", "waiting", "connected", "receiving", "disconnected", "error"]


@dataclass(frozen=True)
class BridgeState:
    status: BridgeStatus = "stopped"
    expected_game: str | None = None
    game_id: str | None = None
    game_code: str | None = None
    game_region: str | None = None
    rom_revision: int | None = None
    script_version: str | None = None
    memory_profile: str | None = None
    capabilities: tuple[str, ...] = ()
    party_size: int | None = None
    party: list[dict[str, int | None]] | None = None
    received_count: int = 0
    last_received_at: float | None = None
    last_timestamp: int | None = None
    last_event: str | None = None
    last_error: str | None = None
    sequence: int = 0
    protocol_version: int = 1
    session_id: str | None = None
    observation: dict | None = None
    observations: tuple[dict, ...] = ()

    @property
    def connected(self) -> bool:
        return self.status in {"connected", "receiving"}
