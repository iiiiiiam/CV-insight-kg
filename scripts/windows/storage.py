"""Storage selection shared by the frozen launcher and its console wrapper."""
from pathlib import Path
import shutil


def state_directory(home, data_dir=None):
    if data_dir:
        path = Path(data_dir)
        if not path.is_absolute():
            raise RuntimeError('--data-dir must be an absolute path.')
        return path.resolve()
    return Path(home) / 'user-data'


def prepare_neo4j_config(neo, state):
    """Create external configuration once; never rewrite user configuration."""
    conf = state / 'neo4j/conf'
    target = conf / 'neo4j.conf'
    if target.exists():
        return conf
    conf.mkdir(parents=True, exist_ok=True)
    for source in (neo / 'conf').iterdir():
        if source.is_file() and source.name != 'neo4j.conf':
            destination = conf / source.name
            if not destination.exists():
                shutil.copyfile(source, destination)
    settings = {
        'server.directories.data': state / 'neo4j/data',
        'server.directories.logs': state / 'neo4j/logs',
        'server.directories.run': state / 'neo4j/run',
        'server.directories.import': state / 'neo4j/import',
        'server.directories.transaction.logs.root': state / 'neo4j/data/transactions',
        'server.logs.config': conf / 'server-logs.xml',
        'server.logs.user.config': conf / 'user-logs.xml',
    }
    original = (neo / 'conf/neo4j.conf').read_text(encoding='utf-8-sig')
    lines = [line for line in original.splitlines()
             if line.split('=', 1)[0].strip() not in settings]
    lines.extend(f'{key}={value.as_posix()}' for key, value in settings.items())
    with target.open('x', encoding='utf-8') as handle:
        handle.write('\n'.join(lines) + '\n')
    return conf
