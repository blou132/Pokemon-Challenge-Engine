"""Strict Gen V battery conversion; never rewrite or trim a source save.

Format: TASEmulators/desmume desmume/doc/dsv.txt and src/mc.cpp,
BackupDevice::readFooter / ensure. The cookie is 16 bytes without a terminating
NUL. Only version 0 and 512 KiB are accepted.
"""

import hashlib
import os
from pathlib import Path
import struct

from app.services.discovery_safety import file_hash, file_signature, local_path
from app.services.run_isolation_service import _regular


GEN5_SAVE_BYTES = 512 * 1024
DSV_COOKIE = b"|-DESMUME SAVE-|"


def gen5_battery_bytes(data: bytes, suffix: str) -> bytes:
    """Preserve every raw byte, including padding; reject ambiguous containers."""
    if suffix.lower() == ".sav":
        if len(data) != GEN5_SAVE_BYTES:
            raise ValueError("Une sauvegarde Gen V brute doit mesurer exactement 512 Kio.")
        return data
    if suffix.lower() != ".dsv" or not data.endswith(DSV_COOKIE) or len(data) < 40:
        raise ValueError("Sauvegarde DSV non reconnue ; utilisez l'export batterie de DeSmuME.")
    written, padded, _kind, address_size, _memory_size, version = struct.unpack(
        "<6I", data[-len(DSV_COOKIE) - 24:-len(DSV_COOKIE)])
    if version != 0 or padded != GEN5_SAVE_BYTES or not 0 < written <= padded or address_size != 3:
        raise ValueError("Format DSV non pris en charge pour Gen V ; aucune conversion effectuée.")
    # Current v0 footer is exactly 122 bytes. A different trailer needs review,
    # even if its cookie and reported padded size happen to match.
    if len(data) != padded + 122:
        raise ValueError("Longueur du pied DSV inattendue ; sauvegarde conservée.")
    return data[:padded]


def convert_gen5_battery(source: Path, destination: Path) -> dict:
    """Write one new .sav and return copy provenance; never overwrite a target."""
    source, destination = _regular(Path(source)), local_path(destination)
    if destination.suffix.lower() != ".sav" or destination.exists():
        raise ValueError("La conversion exige un nouveau fichier .sav ; aucun écrasement autorisé.")
    before = file_signature(source)
    if source.stat().st_size > GEN5_SAVE_BYTES + 122:
        raise ValueError("Sauvegarde trop volumineuse pour Gen V.")
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    raw = gen5_battery_bytes(data, source.suffix)
    if file_signature(source) != before or file_hash(source) != digest or file_signature(source) != before:
        raise ValueError("La sauvegarde a changé pendant la lecture ; fermez l'émulateur.")
    with destination.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    output_hash = hashlib.sha256(raw).hexdigest()
    if file_hash(destination) != output_hash:
        raise ValueError("La copie convertie ne correspond pas aux données lues.")
    return {"source_sha256": digest, "output_sha256": output_hash,
            "source_format": source.suffix.lower()[1:], "output_format": "raw_gen5_512k",
            "size": len(raw)}
