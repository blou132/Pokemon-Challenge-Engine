"""Synthetic PE and network fixtures: installation never targets a user emulator."""

import hashlib
import io
from pathlib import Path
import struct
from types import SimpleNamespace
import urllib.error

import pytest

from app.services.desmume_discovery_service import DeSmuMEDiscoveryService
from app.services import lua_runtime_installer as runtime
from app.services.lua_runtime_installer import LuaReplacementRequired, LuaRuntimeInstaller
from app.services.pe_inspection import inspect_pe, inspect_pe_bytes
from app.services import trusted_download_service as download
from app.services.trusted_download_service import TrustedDownloadService


def pe_bytes(architecture="x64", *, dll=False, markers=b"", suffix=b""):
    raw = bytearray(1024)
    raw[:2] = b"MZ"
    struct.pack_into("<I", raw, 0x3C, 128)
    raw[128:132] = b"PE\0\0"
    struct.pack_into("<HH", raw, 132, 0x8664 if architecture == "x64" else 0x14C, 1)
    optional = 240 if architecture == "x64" else 224
    struct.pack_into("<HH", raw, 148, optional, 2 | (0x2000 if dll else 0))
    struct.pack_into("<H", raw, 152, 0x20B if architecture == "x64" else 0x10B)
    table = 152 + optional
    struct.pack_into("<II", raw, table + 16, 512, 512)
    raw[512:512 + len(markers)] = markers
    return bytes(raw) + suffix


@pytest.mark.parametrize("architecture", ["x64", "x86"])
def test_pe_architecture_comes_from_binary_not_name(tmp_path, architecture):
    path = tmp_path / "misleading-x86-name.exe"
    path.write_bytes(pe_bytes(architecture, markers=b"DeSmuME lua51.dll"))
    info = inspect_pe(path)
    assert info.architecture == architecture
    assert not info.is_dll
    assert info.references_lua51
    assert info.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("corruption", ["mz", "offset", "signature", "machine_magic", "section", "optional"])
def test_malformed_pe_rejected(corruption):
    raw = bytearray(pe_bytes())
    if corruption == "mz": raw[:2] = b"NO"
    elif corruption == "offset": struct.pack_into("<I", raw, 0x3C, 999999)
    elif corruption == "signature": raw[128:132] = b"BAD!"
    elif corruption == "machine_magic": struct.pack_into("<H", raw, 152, 0x10B)
    elif corruption == "section": struct.pack_into("<I", raw, 152 + 240 + 16, 999999)
    elif corruption == "optional": struct.pack_into("<H", raw, 148, 10)
    with pytest.raises(ValueError):
        inspect_pe_bytes(bytes(raw))


def test_missing_binary_and_dll_are_not_discovered_as_emulators(tmp_path):
    (tmp_path / "DeSmuME.exe").write_bytes(pe_bytes())
    (tmp_path / "dll.exe").write_bytes(pe_bytes(dll=True, markers=b"DeSmuME lua51.dll"))
    assert DeSmuMEDiscoveryService().discover([tmp_path], [tmp_path / "missing.exe"]) == []


def test_installer_downloads_use_the_directory_measured_by_storage(tmp_path):
    from app.services.local_storage_service import LocalStorageService
    cache = tmp_path / "runtime/downloads"
    installer = LuaRuntimeInstaller(cache)
    assert installer.downloader.cache_dir == cache
    archive = cache / f"lua-{download.LUA_ARCHIVE_SHA256}.7z"
    cache.mkdir(parents=True)
    archive.write_bytes(b"synthetic cache marker")
    from unittest.mock import patch
    with patch.object(download, "archive_is_trusted", side_effect=lambda path: path == archive):
        item = next(item for item in LocalStorageService(tmp_path).summary()["items"] if item["kind"] == "downloads")
        assert item["count"] == 1 and item["bytes"] == archive.stat().st_size


@pytest.fixture
def installation(tmp_path, monkeypatch):
    directory = tmp_path / "emulator"
    directory.mkdir()
    exe = directory / "not-named-desmume.exe"
    exe.write_bytes(pe_bytes(markers=b"DeSmuME lua51.dll"))
    blobs = {name: pe_bytes(dll=True, suffix=name.encode()) for name in ("lua51.dll", "lua5.1.dll")}
    manifest = {"x64": {name: ("x64/" + name, len(data), hashlib.sha256(data).hexdigest())
                        for name, data in blobs.items()}, "x86": runtime.DLL_MANIFEST["x86"]}
    monkeypatch.setattr(runtime, "DLL_MANIFEST", manifest)
    monkeypatch.setattr(runtime, "extractor_path", lambda: Path("tar.exe"))
    journal = []
    downloader = SimpleNamespace(download_lua=lambda: SimpleNamespace(path=tmp_path / "source.7z"))
    service = LuaRuntimeInstaller(tmp_path / "cache", running_probe=lambda exe: False,
        journal=lambda event, **details: journal.append((event, details)), downloader=downloader,
        extractor=lambda archive, architecture: dict(blobs))
    return SimpleNamespace(exe=exe, service=service, blobs=blobs, journal=journal)


