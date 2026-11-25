"""Wrap a clean portable candidate with Inno Setup; never start app services."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def validate_package(home):
    for relative in ('ResearchInsight.exe', 'build-manifest.json',
                     'runtime/java/bin/java.exe', 'runtime/neo4j/bin/neo4j.bat'):
        if not (home / relative).is_file():
            raise ValueError(f'Missing package file: {relative}')
    for relative in ('user-data', 'runtime/neo4j/data', 'runtime/neo4j/logs', 'runtime/neo4j/run'):
        if (home / relative).exists():
            raise ValueError(f'Candidate has runtime state: {relative}; use an unused build.')
    manifest = json.loads((home / 'build-manifest.json').read_text(encoding='utf-8'))
    if 'stop-entry-v1' not in manifest.get('launcher_capabilities', []):
        raise ValueError('Rebuild the portable candidate: installer stop entry is not supported by this build.')
    if 'desktop-control-v1' not in manifest.get('launcher_capabilities', []):
        raise ValueError('Rebuild the portable candidate: desktop control window is missing.')
    if not (home / 'ResearchInsightControl/ResearchInsightControl.exe').is_file():
        raise ValueError('Desktop control executable is missing.')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--portable-dir', type=Path, required=True)
    parser.add_argument('--iscc', type=Path, help='Inno Setup 6 ISCC.exe (or discover on PATH).')
    args = parser.parse_args(argv)
    home = args.portable_dir.resolve()
    manifest = validate_package(home)
    compiler = str(args.iscc.resolve()) if args.iscc else shutil.which('ISCC.exe')
    if not compiler or not Path(compiler).is_file():
        parser.error('Install Inno Setup 6 on the build computer, then pass --iscc to ISCC.exe.')
    output = ROOT / 'dist/windows-installers' / datetime.now().strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True, exist_ok=False)
    version = manifest['built_at']
    for value in (str(home), str(output), version):
        if any(char in value for char in ('"', '\r', '\n')):
            raise ValueError('Unsupported installer build value')
    command = [compiler, f'/DPackageDir={home}', f'/DInstallerOutput={output}',
               f'/DBuildVersion={version}', str(Path(__file__).with_name('installer.iss'))]
    subprocess.run(command, cwd=ROOT, check=True)
    (output / 'installer-build.json').write_text(json.dumps({
        'portable_source': str(home), 'portable_manifest': manifest,
        'runtime_validated': False,
    }, indent=2), encoding='utf-8')
    print(f'Installer candidate ready (not runtime-validated): {output}')


if __name__ == '__main__':
    main()
