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
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--data-dir')
    parser.add_argument('--stop', action='store_true')
    options, _ = parser.parse_known_args()
    if options.stop:
        from pathlib import Path
        from storage import state_directory
        from control import request_stop
        request_stop(state_directory(Path(sys.executable).parent, options.data_dir))
        return 0
    return run_console(launch, data_dir=options.data_dir)


if __name__ == '__main__':
    raise SystemExit(main())
