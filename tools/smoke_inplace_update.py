"""Exercise the frozen helper against disposable copies of actual releases."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gtleaderboard.installer import legacy_installation, write_json
from gtleaderboard.releases import MANIFEST, digest_file, prepare_update


def read_report(path, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('ok'):
                return data
            raise RuntimeError(data)
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(.2)
    raise TimeoutError(f'No successful report: {path}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('old_release', type=Path)
    parser.add_argument('new_zip', type=Path)
    args = parser.parse_args()
    root = ROOT / 'artifacts/release-update-tests' / uuid4().hex
    root.mkdir(parents=True)
    evidence = {}
    for repair in (True, False):
        name = 'nested-repair' if repair else 'in-place'
        case = root / name
        target = case / 'installation'
        shutil.copytree(args.old_release, target)
        personal = target / '내 리그.png'
        personal.write_bytes(b'personal league stays intact')
        workspace = case / f'.gtleaderboard-update-{uuid4().hex}'
        workspace.mkdir()
        if repair:
            nested = prepare_update(args.new_zip, target, target / 'models', '1.1.0')
            assert legacy_installation(nested) == target
            source = nested
        else:
            source = target
            with ZipFile(args.new_zip) as archive:
                (source / 'GTLeaderboardUpdater.exe').write_bytes(archive.read('GTLeaderboardUpdater.exe'))
        old_report, new_report = case / 'old.json', case / 'new.json'
        old = subprocess.Popen([str(source / 'GTLeaderboard.exe'), '--self-test', str(old_report)], cwd=source, creationflags=subprocess.CREATE_NO_WINDOW)
        request = workspace / 'updater-request.json'
        write_json(request, {'format': 'GTLeaderboardUpdaterRequest', 'schema': 1, 'target': str(target), 'source': str(source),
                            'mode': 'repair' if repair else 'local', 'package': str(args.new_zip.resolve()), 'pid': old.pid,
                            'arguments': ['--self-test', str(new_report)]})
        helper = workspace / 'GTLeaderboardUpdater.exe'
        shutil.copyfile(source / 'GTLeaderboardUpdater.exe', helper)
        env = __import__('os').environ.copy()
        env['QT_QPA_PLATFORM'] = 'offscreen'
        process = subprocess.Popen([str(helper), '--request', str(request)], cwd=workspace, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        result = process.wait(timeout=150)
        assert result == 0, f'Helper returned {result}'
        old.wait(timeout=15)
        previous = read_report(old_report)
        updated = read_report(new_report)
        assert previous['version'] == ('1.1.1' if repair else '1.1.0')
        assert updated['version'] == '1.1.1'
        assert Path(updated['executable']).resolve() == (target / 'GTLeaderboard.exe').resolve()
        with ZipFile(args.new_zip) as archive:
            from hashlib import sha256
            assert digest_file(target / 'GTLeaderboard.exe') == sha256(archive.read('GTLeaderboard.exe')).hexdigest()
            assert digest_file(target / 'GTLeaderboardUpdater.exe') == sha256(archive.read('GTLeaderboardUpdater.exe')).hexdigest()
        assert personal.read_bytes() == b'personal league stays intact'
        if repair:
            assert nested.exists() and (nested / 'GTLeaderboard.exe').is_file()
        else:
            assert not (target / 'GTLeaderboard-1.1.1').exists()
        assert json.loads((workspace / 'result.json').read_text())['ok']
        assert json.loads((workspace / 'updater-ready.json').read_text())['ready']
        evidence[name] = {'ok': True, 'dedicated_updater': str(helper), 'target': str(target), 'old_report': str(old_report), 'new_report': str(new_report), 'request': str(request), 'job': str(workspace / 'install-job.json')}
        print(f'{name}: passed', flush=True)
    report = root / 'report.json'
    report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(report, flush=True)


if __name__ == '__main__':
    main()
