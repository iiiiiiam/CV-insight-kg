"""Keep portable startup failures visible and record supervisor output."""
from contextlib import contextmanager
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile


class Tee:
    def __init__(self, console, logfile):
        self.console, self.logfile = console, logfile

    def write(self, text):
        self.logfile.write(text)
        self.logfile.flush()
        if self.console is not None:
            try:
                self.console.write(text)
                self.console.flush()
            except (OSError, UnicodeError):
                pass  # The UTF-8 file still preserves diagnostic output.
        return len(text)

    def flush(self):
        self.logfile.flush()
        if self.console is not None:
            try:
                self.console.flush()
            except OSError:
                pass


@contextmanager
def single_instance(path=None):
    """OS-backed lock; a terminated process cannot leave a stale held lock."""
    import msvcrt
    path = Path(path) if path else Path(tempfile.gettempdir()) / 'ResearchInsight-portable.lock'
    with path.open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError('ResearchInsight is already starting or running. '
                               'Use the existing control window; do not launch another copy.') from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def pause_on_failure(code, stream=None, input_fn=input):
    stream = sys.stdin if stream is None else stream
    if code and stream is not None and stream.isatty():
        try:
            input_fn('Startup failed. Read the error above. Press Enter to close this window...')
        except (EOFError, KeyboardInterrupt, OSError):
            pass


def run_console(callback, home=None, data_dir=None):
    home = Path(home) if home is not None else Path(sys.executable).parent
    original_out, original_err = sys.stdout, sys.stderr
    code = 1
    try:
        from storage import state_directory
        directory = state_directory(home, data_dir) / 'logs'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'launcher-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}.log'
        with path.open('x', encoding='utf-8', buffering=1) as logfile:
            sys.stdout, sys.stderr = Tee(original_out, logfile), Tee(original_err, logfile)
            try:
                print(f'Startup log: {path}')
                print('Keep this control window open. Ctrl+C stops the software. Do not open it twice.')
                with single_instance():
                    code = callback()
            except KeyboardInterrupt:
                print('Startup cancelled.')
                code = 0
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
            except Exception as exc:
                # Do not dump environment/arguments or arbitrary tracebacks.
                print(f'ERROR: {exc}' if isinstance(exc, RuntimeError) else
                      f'ERROR: {type(exc).__name__}; inspect runtime/configuration.', file=sys.stderr)
                code = 1
            finally:
                print(f'Exit code: {code}; startup log: {path}')
                sys.stdout, sys.stderr = original_out, original_err
    except OSError:
        print('ERROR: Cannot create startup log. Extract to a writable folder.', file=original_err)
        code = 1
    pause_on_failure(code)
    return code
