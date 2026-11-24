"""Frozen dispatch: permit only the bundled services, never arbitrary modules."""
import mimetypes
import multiprocessing
import runpy
import sys

MODULES = {'server.run', 'server.run_a', 'server.run_c', 'app.worker'}


def main():
    multiprocessing.freeze_support()
    mimetypes.add_type('application/javascript', '.js')
    if len(sys.argv) == 3 and sys.argv[1] == '--internal-module':
        module = sys.argv[2]
        if module not in MODULES:
            raise SystemExit('Unsupported internal service')
        sys.argv = [sys.argv[0]]
        runpy.run_module(module, run_name='__main__')
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == '--console-stop':
        from console_stop import request_stop
        return request_stop(int(sys.argv[2]))
    from launch import main as launch
    if '--check' in sys.argv:
        return launch()  # Preserve read-only preflight behavior.
    from console_ui import run_console
    return run_console(launch)


if __name__ == '__main__':
    raise SystemExit(main())
