"""Generate public update metadata from the exact ZIP that will be uploaded."""
import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gtleaderboard.online_updates import UPDATER_PROTOCOL, https_url, parse_manifest
from gtleaderboard.releases import MANIFEST, digest_file, inspect_package
from gtleaderboard.storage import atomic_write

REPOSITORY = 'GreenRiceCake/GTLeaderboard'


def make_manifest(package_path, output_path, notes_path, repository=REPOSITORY, download_url=None):
    package_path = Path(package_path)
    release = inspect_package(package_path)
    version = release.manifest['version']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Repository must be OWNER/REPOSITORY.')
    url = https_url(download_url or f'https://github.com/{repository}/releases/download/v{version}/{quote(package_path.name)}')
    notes = Path(notes_path).read_text(encoding='utf-8').splitlines()
    changelog = []
    for line in notes[1:]:
        if line.startswith('#'):
            break
        changelog.append(line)
    document = {
        'app': 'GTLeaderboard', 'schema_version': 1,
        'version': version, 'title': f'GTLeaderboard v{version} 업데이트',
        'changelog': '\n'.join(changelog).strip(), 'update_type': 'zip',
        'download_url': url, 'min_updater_protocol': UPDATER_PROTOCOL,
        'transactional_package': {'type': 'zip', 'url': url, 'size': package_path.stat().st_size, 'sha256': digest_file(package_path), 'package_manifest': MANIFEST},
    }
    content = (json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    parse_manifest(content)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(output_path, content)
    return output_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('package', type=Path)
    parser.add_argument('--repository', default=REPOSITORY)
    parser.add_argument('--download-url')
    parser.add_argument('--notes', type=Path, default=ROOT / 'RELEASE_NOTES.md')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/update_manifest.json')
    args = parser.parse_args()
    print(make_manifest(args.package, args.output, args.notes, args.repository, args.download_url))