def test_discovery_recognizes_pe_markers_and_reports_ini_and_missing_lua(installation):
    item = installation
    (item.exe.parent / "desmume.ini").write_bytes(b"[Controls]\nA=88")
    found = DeSmuMEDiscoveryService().discover([item.exe.parent], [item.exe])
    assert len(found) == 1
    assert found[0].architecture == "x64"
    assert found[0].ini_path is not None
    assert found[0].lua_status == "missing"
    assert not found[0].known_build
    assert not found[0].replacement_required


def test_install_verifies_both_dlls_and_is_idempotent(installation):
    item = installation
    assert item.service.diagnose(item.exe).status == "missing"
    result = item.service.install(item.exe)
    assert len(result.changed) == 2 and result.backups == ()
    assert result.diagnostic.ready
    assert result.diagnostic.console_status == "not_tested"
    assert {entry[0] for entry in item.journal} >= {"lua_runtime_install_started", "lua_runtime_installed"}
    before = {name: (item.exe.parent / name).stat().st_mtime_ns for name in item.blobs}
    assert item.service.install(item.exe).changed == ()
    assert before == {name: (item.exe.parent / name).stat().st_mtime_ns for name in item.blobs}


def test_one_missing_dll_only_installs_missing_file(installation):
    item = installation
    (item.exe.parent / "lua51.dll").write_bytes(item.blobs["lua51.dll"])
    result = item.service.install(item.exe)
    assert [p.name for p in result.changed] == ["lua5.1.dll"]
    assert not result.backups


def test_different_dll_requires_confirmation_then_backup_is_preserved(installation):
    item = installation
    destination = item.exe.parent / "lua51.dll"
    original = pe_bytes(dll=True, suffix=b"different local runtime")
    destination.write_bytes(original)
    older_backup = destination.with_name("lua51.dll.pce-backup")
    older_backup.write_bytes(b"prior backup")
    candidate = DeSmuMEDiscoveryService().inspect(item.exe)
    assert candidate.replacement_required
    with pytest.raises(LuaReplacementRequired) as caught:
        item.service.install(item.exe)
    assert caught.value.paths == (destination,)
    assert destination.read_bytes() == original
    assert not item.journal
    result = item.service.install(item.exe, allow_replace=True)
    assert result.backups[0].name == "lua51.dll.pce-backup.1"
    assert result.backups[0].read_bytes() == original
    assert older_backup.read_bytes() == b"prior backup"


def test_wrong_architecture_is_reported_and_requires_replacement_confirmation(installation):
    item = installation
    (item.exe.parent / "lua51.dll").write_bytes(pe_bytes("x86", dll=True))
    diagnostic = item.service.diagnose(item.exe)
    assert diagnostic.dlls[0].status == "wrong_architecture"
    assert not diagnostic.ready
    with pytest.raises(LuaReplacementRequired):
        item.service.install(item.exe)


@pytest.mark.parametrize("state", [True, None])
def test_running_or_unverifiable_emulator_never_installs(installation, state):
    item = installation
    item.service.running_probe = lambda exe: state
    with pytest.raises(ValueError, match="Fermez"):
        item.service.install(item.exe)
    assert not list(item.exe.parent.glob("*.dll"))


def test_wrong_extracted_architecture_rejected_before_any_write(installation):
    item = installation
    item.service.extractor = lambda *args: {name: pe_bytes("x86", dll=True) for name in item.blobs}
    with pytest.raises(ValueError):
        item.service.install(item.exe)
    assert not list(item.exe.parent.glob("*.dll"))


def test_interrupted_second_replace_rolls_back_first_dll(installation, monkeypatch):
    item = installation
    replace = Path.replace
    def locked(self, target):
        if Path(target).name == "lua5.1.dll":
            raise PermissionError("locked")
        return replace(self, target)
    monkeypatch.setattr(Path, "replace", locked)
    with pytest.raises(ValueError, match="annulée"):
        item.service.install(item.exe)
    assert not list(item.exe.parent.glob("*.dll"))
    assert not list(item.exe.parent.glob(".pce_lua_*"))
    assert item.journal[-1][0] == "lua_runtime_install_failed"


