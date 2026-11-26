"""First-run configuration for a writable, isolated portable folder."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

from native import external_dll_search, neo4j_command, redacted_output
from storage import state_directory, prepare_neo4j_config


def load_credentials(path):
    if path.exists():
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or any(
            not isinstance(value.get(key), str) or len(value[key]) < length
            for key, length in (('ADMIN_PASSWORD', 12), ('SESSION_SECRET', 32),
                                ('A_ADMIN_TOKEN', 24), ('C_ADMIN_TOKEN', 24), ('NEO4J_PASSWORD', 12))
        ):
            raise RuntimeError('Portable credentials are invalid; existing data left untouched.')
        return value
    value = {key: secrets.token_urlsafe(size) for key, size in (
        ('ADMIN_PASSWORD', 18), ('SESSION_SECRET', 48), ('A_ADMIN_TOKEN', 32),
        ('C_ADMIN_TOKEN', 32), ('NEO4J_PASSWORD', 24))}
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2)
    return value


def configuration(args):
    from launch import free_port, PORTS

    home = Path(sys.executable).resolve().parent
    resources = Path(sys._MEIPASS)
    java, neo = home / 'runtime/java', home / 'runtime/neo4j'
    for path in (java / 'bin/java.exe', neo / 'bin/neo4j.bat', resources / 'frontend/dist/index.html'):
        if not path.is_file():
            raise RuntimeError(f'Incomplete portable folder: {path.name} is missing.')
    if args.java_home or args.neo4j_home:
        raise RuntimeError('Portable mode uses only its bundled Java/Neo4j; remove runtime overrides.')
    occupied = [port for port in PORTS if not free_port(port)]
    if occupied:
        raise RuntimeError(f'Ports already in use: {occupied}. Stop existing services first.')
    external = getattr(args, 'data_dir', None)
    state = state_directory(home, external)
    credential_path = state / 'credentials.json'
    if args.check and not credential_path.exists():
        raise RuntimeError('First run not initialized. Run without --check once; no changes made by check.')
    if not args.check:
        state.mkdir(parents=True, exist_ok=True)
    credentials = load_credentials(credential_path)
    # Do not inherit a developer machine's data locations, proxy service tokens
    # or Python settings. Preserve Windows and PyInstaller loader environment.
    prefixes = ('A_', 'B_', 'C_', 'D_', 'GRAPH_', 'NEO4J_', 'ADMIN_', 'SESSION_', 'PYTHON', 'CLOUD_FEEDBACK_')
    excluded = {'DATABASE_URL', 'LOCAL_DEMO', 'SAMPLE_DIR', 'KNOWLEDGE_WORKBENCH_DATA',
                'COOKIE_SECURE', 'ALLOWED_ORIGINS', 'AUTO_GRAPH_SYNC'}
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(prefixes) and key not in excluded}
    data = state / 'application'
    neo_data = state / 'neo4j/data' if external else neo / 'data'
    if external:
        conf = state / 'neo4j/conf'
        if not args.check:
            conf = prepare_neo4j_config(neo, state)
        elif not (conf / 'neo4j.conf').is_file():
            raise RuntimeError('External Neo4j configuration is missing; no changes made by check.')
        env['NEO4J_CONF'] = str(conf)
    env.update(credentials)
    env.update(JAVA_HOME=str(java), NEO4J_HOME=str(neo), NEO4J_URI='bolt://127.0.0.1:7687',
               NEO4J_USER='neo4j', NEO4J_DATABASE='neo4j', ADMIN_USERNAME='admin',
               SESSION_TTL_SECONDS='3600', COOKIE_SECURE='false',
               ALLOWED_ORIGINS='http://127.0.0.1:8001',
               A_API_BASE_URL='http://127.0.0.1:8000', C_API_BASE_URL='http://127.0.0.1:8002',
               B_API_BASE_URL='http://127.0.0.1:8001', AUTO_GRAPH_SYNC='true',
               GRAPH_SYNC_INTERVAL_SECONDS='30', C_SYNC_TIMEOUT_SECONDS='240',
               D_A_DATABASE_URL='sqlite:///' + str(data / 'a.db'), A_REPORT_ROOT=str(data / 'reports'),
               B_BATCH_REGISTRY=str(data / 'b-batches/ledger.json'), B_REVIEWS_DIR=str(data / 'b-reviews'),
               B_SOURCE_CACHE=str(data / 'b-source-cache'), D_USER_STORE=str(data / 'users.json'),
               B_SOURCE_CORPUS='', B_VOCABULARY_PATH='', B_SOURCE_OFFLINE='true',
               PYTHONUTF8='1', PYTHONUNBUFFERED='1')
    if not args.check:
        marker = state / 'neo4j-initialized.json'
        if not marker.exists():
            if (neo_data / 'databases').exists() and any((neo_data / 'databases').iterdir()):
                raise RuntimeError('Neo4j data exists without initialization marker; no password reset attempted.')
            # Neo4j's supported initial-password command accepts the password
            # as an argument. Never print this command or its captured output.
            with external_dll_search():
                result = subprocess.run(
                    neo4j_command(neo, 'dbms', 'set-initial-password',
                                  credentials['NEO4J_PASSWORD'], admin=True),
                    cwd=home, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=120)
            setup_log = state / 'neo4j-setup.log'
            setup_log.write_text(redacted_output(result.stdout, credentials), encoding='utf-8')
            if result.returncode:
                raise RuntimeError(f'Neo4j initial password setup failed (exit {result.returncode}); '
                                   f'existing credentials retained. Diagnostic log: {setup_log}')
            marker.write_text(json.dumps({'initialized': True}), encoding='utf-8')
        data.mkdir(parents=True, exist_ok=True)
        account = state / '管理员登录信息.txt'
        if not account.exists():
            with account.open('x', encoding='utf-8-sig') as handle:
                handle.write('仅供本机保管，不要随测试包分享。\n账号：admin\n密码：' +
                             credentials['ADMIN_PASSWORD'] + '\n')
        print(f'Local administrator login file: {account}')
    return env, neo
