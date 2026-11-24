"""Build a fresh Windows onedir candidate; never copy developer data/config."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
RULE_RESOURCES = ('extraction.py', 'feedback.py', 'effective_export.py', 'source_enrichment.py',
                  'research_directions.py', 'text_signals.py', 'curated_vocabulary.py')


def extract_runtime(archive, destination, *, neo4j=False):
    allowed = {'bin', 'conf', 'lib', 'plugins', 'labs', 'licenses'}
    with zipfile.ZipFile(archive) as bundle:
        files = [info for info in bundle.infolist() if not info.is_dir()]
        roots = {Path(info.filename.replace('\\', '/')).parts[0] for info in files}
        if len(roots) != 1:
            raise ValueError('Runtime ZIP must have a single top-level directory')
        for info in files:
            parts = Path(info.filename.replace('\\', '/')).parts
            if any(part in ('..', '.', '') or ':' in part for part in parts) or info.filename.startswith(('/', '\\')):
                raise ValueError('Unsafe runtime ZIP path')
            relative = Path(*parts[1:])
            if not relative.parts:
                continue
            if neo4j and len(relative.parts) > 1 and relative.parts[0] not in allowed:
                continue  # Never transfer data, logs, run, import, certificates.
            target = destination / relative
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('Runtime path escapes build destination')
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java-zip', type=Path, required=True)
    parser.add_argument('--neo4j-zip', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Build on Windows x64 with the dedicated build Python.')
    if sys.version_info[:2] != (3, 11):
        parser.error('Initial candidate is validated for a Python 3.11 build environment.')
    java_zip, neo_zip = args.java_zip.resolve(), args.neo4j_zip.resolve()
    for archive in (java_zip, neo_zip):
        if not archive.is_file():
            parser.error(f'Archive not found: {archive}')
    if not (ROOT / 'frontend/dist/index.html').is_file():
        parser.error('Build the frontend first.')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    output = ROOT / 'dist/windows' / stamp
    output.mkdir(parents=True, exist_ok=False)
    work = ROOT / '.cache/windows-pyinstaller' / stamp
    work.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--console',
               '--name', 'ResearchInsight', '--distpath', str(output),
               '--workpath', str(work / 'work'), '--specpath', str(work),
               '--paths', str(ROOT), '--paths', str(Path(__file__).parent),
               '--hidden-import', 'launch', '--hidden-import', 'portable',
               '--hidden-import', 'console_stop', '--collect-all', 'argon2',
               '--collect-all', '_argon2_cffi_bindings', '--collect-all', 'pwdlib',
               '--collect-all', 'pymysql']
    for package in ('app', 'server', 'src.graph_query', 'src.knowledge_builder',
                    'examples.additional_papers_60', 'uvicorn', 'sqlalchemy.dialects.sqlite'):
        command += ['--collect-submodules', package]
    for package in ('src.knowledge_builder', 'src.graph_query'):
        command += ['--collect-data', package]
    # Explicit allowlist. No .env, runtime DB, feedback, user files or reports.
    for relative in ('frontend/dist', 'examples/week1_baseline.json', 'examples/cvpr_2024_seed.jsonl',
                     'examples/additional_papers_60'):
        source = ROOT / relative
        destination = relative if source.is_dir() else str(Path(relative).parent)
        command += ['--add-data', f'{source};{destination}']
    # B computes its public revision from exact rule source text, not bytecode.
    # Preserve these as data as well as the executable modules in PYZ.
    for name in RULE_RESOURCES:
        source = ROOT / 'src/knowledge_builder' / name
        command += ['--add-data', f'{source};src/knowledge_builder']
    command.append(str(Path(__file__).with_name('portable_entry.py')))
    print('Building application; no services will be started.', flush=True)
    subprocess.run(command, cwd=ROOT, check=True)
    home = output / 'ResearchInsight'
    extract_runtime(java_zip, home / 'runtime/java')
    extract_runtime(neo_zip, home / 'runtime/neo4j', neo4j=True)
    if not (home / 'runtime/java/bin/java.exe').is_file() or not (home / 'runtime/neo4j/bin/neo4j.bat').is_file():
        raise RuntimeError('ZIP runtime layout is not the expected Windows layout')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT))
    packages = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True)
    (home / 'build-requirements.txt').write_text(packages, encoding='utf-8')
    manifest = {'built_at': stamp, 'base_commit': revision, 'uncommitted_changes': dirty,
                'python': sys.version, 'platform': 'Windows x64',
                'seed': 'B: tracked week1 baseline (20 papers); A: baseline + 60 tracked supplemental samples',
                'runtime_archives': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in (java_zip, neo_zip)},
                'validated_on_second_machine': False}
    (home / 'build-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (home / '开始使用.txt').write_text(
        'Windows 便携版候选，尚待验证。\n'
        '请完整解压目录到可写位置，双击 ResearchInsight.exe。不要只复制 exe。\n'
        '首次运行生成自己的账号、数据库和凭据，需要等待初始化。\n'
        '管理员登录信息见 user-data/管理员登录信息.txt，不要分享该文件。\n'
        '出现 Ready 后浏览器打开。保留控制窗口，不要重复双击。\n'
        '用完在控制窗口按 Ctrl+C，等正常退出再关窗口；直接关窗尚不保证正常清理。\n'
        '启动失败时错误窗口等待回车关闭；启动日志在 user-data/logs/launcher-*.log。\n'
        '用户数据在 user-data 和 runtime/neo4j/data；再次分发前不要分享用过的目录。\n'
        '初始 B 图谱为 20 篇基线，不是开发者本机 150 篇，也不是最终数据集。\n'
        '本版不含独立安装间的云端反馈同步。\n', encoding='utf-8-sig')
    print(f'Candidate ready (not yet runtime-validated): {home}')
    print('First test locally in this fresh folder. Keep an unused copy for the second machine.')


if __name__ == '__main__':
    main()
