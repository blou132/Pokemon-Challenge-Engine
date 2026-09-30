"""Contrats de la passerelle locale DeSmuME, sans dépendance à Qt."""

from app.bridge.protocol import BridgeMessage, ProtocolError, parse_message
from app.bridge.state import BridgeState

__all__ = ["BridgeMessage", "BridgeState", "ProtocolError", "parse_message"]