def test_interrupted_replacement_restores_existing_dll_and_preserves_backup(installation, monkeypatch):
    item = installation
    destination = item.exe.parent / "lua51.dll"
    original = b"previous local runtime"
    destination.write_bytes(original)
    replace = Path.replace
    def locked(self, target):
        if Path(target).name == "lua5.1.dll":
            raise PermissionError("locked")
        return replace(self, target)
    monkeypatch.setattr(Path, "replace", locked)
    with pytest.raises(ValueError, match="annulée"):
        item.service.install(item.exe, allow_replace=True)
    assert destination.read_bytes() == original
    assert destination.with_name("lua51.dll.pce-backup").read_bytes() == original
    assert not (item.exe.parent / "lua5.1.dll").exists()


def test_truthy_text_is_not_a_replacement_confirmation(installation):
    with pytest.raises(ValueError, match="explicite"):
        installation.service.install(installation.exe, allow_replace="false")


def test_permission_denied_backup_preserves_original(installation, monkeypatch):
    item = installation
    old = b"old runtime"
    destination = item.exe.parent / "lua51.dll"
    destination.write_bytes(old)
    def denied(*args): raise PermissionError("denied")
    monkeypatch.setattr(item.service, "_backup", denied)
    with pytest.raises(ValueError):
        item.service.install(item.exe, allow_replace=True)
    assert destination.read_bytes() == old
    assert not (item.exe.parent / "lua5.1.dll").exists()


def test_external_change_during_preparation_is_never_overwritten(installation):
    item = installation
    def extract(*args):
        (item.exe.parent / "lua51.dll").write_bytes(b"external new file")
        return item.blobs
    item.service.extractor = extract
    with pytest.raises(ValueError):
        item.service.install(item.exe)
    assert (item.exe.parent / "lua51.dll").read_bytes() == b"external new file"


def test_installer_journals_network_failure_without_external_changes(installation):
    item = installation
    def fail(): raise ValueError("Réseau indisponible")
    item.service.downloader.download_lua = fail
    with pytest.raises(ValueError, match="Réseau"):
        item.service.install(item.exe)
    assert item.journal[-1] == ("lua_runtime_install_failed", {
        "stage": "preparation", "error": "Réseau indisponible", "changed": []})
    assert not list(item.exe.parent.glob("*.dll"))


class Response(io.BytesIO):
    def __init__(self, data, *, url=download.LUA_URL, length=None):
        super().__init__(data)
        self.url = url
        self.headers = {} if length is None else {"Content-Length": str(length)}
    def geturl(self): return self.url


@pytest.fixture
def source(monkeypatch):
    raw = b"synthetic pinned archive"
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(download, "LUA_ARCHIVE_SIZE", len(raw))
    monkeypatch.setattr(download, "LUA_ARCHIVE_SHA256", digest)
    return raw


def test_trusted_download_uses_only_pinned_https_url_and_cache(tmp_path, source):
    requests = []
    def open_request(request, timeout):
        requests.append((request.full_url, timeout))
        return Response(source)
    service = TrustedDownloadService(tmp_path, opener=SimpleNamespace(open=open_request))
    first = service.download_lua()
    assert first.path.read_bytes() == source and not first.cached
    assert service.download_lua().cached
    assert requests == [(download.LUA_URL, 20)]
    assert download.LUA_URL.startswith("https://raw.githubusercontent.com/TASEmulators/desmume/")


@pytest.mark.parametrize("problem", ["bad_hash", "truncated", "oversize", "redirect", "interrupted"])
def test_download_failure_removes_temporary_and_never_publishes_archive(tmp_path, source, problem):
    class Interrupted(Response):
        def read(self, *args): raise urllib.error.URLError("interrupted")
    def open_request(*args, **kwargs):
        if problem == "bad_hash": return Response(b"X" * len(source))
        if problem == "truncated": return Response(source[:-2])
        if problem == "oversize": return Response(source, length=download.MAX_DOWNLOAD_BYTES + 1)
        if problem == "redirect": return Response(source, url="https://untrusted.example/lua.7z")
        return Interrupted(source)
    service = TrustedDownloadService(tmp_path, opener=SimpleNamespace(open=open_request))
    with pytest.raises(ValueError):
        service.download_lua()
    assert list(tmp_path.iterdir()) == []


def test_corrupt_cache_is_reverified_and_replaced_by_pinned_content(tmp_path, source):
    service = TrustedDownloadService(tmp_path, opener=SimpleNamespace(open=lambda *a, **k: Response(source)))
    first = service.download_lua()
    first.path.write_bytes(b"corrupt")
    assert not service.download_lua().cached
    assert first.path.read_bytes() == source


def test_invalid_archive_never_runs_extractor(tmp_path):
    path = tmp_path / "bad.7z"
    path.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="non vérifiée"):
        runtime.extract_lua_dlls(path, "x64")
