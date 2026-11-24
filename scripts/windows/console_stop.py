"""Send Ctrl+C only to the dedicated console created for Neo4j.

Run as a short-lived helper so the supervisor never detaches its own console.
Windows CTRL_C_EVENT cannot target a process group: the target must therefore
have a separate console. Never call this against a shared user console.
"""
import ctypes
from ctypes import wintypes
import sys
import time


def request_stop(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.AttachConsole.argtypes = [wintypes.DWORD]
    kernel.AttachConsole.restype = wintypes.BOOL
    kernel.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
    kernel.SetConsoleCtrlHandler.restype = wintypes.BOOL
    kernel.GenerateConsoleCtrlEvent.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.GenerateConsoleCtrlEvent.restype = wintypes.BOOL
    kernel.FreeConsole()
    if not kernel.AttachConsole(pid):
        return 1
    try:
        if not kernel.SetConsoleCtrlHandler(None, True):
            return 2
        if not kernel.GenerateConsoleCtrlEvent(0, 0):
            return 3
        time.sleep(0.3)  # Allow event delivery before detaching the helper.
        return 0
    finally:
        kernel.FreeConsole()


if __name__ == '__main__':
    raise SystemExit(request_stop(int(sys.argv[1])))
