"""Read PE headers and version resources without loading or executing the file."""

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import struct


MAX_PE_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class PEInfo:
    path: Path
    architecture: str | None
    is_dll: bool
    sha256: str
    size: int
    product_name: str | None = None
    file_version: str | None = None
    contains_desmume: bool = False
    references_lua51: bool = False


def _version_strings(path: Path) -> tuple[str | None, str | None]:
    if os.name != "nt":
        return None, None
    version = ctypes.WinDLL("version", use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    version.GetFileVersionInfoW.restype = wintypes.BOOL
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                      ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    version.VerQueryValueW.restype = wintypes.BOOL
    unused = wintypes.DWORD()
    size = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(unused))
    if not size or size > 1024 * 1024:
        return None, None
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        return None, None
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    translations = []
    if version.VerQueryValueW(buffer, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)):
        if pointer.value and 4 <= length.value <= 4096:
            raw = ctypes.string_at(pointer, length.value)
            translations = list(struct.iter_unpack("<HH", raw[:len(raw) // 4 * 4]))
    for language, codepage in translations:
        values = []
        for key in ("ProductName", "FileVersion"):
            pointer, length = ctypes.c_void_p(), wintypes.UINT()
            query = f"\\StringFileInfo\\{language:04x}{codepage:04x}\\{key}"
            if (version.VerQueryValueW(buffer, query, ctypes.byref(pointer), ctypes.byref(length))
                    and pointer.value and 0 < length.value <= 1024):
                values.append(ctypes.wstring_at(pointer, length.value).rstrip("\x00") or None)
            else:
                values.append(None)
        if any(values):
            return values[0], values[1]
    return None, None


def inspect_pe_bytes(data: bytes, *, path: Path | None = None) -> PEInfo:
    """Bounds-check the DOS, COFF, optional and section headers."""
    if not 64 <= len(data) <= MAX_PE_BYTES or data[:2] != b"MZ":
        raise ValueError("Fichier Windows PE invalide.")
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    if offset < 64 or offset + 26 > len(data) or data[offset:offset + 4] != b"PE\0\0":
        raise ValueError("Signature PE invalide.")
    machine, sections = struct.unpack_from("<HH", data, offset + 4)
    optional_size, flags = struct.unpack_from("<HH", data, offset + 20)
    magic = struct.unpack_from("<H", data, offset + 24)[0]
    architecture = {0x014C: "x86", 0x8664: "x64"}.get(machine)
    if not flags & 2 or not 1 <= sections <= 96 or magic not in (0x10B, 0x20B):
        raise ValueError("En-tête exécutable PE invalide.")
    if (architecture == "x86" and magic != 0x10B) or (architecture == "x64" and magic != 0x20B):
        raise ValueError("Architecture PE incohérente.")
    minimum = 112 if magic == 0x20B else 96
    table = offset + 24 + optional_size
    if optional_size < minimum or table + sections * 40 > len(data):
        raise ValueError("En-tête PE tronqué.")
    for index in range(sections):
        size, pointer = struct.unpack_from("<II", data, table + index * 40 + 16)
        if size and (pointer < table + sections * 40 or pointer + size > len(data)):
            raise ValueError("Section PE tronquée.")
    lowered = data.lower()
    return PEInfo(path or Path(), architecture, bool(flags & 0x2000), hashlib.sha256(data).hexdigest(), len(data),
                  contains_desmume=b"desmume" in lowered or "desmume".encode("utf-16-le") in lowered,
                  references_lua51=b"lua51.dll" in lowered or "lua51.dll".encode("utf-16-le") in lowered)


def inspect_pe(path: str | Path) -> PEInfo:
    from dataclasses import replace
    from app.services.discovery_safety import local_path
    target = local_path(path)
    if not target.is_file() or target.is_symlink():
        raise ValueError("Binaire absent ou lien symbolique refusé.")
    before = target.stat()
    if before.st_size > MAX_PE_BYTES:
        raise ValueError("Binaire trop volumineux pour le diagnostic.")
    with target.open("rb") as handle:
        data = handle.read(MAX_PE_BYTES + 1)
    result = inspect_pe_bytes(data, path=target.resolve())
    after = target.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("Le binaire a changé pendant sa lecture.")
    product, version = _version_strings(target)
    return replace(result, product_name=product, file_version=version)
