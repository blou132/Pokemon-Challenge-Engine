"""Spawn external tools without inheriting the frozen application's Qt loader.

See PyInstaller's documented Windows SetDllDirectory subprocess requirement.
Only the spawn is enclosed; the parent's loader is restored before waiting.
"""

from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import threading

_SPAWN_LOCK = threading.Lock()


def child_environment(extra=None):
    env = dict(os.environ)
    for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_PLATFORM"):
        env.pop(key, None)
    resources = getattr(sys, "_MEIPASS", None)
    if resources:
        root = Path(resources).resolve()
        env["PATH"] = os.pathsep.join(entry for entry in env.get("PATH", "").split(os.pathsep)
                                    if entry and not Path(entry).resolve().is_relative_to(root))
    if extra:
        env.update(extra)
    return env


@contextmanager
def external_dll_search():
    if os.name != "nt" or not getattr(sys, "frozen", False):
        yield
        return
    with _SPAWN_LOCK:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
        kernel.GetDllDirectoryW.restype = ctypes.c_uint32
        kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
        kernel.SetDllDirectoryW.restype = ctypes.c_bool
        length = kernel.GetDllDirectoryW(0, None)
        buffer = ctypes.create_unicode_buffer(length + 1)
        if length:
            kernel.GetDllDirectoryW(len(buffer), buffer)
        if not kernel.SetDllDirectoryW(None):
            raise OSError("Impossible de préparer le chargement des bibliothèques externes.")
        try:
            yield
        finally:
            if not kernel.SetDllDirectoryW(buffer.value if length else None):
                raise OSError("Impossible de rétablir le chargement des bibliothèques de PCE.")


def run_external(command, *, cwd, timeout):
    with external_dll_search():
        process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=child_environment(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    with process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
        except BaseException:
            process.kill()
            process.wait()
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
