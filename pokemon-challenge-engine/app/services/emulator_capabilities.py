"""Capabilities of a fingerprinted Windows build; never inferred from its filename."""

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path


VERIFIED_BUILD_SHA256 = "34fe290e387722f1b4320751bf0b0f50844079833c7dce57c273d6b054becac0"
SOURCE_COMMIT = "1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a"


@dataclass(frozen=True)
class EmulatorCapabilities:
    emulator: str = "desmume"
    fingerprint: str = ""
    known_build: bool = False
    verification: str = "unknown"
    supports_controls_config: bool = False
    supports_speed_control: bool = False
    supports_speed_config: bool = False
    supports_internal_resolution: bool = False
    supports_vsync: bool = False
    supports_output_filter: bool = False
    supports_aspect_ratio: bool = False
    supports_layout: bool = False
    supports_rotation: bool = False
    supports_save_states: bool = False
    supports_lua: bool = False
    supports_shader: bool = False
    supports_gamepad_mapping: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def detect_capabilities(executable: str | Path) -> EmulatorCapabilities:
    if not str(executable).strip():
        return EmulatorCapabilities()
    path = Path(executable)
    if not path.is_file() or path.suffix.lower() != ".exe":
        return EmulatorCapabilities()
    try:
        with path.open("rb") as handle:
            fingerprint = hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        return EmulatorCapabilities()
    if fingerprint != VERIFIED_BUILD_SHA256:
        return EmulatorCapabilities(fingerprint=fingerprint)
    return EmulatorCapabilities(
        fingerprint=fingerprint, known_build=True, verification="documented_source_and_binary",
        supports_controls_config=True, supports_speed_config=True,
        supports_internal_resolution=True, supports_vsync=True, supports_output_filter=True,
        supports_aspect_ratio=True, supports_layout=True, supports_rotation=True,
        supports_save_states=True,
        supports_lua=all((path.parent / name).is_file() for name in ("lua51.dll", "lua5.1.dll")),
    )
