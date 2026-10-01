"""Own-process window discovery/placement; no embedding, hooks or keyboard input.

Win32 contracts: https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-enumwindows
https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-setwindowpos
https://learn.microsoft.com/windows/win32/api/tlhelp32/ns-tlhelp32-processentry32w
"""

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import os
from pathlib import Path


class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


@dataclass(frozen=True)
class EmulatorWindow:
    handle: int
    pid: int
    title: str
    executable: str
    rect: tuple[int, int, int, int]


class EmulatorWindowManager:
    """A future embedding adapter can replace this external-window implementation."""

    def __init__(self):
        self.available = os.name == "nt"
        if not self.available:
            return
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        signatures = {
            "EnumWindows": ([self.callback_type, wintypes.LPARAM], wintypes.BOOL),
            "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
            "GetWindow": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            "GetWindowThreadProcessId": ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            "GetWindowTextLengthW": ([wintypes.HWND], ctypes.c_int),
            "GetWindowTextW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            "GetWindowRect": ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            "SetWindowPos": ([wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = arguments, result
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                         wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        for name in ("Process32FirstW", "Process32NextW"):
            function = getattr(self.kernel, name)
            function.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
            function.restype = wintypes.BOOL

    def _executable(self, pid: int) -> str:
        handle = self.kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            return buffer.value if self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) else ""
        finally:
            self.kernel.CloseHandle(handle)

    def windows(self, pid: int | None = None) -> list[EmulatorWindow]:
        if not self.available:
            return []
        found = []

        def visit(hwnd, _parameter):
            owner = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if ((pid is not None and owner.value != pid) or not self.user.IsWindowVisible(hwnd)
                    or self.user.GetWindow(hwnd, 4)):  # GW_OWNER excludes dialogs
                return True
            length = min(self.user.GetWindowTextLengthW(hwnd), 4096)
            title = ctypes.create_unicode_buffer(length + 1)
            self.user.GetWindowTextW(hwnd, title, length + 1)
            rect = wintypes.RECT()
            if title.value and self.user.GetWindowRect(hwnd, ctypes.byref(rect)):
                found.append(EmulatorWindow(int(hwnd), owner.value, title.value, self._executable(owner.value),
                                            (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)))
            return True

        callback = self.callback_type(visit)
        if not self.user.EnumWindows(callback, 0):
            raise OSError("Impossible d'énumérer les fenêtres Windows.")
        return found

    def find(self, pid: int, executable: str | Path | None = None) -> EmulatorWindow | None:
        matches = self.windows(pid)
        if executable:
            expected = os.path.normcase(str(Path(executable).resolve()))
            matches = [item for item in matches if item.executable and os.path.normcase(item.executable) == expected]
        # Never pick arbitrarily between multiple top-level windows.
        return matches[0] if len(matches) == 1 else None

    def running_executable(self, executable: str | Path) -> bool:
        if not self.available:
            raise OSError("La vérification des processus nécessite Windows.")
        if not str(executable).strip():
            raise ValueError("Choisissez un exécutable pour vérifier son arrêt.")
        expected = os.path.normcase(str(Path(executable).resolve()))
        expected_name = Path(expected).name.casefold()
        # Process enumeration also covers minimised/hidden windows and startup.
        for pid, name in self._processes():
            if name.casefold() != expected_name:
                continue
            actual = self._executable(pid)
            if not actual:
                # An inaccessible matching process cannot certify a safe INI write.
                raise OSError("Impossible de confirmer l'arrêt de cet émulateur.")
            if os.path.normcase(actual) == expected:
                return True
        return False

    def _processes(self) -> list[tuple[int, str]]:
        handle = self.kernel.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if handle == ctypes.c_void_p(-1).value:
            raise OSError("Impossible d'énumérer les processus Windows.")
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            if not self.kernel.Process32FirstW(handle, ctypes.byref(entry)):
                raise OSError("Impossible de lire la liste des processus Windows.")
            entries = []
            while True:
                entries.append((entry.th32ProcessID, entry.szExeFile))
                if not self.kernel.Process32NextW(handle, ctypes.byref(entry)):
                    if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                        raise OSError("Liste des processus Windows incomplète.")
                    return entries
        finally:
            self.kernel.CloseHandle(handle)

    def arrange(self, pid: int, rect: tuple[int, int, int, int], *, executable: str | Path) -> EmulatorWindow:
        if (not isinstance(rect, tuple) or len(rect) != 4 or any(type(value) is not int for value in rect)
                or not 128 <= rect[2] <= 16384 or not 128 <= rect[3] <= 16384):
            raise ValueError("Dimensions de fenêtre invalides.")
        window = self.find(pid, executable)
        if window is None:
            raise ValueError("Fenêtre DeSmuME absente ou ambiguë ; placement annulé.")
        # NOZORDER | NOACTIVATE: arranging must not redirect the user's keyboard.
        if not self.user.SetWindowPos(window.handle, None, *rect, 0x0004 | 0x0010):
            raise OSError("Windows a refusé le placement de DeSmuME.")
        return self.find(pid, executable) or window
