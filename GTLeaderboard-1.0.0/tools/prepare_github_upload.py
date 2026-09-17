"""Collect explicit public inputs and the matching release manifest for upload."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gtleaderboard import __version__
from gtleaderboard.releases import digest_file, inspect_package

PRIVATE_FIXTURE_TESTS = {
    'test_export_png.py', 'test_png_data.py', 'test_recorded_points.py',
}


def prepare(destination):
    manifest_path = ROOT / 'dist/update_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    package = ROOT / 'dist' / f'GTLeaderboard-{__version__}-windows-x64-full.zip'
    metadata = manifest['transactional_package']
    if (manifest['version'] != __version__ or metadata['size'] != package.stat().st_size
            or metadata['sha256'] != digest_file(package)):
        raise ValueError('Build the current version first: manifest and ZIP do not match.')
    inspect_package(package)
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Choose an empty destination; existing files are never overwritten.')
    files = list((ROOT / 'gtleaderboard').rglob('*.py'))
    files += list((ROOT / 'gtleaderboard/data').glob('*.json'))
    files += [p for p in (ROOT / 'tests').glob('test_*.py') if p.name not in PRIVATE_FIXTURE_TESTS]
    files += [p for p in (ROOT / 'packaging').rglob('*') if p.is_file() and p.suffix in {'.txt', '.md'}]
    files += [ROOT / name for name in (
        '.gitignore', '.github/workflows/release.yml', 'run.pyw',
        'requirements.txt', 'requirements-build.txt', 'BUILDING.md', 'UPDATING.md',
        'RELEASE_NOTES.md', 'models/README.md', 'examples/demo.gtlb',
        'tools/build_release.py', 'tools/setup_ocr.py', 'tools/fetch_release_licenses.py',
        'tools/smoke_release.py', 'tools/make_update_manifest.py',
        'tools/update_tracks.py', 'tools/prepare_github_upload.py',
    )]
    for source in files:
        if not source.is_file():
            raise FileNotFoundError(source)
    destination.mkdir(parents=True, exist_ok=True)
    for source in files:
        target = destination / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    shutil.copyfile(ROOT / 'packaging/README_GITHUB.md', destination / 'README.md')
    shutil.copyfile(manifest_path, destination / 'update_manifest.json')
    print(f'{destination}\n{len(files) + 2} public files; version {__version__}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', nargs='?', type=Path,
                        default=ROOT / 'github-upload' / f'GTLeaderboard-{__version__}')
    prepare(parser.parse_args().destination)
