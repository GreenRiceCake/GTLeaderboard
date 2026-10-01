from hashlib import sha256
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from test_ui import APP
from test_online_updates import Response
from gtleaderboard.domain import ValidationError
from gtleaderboard.installer import apply_job, write_json
from gtleaderboard.online_updates import UpdateCancelled, default_manifest_url, parse_manifest
from gtleaderboard.releases import MANIFEST
from gtleaderboard.updater import UpdaterWindow, update_request
from gtleaderboard.updater_launch import UPDATER_NAME, read_request, start_updater, updater_ready
from tools.make_update_manifest import make_manifest


class Signal:
    def __init__(self):
        self.values = []

    def emit(self, *args):
        self.values.append(args)


class Worker:
    def __init__(self, cancelled=False):
        self.cancelled = cancelled
        for name in ('phase', 'release', 'progress', 'applying'):
            setattr(self, name, Signal())

    def isInterruptionRequested(self):
        return self.cancelled


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / 'artifacts/tests'
        self.work = self.root / f'.gtleaderboard-update-{uuid4().hex}'
        self.target = self.root / f'updater-target-{uuid4().hex}'
        self.work.mkdir(parents=True)
        self.target.mkdir()
        (self.target / 'GTLeaderboard.exe').write_bytes(b'old app')
        (self.target / UPDATER_NAME).write_bytes(b'old updater')
        (self.target / 'VERSION.txt').write_text('1.1.0')
        (self.target / 'league.png').write_bytes(b'personal league')
        self.package = self.work / 'new.zip'
        payload = {'GTLeaderboard.exe': b'new app', UPDATER_NAME: b'new updater', 'models/test.onnx': b'model', 'VERSION.txt': b'9.0.0'}
        info = {'format': 'GTLeaderboardRelease', 'schemaVersion': 1, 'version': '9.0.0', 'platform': 'windows-x64', 'kind': 'full', 'leagueSchema': {'min': 1, 'max': 4}, 'model': {'file': 'models/test.onnx', 'sha256': sha256(b'model').hexdigest()}, 'files': {name: {'size': len(data), 'sha256': sha256(data).hexdigest()} for name, data in payload.items()}}
        with ZipFile(self.package, 'w') as archive:
            for name, data in payload.items():
                archive.writestr(name, data)
            archive.writestr(MANIFEST, json.dumps(info))
        notes = self.work / 'notes.md'
        notes.write_text('# New\n\n- update\n')
        manifest = make_manifest(self.package, self.work / 'update_manifest.json', notes)
        self.release = parse_manifest(manifest.read_bytes())

    def tearDown(self):
        for path in (self.work, self.target):
            if path.resolve().parent != self.root.resolve():
                raise RuntimeError('Cleanup escaped test workspace')
            shutil.rmtree(path)

    def request(self, mode):
        return {'mode': mode, 'target': self.target, 'source': self.target, 'workspace': self.work,
                'pid': 0, 'arguments': [str(self.target / 'league.png')], 'package': str(self.package)}

    def test_launcher_copies_only_dedicated_updater_and_passes_actual_install_location(self):
        with patch('gtleaderboard.updater_launch.temporary_workspace', return_value=self.work), patch('gtleaderboard.updater_launch.subprocess.Popen') as launch:
            path = start_updater(self.target, self.target, 'online', [str(self.target / 'league.png')])
        self.assertEqual((self.work / UPDATER_NAME).read_bytes(), b'old updater')
        self.assertFalse((self.work / 'GTLeaderboard.exe').exists())
        request = read_request(path)
        self.assertEqual(request['target'], self.target)
        self.assertEqual(request['mode'], 'online')
        self.assertEqual(launch.call_args.args[0][1], '--request')

    def test_missing_updater_is_a_clear_error_before_app_exit(self):
        (self.target / UPDATER_NAME).unlink()
        with self.assertRaisesRegex(ValidationError, 'GTLeaderboardUpdater.exe'):
            start_updater(self.target, self.target, 'online')

    def test_readiness_requires_exact_updater_executable_path(self):
        request = self.work / 'updater-request.json'
        self.assertFalse(updater_ready(request))
        write_json(self.work / 'updater-ready.json', {'ready': True, 'executable': str(self.target / 'GTLeaderboard.exe')})
        self.assertFalse(updater_ready(request))
        write_json(self.work / 'updater-ready.json', {'ready': True, 'executable': str(self.work / UPDATER_NAME)})
        self.assertTrue(updater_ready(request))

    def test_online_updater_downloads_verified_zip_replaces_itself_and_preserves_league(self):
        worker = Worker()
        def install(job):
            return apply_job(job, wait=lambda _: None, launch=lambda *_: None)
        with patch('gtleaderboard.updater.fetch_manifest', return_value=self.release) as check, patch('gtleaderboard.online_updates.open_https', return_value=Response(self.package.read_bytes())), patch('gtleaderboard.updater.apply_job', side_effect=install):
            target = update_request(self.request('online'), worker)
        self.assertEqual(check.call_args.args[0], default_manifest_url())
        self.assertEqual(target, self.target)
        self.assertEqual((target / UPDATER_NAME).read_bytes(), b'new updater')
        self.assertEqual((target / 'GTLeaderboard.exe').read_bytes(), b'new app')
        self.assertEqual((target / 'league.png').read_bytes(), b'personal league')
        self.assertFalse((target / 'GTLeaderboard-9.0.0').exists())
        self.assertTrue(worker.applying.values)
        self.assertTrue(worker.progress.values)

    def test_cancel_after_local_verification_never_replaces_files(self):
        with patch('gtleaderboard.updater.apply_job') as install:
            with self.assertRaises(UpdateCancelled):
                update_request(self.request('local'), Worker(True))
            install.assert_not_called()
        self.assertEqual((self.target / 'GTLeaderboard.exe').read_bytes(), b'old app')

    def test_dialog_shows_literal_changelog_and_uses_existing_directory(self):
        window = UpdaterWindow(self.target)
        window.show_release(self.release)
        window.refresh()
        self.assertTrue(window.install.isEnabled())
        self.assertIn(str(self.target), window.location.text())
        self.assertIn('1.1.0', window.version.text())
        window.begin_apply()
        self.assertFalse(window.cancel.isEnabled())
        window.close()

    def test_request_rejects_invalid_process_id(self):
        with patch('gtleaderboard.updater_launch.temporary_workspace', return_value=self.work), patch('gtleaderboard.updater_launch.subprocess.Popen'):
            request = start_updater(self.target, self.target, 'online')
        data = json.loads(request.read_text())
        data['pid'] = -1
        request.write_text(json.dumps(data))
        with self.assertRaises(ValidationError):
            read_request(request)


if __name__ == '__main__':
    unittest.main()
