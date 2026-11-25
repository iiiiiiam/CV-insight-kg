"""Repeatable frontend -> portable -> installer build, without starting services."""
import argparse
from pathlib import Path
import shutil
import subprocess

from build_portable import ROOT, main as portable
from build_installer import main as installer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java-zip', required=True)
    parser.add_argument('--neo4j-zip', required=True)
    parser.add_argument('--iscc', required=True)
    args = parser.parse_args()
    if not Path(args.iscc).is_file():
        parser.error('--iscc must point to an installed Inno Setup 6 ISCC.exe.')
    npm = shutil.which('npm.cmd')
    if not npm:
        parser.error('npm.cmd not found. Install Node and frontend dependencies first.')
    subprocess.run([npm, '--prefix', str(ROOT / 'frontend'), 'run', 'build'], cwd=ROOT, check=True)
    home = portable(['--java-zip', args.java_zip, '--neo4j-zip', args.neo4j_zip])
    installer(['--portable-dir', str(home), '--iscc', args.iscc])


if __name__ == '__main__':
    main()
