"""Build allowlisted, secret-free ZIPs without installing anything or using network."""
import argparse
from pathlib import Path
import zipfile


SOURCE = Path(__file__).resolve().parent


def package(target, files):
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = (0o100755 if name == 'scf_bootstrap' else 0o100644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, (SOURCE / name).read_bytes().replace(b'\r\n', b'\n'))
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == files
    print(target.resolve())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=SOURCE.parents[2] / '.cache/cloudbase/delivery')
    args = parser.parse_args()
    package(args.output / 'ri-feedback-api-upload.zip', ['index.js', 'package.json', 'scf_bootstrap'])
    package(args.output / 'ri-feedback-client.zip', ['client.py', 'CLIENT.md'])


if __name__ == '__main__':
    main()
