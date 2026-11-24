"""Start bundled Java without frozen DLL paths or shell argument rewriting."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys


def neo4j_command(home, *arguments, admin=False):
    home = Path(home)
    # Match Neo4j 5.26's shipped Invoke-Neo4jUtility.ps1 Get-Java invocation,
    # without PowerShell Start-Process flattening an argument array to a string.
    java = home.parent / 'java/bin/java.exe'
    starting_class = ('org.neo4j.server.startup.Neo4jAdminCommand' if admin else
                      'org.neo4j.server.startup.Neo4jCommand')
    return [str(java), '-cp', str(home / 'lib/*'), f'-Dbasedir={home}',
            starting_class, *arguments]


@contextmanager
def external_dll_search():
    """PyInstaller documents resetting DLL search before external programs.

    Restore the frozen interpreter's search path immediately after spawning.
    See https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html
    """
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        yield
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetDllDirectoryW.argtypes = [wintypes.DWORD, wintypes.LPWSTR]
    kernel.GetDllDirectoryW.restype = wintypes.DWORD
    kernel.SetDllDirectoryW.argtypes = [wintypes.LPCWSTR]
    kernel.SetDllDirectoryW.restype = wintypes.BOOL
    size = kernel.GetDllDirectoryW(0, None)
    original = ctypes.create_unicode_buffer(size + 1)
    kernel.GetDllDirectoryW(len(original), original)
    if not kernel.SetDllDirectoryW(None):
        raise OSError('Unable to restore system DLL search for external program')
    try:
        yield
    finally:
        if not kernel.SetDllDirectoryW(original.value or None):
            raise OSError('Unable to restore application DLL search')


def redacted_output(output, credentials):
    text = output.decode('utf-8', errors='replace')
    for value in credentials.values():
        if isinstance(value, str) and value:
            text = text.replace(value, '[redacted]')
    return text
