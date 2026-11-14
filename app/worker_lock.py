"""One recovery owner per database, including across Docker containers."""
import hashlib
from contextlib import contextmanager
from sqlalchemy import text


@contextmanager
def worker_lock(factory, *, role="worker"):
    engine = factory.kw['bind']
    if engine.dialect.name == 'mysql':
        lock_name = "cv_" + role + "_" + hashlib.sha256((engine.url.database or "").encode()).hexdigest()[:32]
        with engine.connect() as connection:
            if connection.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name}) != 1:
                raise RuntimeError('Another worker is already running for this database')
            try:
                def check_owner():
                    owner = connection.scalar(text('SELECT IS_USED_LOCK(:name) = CONNECTION_ID()'), {'name': lock_name})
                    if owner != 1:
                        raise RuntimeError('Worker database lock was lost')
                yield check_owner
            finally:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
    else:
        from pathlib import Path
        import tempfile
        identity = str(Path(engine.url.database).resolve()) if engine.url.database else str(id(engine))
        path = Path(tempfile.gettempdir()) / ('tupu-' + role + '-' + hashlib.sha256(identity.encode()).hexdigest() + '.lock')
        with path.open('a+b') as handle:
            try:
                import fcntl
            except ImportError:
                import msvcrt
                handle.write(b'0'); handle.flush(); handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield lambda: None
            finally:
                if 'fcntl' in locals():
                    fcntl.flock(handle, fcntl.LOCK_UN)
                else:
                    handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
