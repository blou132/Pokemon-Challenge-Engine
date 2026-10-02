"""Only the exact pinned official DeSmuME Lua archive can be downloaded."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.request

from app.services.discovery_safety import local_path


LUA_COMMIT = "1275dc64f5d1f5ef18dc1bc1fa9e012024b6df1a"
LUA_URL = (f"https://raw.githubusercontent.com/TASEmulators/desmume/{LUA_COMMIT}/"
           "desmume/src/frontend/windows/lua/lua.7z")
LUA_ARCHIVE_SHA256 = "3814c8c1b884170176ea336cebf03da4e32908dc66394b238959df02a5d1e4a3"
LUA_ARCHIVE_SIZE = 166260
MAX_DOWNLOAD_BYTES = 1024 * 1024


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    sha256: str
    url: str
    cached: bool


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("La source officielle a redirigé le téléchargement ; opération refusée.")


def archive_is_trusted(path: Path) -> bool:
    if not path.is_file() or path.is_symlink() or path.stat().st_size != LUA_ARCHIVE_SIZE:
        return False
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest() == LUA_ARCHIVE_SHA256


class TrustedDownloadService:
    def __init__(self, cache_dir: Path, *, opener=None, timeout: float = 20, journal=None):
        self.cache_dir = local_path(cache_dir)
        self.opener = opener or urllib.request.build_opener(_NoRedirect())
        self.timeout = timeout
        self.journal = journal or (lambda event, **details: None)

    def download_lua(self) -> DownloadResult:
        local_path(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.cache_dir.is_symlink():
            raise ValueError("Cache de téléchargement symbolique refusé.")
        destination = self.cache_dir / f"lua-{LUA_ARCHIVE_SHA256}.7z"
        if destination.is_symlink():
            raise ValueError("Archive du cache symbolique refusée.")
        if archive_is_trusted(destination):
            self.journal("lua_download_cached", path=str(destination), sha256=LUA_ARCHIVE_SHA256)
            return DownloadResult(destination, LUA_ARCHIVE_SHA256, LUA_URL, True)
        temporary = None
        self.journal("lua_download_started", url=LUA_URL, expected_sha256=LUA_ARCHIVE_SHA256)
        try:
            request = urllib.request.Request(LUA_URL, headers={"User-Agent": "Pokemon-Challenge-Engine/0.3.6",
                                                             "Accept-Encoding": "identity"})
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.geturl() != LUA_URL:
                    raise ValueError("Source de téléchargement non autorisée.")
                declared = response.headers.get("Content-Length")
                if declared is not None and (not declared.isdecimal() or int(declared) > MAX_DOWNLOAD_BYTES):
                    raise ValueError("Taille annoncée du téléchargement invalide.")
                digest, total = hashlib.sha256(), 0
                with tempfile.NamedTemporaryFile(dir=self.cache_dir, prefix=".lua_download_", delete=False) as handle:
                    temporary = Path(handle.name)
                    while True:
                        chunk = response.read(min(65536, MAX_DOWNLOAD_BYTES + 1 - total))
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_DOWNLOAD_BYTES:
                            raise ValueError("Le téléchargement dépasse la taille maximale.")
                        digest.update(chunk)
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                if total != LUA_ARCHIVE_SIZE or digest.hexdigest() != LUA_ARCHIVE_SHA256:
                    raise ValueError("Archive Lua incomplète ou empreinte officielle différente.")
            temporary.replace(destination)
            self.journal("lua_download_verified", path=str(destination), url=LUA_URL,
                         sha256=LUA_ARCHIVE_SHA256, size=total)
            return DownloadResult(destination, LUA_ARCHIVE_SHA256, LUA_URL, False)
        except (OSError, urllib.error.URLError) as exc:
            raise ValueError("Téléchargement Lua impossible. Vérifiez le réseau, l'espace libre et les permissions.") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
