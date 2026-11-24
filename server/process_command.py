"""Child service command for source checkouts and the Windows frozen bundle."""
import sys


def module_command(module):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--internal-module', module]
    return [sys.executable, '-m', module]
