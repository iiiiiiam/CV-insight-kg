"""Session-local Windows stop signal; never terminate unrelated processes."""
import ctypes
from ctypes import wintypes
import hashlib
import os

MUTEX_NAME = 'ResearchInsight-Running'


def event_name(state, owner_pid=None):
    identity = os.path.normcase(str(state.resolve())).encode('utf-8')
    name = 'Local\\ResearchInsight-stop-' + hashlib.sha256(identity).hexdigest()
    return name + (f'-{owner_pid}' if owner_pid is not None else '')


def kernel():
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateEventW.restype = wintypes.HANDLE
    api.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    api.OpenEventW.restype = wintypes.HANDLE
    api.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateMutexW.restype = wintypes.HANDLE
    api.SetEvent.argtypes = [wintypes.HANDLE]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    return api


class StopSignal:
    def __init__(self, state):
        self.api = kernel()
        self.handle = self.api.CreateEventW(None, True, False, event_name(state))
        self.private_handle = self.api.CreateEventW(None, True, False, event_name(state, os.getpid()))
        self.mutex = self.api.CreateMutexW(None, False, MUTEX_NAME)
        if not self.handle or not self.private_handle or not self.mutex:
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def check(self):
        if any(self.api.WaitForSingleObject(handle, 0) == 0
               for handle in (self.handle, self.private_handle)):
            raise KeyboardInterrupt

    def close(self):
        for handle in (self.handle, self.private_handle, self.mutex):
            if handle:
                self.api.CloseHandle(handle)
        self.handle = self.private_handle = self.mutex = None


def request_stop(state, owner_pid=None):
    api = kernel()
    handle = api.OpenEventW(0x0002, False, event_name(state, owner_pid))
    if not handle:
        error = ctypes.get_last_error()
        if error == 2:
            print('No running instance found for this data directory.')
            return False
        raise ctypes.WinError(error)
    try:
        if not api.SetEvent(handle):
            raise ctypes.WinError(ctypes.get_last_error())
        print('Stop requested. Wait for the original control window to finish stopping services.')
        return True
    finally:
        api.CloseHandle(handle)
