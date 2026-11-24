"""Local Windows supervisor. Uses existing runtime/configuration; installs nothing."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
from urllib.error import URLError
import webbrowser

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(ROOT))
PORTS = (7474, 7687, 8000, 8001, 8002)


def free_port(port):
    with socket.socket() as sock:
        if os.name == 'nt':
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def runtime_path(value, pattern, marker):
    if value:
        path = Path(value).resolve()
    else:
        candidates = [p for p in ROOT.glob(pattern) if (p / marker).is_file()]
        if len(candidates) != 1:
            raise RuntimeError('Specify a unique runtime with --java-home / --neo4j-home.')
        path = candidates[0]
    if not (path / marker).is_file():
        raise RuntimeError(f'Missing runtime file: {path / marker}')
    return path


def configuration(args):
    if getattr(sys, 'frozen', False):
        from portable import configuration as portable_configuration
        return portable_configuration(args)
    from dotenv import dotenv_values

    # Resolve D/B settings from the same server/.env as Settings.from_env.
    env = os.environ.copy()
    for name in ('server/.env',):
        for key, value in dotenv_values(ROOT / name).items():
            if value is not None:
                env.setdefault(key, value)
    java = runtime_path(args.java_home, '.cache/windows-runtime/java/*', 'bin/java.exe')
    neo = runtime_path(args.neo4j_home, '.cache/windows-runtime/neo4j/*', 'bin/neo4j.bat')
    for filename in ('server/.env', 'frontend/dist/index.html'):
        if not (ROOT / filename).is_file():
            raise RuntimeError(f'Missing {filename}; follow setup/build instructions first.')
    if len(env.get('ADMIN_PASSWORD', '')) < 12 or len(env.get('SESSION_SECRET', '')) < 32:
        raise RuntimeError('Existing administrator configuration is incomplete.')
    if not env.get('A_ADMIN_TOKEN') or not (env.get('C_ADMIN_TOKEN') or env.get('GRAPH_ADMIN_TOKEN')):
        raise RuntimeError('Existing service token configuration is incomplete.')
    # This initial supervisor deliberately reuses the already tested preview data.
    data = ROOT / 'data/windows-preview'
    if not data.is_dir():
        raise RuntimeError('Existing data/windows-preview is missing; no replacement data created.')
    env.update(JAVA_HOME=str(java), NEO4J_HOME=str(neo),
               NEO4J_URI='bolt://127.0.0.1:7687', NEO4J_USER='neo4j', NEO4J_DATABASE='neo4j',
               D_A_DATABASE_URL='sqlite:///' + str(data / 'a.db'),
               A_REPORT_ROOT=str(data / 'reports'),
               B_BATCH_REGISTRY=str(data / 'b-batches/ledger.json'),
               B_REVIEWS_DIR=str(data / 'b-reviews'), B_SOURCE_CACHE=str(data / 'b-source-cache'),
               D_USER_STORE=str(data / 'users.json'), B_SOURCE_OFFLINE='true',
               A_API_BASE_URL='http://127.0.0.1:8000', C_API_BASE_URL='http://127.0.0.1:8002',
               AUTO_GRAPH_SYNC='true', COOKIE_SECURE='false', ALLOWED_ORIGINS='http://127.0.0.1:8001',
               PYTHONUTF8='1', PYTHONUNBUFFERED='1')
    # Preserve the resolved source/vocabulary settings instead of relying on
    # PowerShell's ambiguous empty-environment-variable behavior.
    for name in ('B_SOURCE_CORPUS', 'B_VOCABULARY_PATH'):
        if env.get(name):
            candidate = Path(env[name])
            if not candidate.is_absolute():
                candidate = ROOT / candidate
            if not candidate.is_file():
                raise RuntimeError(f'{name} points to a missing file; configuration left unchanged.')
            print(f'{name}: {candidate}')
    occupied = [p for p in PORTS if not free_port(p)]
    if occupied:
        raise RuntimeError(f'Ports already in use: {occupied}. Stop existing services first.')
    return env, neo


class Supervisor:
    def __init__(self, env, logs):
        self.env, self.logs, self.children = env, logs, []

    def start(self, name, command):
        stream = (self.logs / f'{name}.log').open('wb')
        options = dict(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        if name == 'neo4j':
            # JVM Ctrl+Break produces a thread dump. Give Neo4j its own hidden
            # console so a helper can send genuine Ctrl+C without affecting
            # the user's terminal or unrelated processes.
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            options = dict(creationflags=subprocess.CREATE_NEW_CONSOLE,
                           startupinfo=startup, stdin=subprocess.DEVNULL)
        try:
            from native import external_dll_search
            # Only Neo4j is external; bundled Python services retain their DLLs.
            if name == 'neo4j':
                with external_dll_search():
                    process = subprocess.Popen(command, cwd=ROOT, env=self.env,
                                               stdout=stream, stderr=subprocess.STDOUT, **options)
            else:
                process = subprocess.Popen(command, cwd=ROOT, env=self.env,
                                           stdout=stream, stderr=subprocess.STDOUT, **options)
        finally:
            stream.close()
        self.children.append((name, process))
        print(f'Started {name}, PID {process.pid}', flush=True)

    def wait(self, url, *, synced=False, timeout=180):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for name, process in self.children:
                if process.poll() is not None:
                    raise RuntimeError(f'{name} exited; inspect its log.')
            try:
                with urlopen(url, timeout=3) as response:
                    body = response.read()
                # Neo4j's HTTP root may serve HTML rather than JSON.
                if ':7474/' in url:
                    return {}
                result = json.loads(body)
                if not synced or result.get('graph_sync', {}).get('state') == 'synced':
                    return result
                if result.get('graph_sync', {}).get('state') == 'error':
                    diagnostic = self.logs / 'graph-sync-error.json'
                    diagnostic.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                    code = result.get('graph_sync', {}).get('error', {}).get('code', 'unknown')
                    raise RuntimeError(f'Graph synchronization failed ({code}); diagnostic: {diagnostic}')
            except (URLError, TimeoutError, OSError, ValueError):
                pass
            time.sleep(1)
        raise RuntimeError(f'Readiness timed out: {url}')

    def stop(self):
        # Ignore additional Ctrl+C while orderly shutdown is in progress.
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            for name, process in reversed(self.children):
                if process.poll() is not None:
                    continue
                print(f'Stopping {name}...', flush=True)
                try:
                    if name == 'neo4j':
                        result = subprocess.run(
                            ([sys.executable, '--console-stop', str(process.pid)]
                             if getattr(sys, 'frozen', False) else
                             [sys.executable, str(Path(__file__).with_name('console_stop.py')), str(process.pid)]),
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=10, check=False)
                        if result.returncode:
                            raise OSError('Dedicated console stop request failed')
                    else:
                        process.send_signal(signal.CTRL_BREAK_EVENT)
                    process.wait(timeout=60 if name == 'neo4j' else 25)
                except (OSError, subprocess.TimeoutExpired):
                    # Only the process tree created by this supervisor, never
                    # all Python/Java processes or arbitrary port owners.
                    if process.poll() is None:
                        print(f'{name}: graceful stop timed out; stopping owned process tree.')
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       check=False)
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            print(f'WARNING: {name} did not exit; inspect PID {process.pid}.')
        finally:
            signal.signal(signal.SIGINT, previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java-home')
    parser.add_argument('--neo4j-home')
    parser.add_argument('--check', action='store_true', help='Check configuration only; start nothing.')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This launcher supports Windows only.')
    supervisor = None
    try:
        env, neo = configuration(args)
        print(f'Runtime: {sys.executable}\nData: {Path(env["D_USER_STORE"]).parent}')
        if args.check:
            print('Preflight passed. No services started; credentials not verified against Neo4j.')
            return 0
        # Prompt each time for this developer preview; do not persist a password.
        password = (env.get('NEO4J_PASSWORD') if getattr(sys, 'frozen', False) else
                    getpass.getpass('Existing local Neo4j password (hidden): '))
        if not password:
            raise RuntimeError('Password was empty; nothing started.')
        log_root = (Path(sys.executable).parent / 'user-data/logs'
                    if getattr(sys, 'frozen', False) else ROOT / '.cache/windows-launcher')
        logs = log_root / time.strftime('%Y%m%d-%H%M%S')
        logs.mkdir(parents=True, exist_ok=False)
        print(f'Logs: {logs}\nKeep this terminal open. Ctrl+C stops this run.')
        supervisor = Supervisor(dict(env), logs)
        # Neo4j itself does not need the client password in its environment.
        supervisor.env.pop('NEO4J_PASSWORD', None)
        if getattr(sys, 'frozen', False):
            from native import neo4j_command
            neo_command = neo4j_command(neo, 'console')
        else:
            neo_command = ['cmd.exe', '/d', '/c', str(neo / 'bin/neo4j.bat'), 'console']
        supervisor.start('neo4j', neo_command)
        supervisor.wait('http://127.0.0.1:7474/', timeout=120)
        supervisor.env = dict(env, NEO4J_PASSWORD=password)
        from server.process_command import module_command
        supervisor.start('C', module_command('server.run_c'))
        supervisor.wait('http://127.0.0.1:8002/api/health')
        # Only C requires the database password.
        supervisor.env = dict(env)
        supervisor.env.pop('NEO4J_PASSWORD', None)
        supervisor.start('A', module_command('server.run_a'))
        supervisor.wait('http://127.0.0.1:8000/health')
        d_command = ([sys.executable, '--internal-module', 'server.run']
                     if getattr(sys, 'frozen', False) else [sys.executable, '-c',
            "import mimetypes,runpy; mimetypes.add_type('application/javascript','.js'); "
            "runpy.run_module('server.run',run_name='__main__')"])
        supervisor.start('D', d_command)
        supervisor.wait('http://127.0.0.1:8001/api/health', synced=True, timeout=300)
        print('Ready: http://127.0.0.1:8001/research/papers?tab=overview')
        if not args.no_browser:
            webbrowser.open('http://127.0.0.1:8001/research/papers?tab=overview')
        while True:
            for name, process in supervisor.children:
                if process.poll() is not None:
                    raise RuntimeError(f'{name} exited unexpectedly; inspect logs.')
            time.sleep(1)
    except KeyboardInterrupt:
        print('\nStop requested.')
        return 0
    except Exception as exc:
        # Avoid leaking credentials through arbitrary dependency exceptions.
        if isinstance(exc, RuntimeError):
            print(f'ERROR: {exc}', file=sys.stderr)
        else:
            print(f'ERROR: {type(exc).__name__}; check runtime paths/configuration.', file=sys.stderr)
        return 1
    finally:
        if supervisor:
            supervisor.stop()


if __name__ == '__main__':
    raise SystemExit(main())
