"""Description déclarative d'une règle et de son état dans le générateur."""

from dataclasses import dataclass, field
from enum import Enum


class RuleState(str, Enum):
    REQUIRED = "required"
    POSSIBLE = "possible"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    name: str
    description: str
    difficulty: int
    category: str
    requires: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    supported_games: tuple[str, ...] = ()
    supports_strict_mode: bool = False
    supports_soft_mode: bool = True
    implementation_status: str = "ui_only"
    parameters: dict = field(default_factory=dict)
