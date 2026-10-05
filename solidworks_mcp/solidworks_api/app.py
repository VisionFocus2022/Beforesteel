"""SolidWorks application connection management."""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Any, Optional

import win32com.client

from solidworks_mcp.config import get_config
from solidworks_mcp.utils.com import call_or_value

logger = logging.getLogger(__name__)

# M-4 (2026-10-05): module-level lazy singleton — WinDLL handles and the
# ctypes prototypes were previously rebuilt on every probe call; they are
# process-stable, so declare them once.
_kernel32: Any = None


def _get_kernel32() -> Any:
    """The process-wide kernel32 handle with session prototypes declared."""
    global _kernel32
    if _kernel32 is None:
        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        dll.GetCurrentProcessId.argtypes = []
        dll.GetCurrentProcessId.restype = wintypes.DWORD
        dll.ProcessIdToSessionId.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        dll.ProcessIdToSessionId.restype = wintypes.BOOL
        _kernel32 = dll
    return _kernel32


def _same_session(pid: int, kernel32: Any = None) -> bool:
    """Return True when ``pid`` belongs to the current Windows session.

    The Toolhelp32 snapshot lists processes from every session, so a
    SLDWORKS.exe started by another user (fast user switching / RDP) must
    not be mistaken for a SolidWorks instance we could attach to.
    """
    dll = kernel32 if kernel32 is not None else _get_kernel32()
    own_session = wintypes.DWORD(0)
    session = wintypes.DWORD(0)
    if not dll.ProcessIdToSessionId(
        dll.GetCurrentProcessId(), ctypes.byref(own_session)
    ):
        return False
    if not dll.ProcessIdToSessionId(pid, ctypes.byref(session)):
        return False
    return session.value == own_session.value


def _is_solidworks_process_running() -> bool:
    """Return True when SLDWORKS.exe runs in this Windows session."""
    max_path = 260
    snapshot_process = 0x00000002
    invalid_handle_value = ctypes.c_void_p(-1).value

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * max_path),
        ]

    kernel32 = _get_kernel32()  # M-4: snapshot prototypes ride the singleton
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(snapshot_process, 0)
    if snapshot == invalid_handle_value:
        return False

    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return False
        while True:
            if entry.szExeFile.lower() == "sldworks.exe" and _same_session(
                entry.th32ProcessID, kernel32
            ):
                return True
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                return False
    finally:
        kernel32.CloseHandle(snapshot)


class SolidWorksApp:
    """Wrapper around the SolidWorks COM application object."""

    def __init__(self) -> None:
        self._app: Optional[Any] = None
        self._version: Optional[str] = None

    @property
    def app(self) -> Any:
        if self._app is None:
            raise SolidWorksNotRunningError("SolidWorks is not connected")
        return self._app

    @property
    def connected(self) -> bool:
        return self._app is not None

    @property
    def version(self) -> Optional[str]:
        return self._version

    def connect(self, launch_if_needed: Optional[bool] = None) -> dict:
        """Connect to a running SolidWorks instance.

        Returns:
            A result dictionary with success status and version information.
        """
        if self._app is not None:
            try:
                revision = call_or_value(self._app, "RevisionNumber")
                self._version = revision
                return {
                    "success": True,
                    "data": {"version": revision, "connected": True},
                    "message": "Already connected to SolidWorks",
                    "warning": None,
                    "error": None,
                }
            except Exception:
                self._app = None

        try:
            should_launch = (
                get_config().auto_start if launch_if_needed is None else launch_if_needed
            )
            try:
                app = win32com.client.GetActiveObject("SldWorks.Application")
            except Exception:
                already_running = _is_solidworks_process_running()
                if not should_launch and not already_running:
                    raise SolidWorksNotRunningError("SolidWorks is not running")
                app = win32com.client.Dispatch("SldWorks.Application")
                if should_launch and not already_running:
                    app.Visible = True
            # Force COM to create a real connection by touching a property.
            revision = call_or_value(app, "RevisionNumber")
            self._app = app
            self._version = revision
            return {
                "success": True,
                "data": {"version": revision, "connected": True},
                "message": "Connected to SolidWorks",
                "warning": None,
                "error": None,
            }
        except Exception as exc:
            logger.error("Failed to connect to SolidWorks: %s", exc)
            return {
                "success": False,
                "data": None,
                "message": (
                    "Could not connect to SolidWorks. "
                    f"Please start SolidWorks {get_config().solidworks_version} "
                    "manually and try again, or call solidworks_connect with "
                    "launch_if_needed=True."
                ),
                "warning": None,
                "error": {
                    "code": "SW_CONNECTION_FAILED",
                    "details": {"exception_type": type(exc).__name__},
                },
            }

    def status(self) -> dict:
        """Probe the cached COM connection and return a serializable status."""
        if self._app is None:
            return {"connected": False, "version": None}
        try:
            revision = call_or_value(self._app, "RevisionNumber")
            self._version = revision
            return {"connected": True, "version": revision}
        except Exception:
            self.disconnect()
            return {"connected": False, "version": None}

    def disconnect(self) -> None:
        """Release the COM reference."""
        self._app = None
        self._version = None

    def get_active_document(self) -> Optional[Any]:
        """Return the active document or None."""
        try:
            return self.app.ActiveDoc
        except Exception:
            return None


class SolidWorksNotRunningError(RuntimeError):
    """Raised when an operation requires SolidWorks but it is not running."""


# Global singleton used by the MCP server
_sw_app = SolidWorksApp()


def get_solidworks_app() -> SolidWorksApp:
    """Return the global SolidWorksApp instance."""
    return _sw_app
