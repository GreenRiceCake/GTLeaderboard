from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import shutil
import time
import unittest
from unittest.mock import patch
from urllib.request import Request
from uuid import uuid4
from zipfile import ZipFile

from PySide6.QtWidgets import QDialog
from test_ui import APP
from gtleaderboard import __version__
from gtleaderboard.domain import ValidationError
from gtleaderboard.online_updates import HttpsRedirect, MAX_MANIFEST, UpdateCancelled, default_manifest_url, download_and_prepare, fetch_manifest, https_url, parse_manifest
from gtleaderboard.releases import MANIFEST
from gtleaderboard.update_ui import UpdateDialog, StartupUpdateCheck
from gtleaderboard.ui import MainWindow
from tools.make_update_manifest import make_manifest


class Response(BytesIO):
    def __init__(self, content, headers=None):
        super().__init__(content)
        self.headers = headers or {}
        self.status = 200

    def geturl(self):
        return 'https://example.com/file'


class Settings:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None, **kwargs):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        pass


class OnlineUpdateTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / 'artifacts/tests'
        self.directory = self.root / uuid4().hex
        self.directory.mkdir(parents=True)
        self.zip = self.directory / 'test-full.zip'
        payload = {'GTLeaderboard.exe': b'fake exe', 'models/test.onnx': b'test model'}
        model = {'file': 'models/test.onnx', 'sha256': sha256(b'test model').hexdigest()}
        package = {'format': 'GTLeaderboardRelease', 'schemaVersion': 1, 'version': '9.0.0', 'platform': 'windows-x64', 'kind': 'full', 'leagueSchema': {'min': 1, 'max': 3}, 'model': model, 'files': {name: {'size': len(data), 'sha256': sha256(data).hexdigest()} for name, data in payload.items()}}
        with ZipFile(self.zip, 'w') as archive:
            for name, value in payload.items():
                archive.writestr(name, value)
            archive.writestr(MANIFEST, json.dumps(package))
        self.notes = self.directory / 'notes.md'
        self.notes.write_text('# New release\n\n- 한글 변경 사항\n\n## Old release\nOld notes', encoding='utf-8')
        self.manifest = make_manifest(self.zip, self.directory / 'update_manifest.json', self.notes)
        self.raw = self.manifest.read_bytes()
        self.release = parse_manifest(self.raw)
        self.old = self.directory / 'league.png'
        self.old.write_bytes(b'original user league')

    def tearDown(self):
        if self.directory.resolve().parent != self.root.resolve():
            raise RuntimeError('Cleanup escaped test workspace')
        shutil.rmtree(self.directory)

    def test_generated_manifest_uses_actual_zip_and_latest_notes(self):
        data = json.loads(self.raw)
        self.assertEqual(data['version'], '9.0.0')
        self.assertEqual(data['title'], 'GTLeaderboard v9.0.0 업데이트')
        self.assertEqual(data['transactional_package']['size'], self.zip.stat().st_size)
        self.assertEqual(data['transactional_package']['sha256'], sha256(self.zip.read_bytes()).hexdigest())
        self.assertIn('/GreenRiceCake/GTLeaderboard/releases/download/v9.0.0/', self.release.url)
        self.assertNotIn('Old notes', self.release.changelog)

    def test_rejects_wrong_app_protocol_and_ambiguous_or_unsafe_metadata(self):
        mutations = [lambda d: d.update(app='GTMate'), lambda d: d.update(schema_version=True), lambda d: d.update(min_updater_protocol=2), lambda d: d.update(min_updater_protocol=False), lambda d: d.update(download_url='https://example.com/other.zip'), lambda d: d['transactional_package'].update(size=True), lambda d: d['transactional_package'].update(sha256='bad'), lambda d: d['transactional_package'].update(package_manifest='../file'), lambda d: d['transactional_package'].update(url='http://example.com/file')]
        for mutate in mutations:
            data = json.loads(self.raw)
            mutate(data)
            with self.assertRaises(ValidationError):
                parse_manifest(json.dumps(data).encode())
        with self.assertRaises(ValidationError):
            parse_manifest(b'{"version":"1.0.0","version":"2.0.0"}')
        with self.assertRaises(ValidationError):
            parse_manifest(b'x' * (MAX_MANIFEST + 1))

    def test_https_only_including_redirects_and_markdown_rejection(self):
        for url in ('http://example.com/file', 'file:///C:/data', '[link](https://example.com/file)', 'https://user:pass@example.com/file', 'https://example.com/file#fragment', 'https://example.com/a b'):
            with self.assertRaises(ValidationError):
                https_url(url)
        redirect = HttpsRedirect(lambda: False, time.monotonic() + 20)
        with self.assertRaises(ValidationError):
            redirect.redirect_request(Request('https://example.com/start'), None, 302, '', {}, 'http://example.com/target')

    def test_fetch_streams_json_and_limits_response(self):
        with patch('gtleaderboard.online_updates.open_https', return_value=Response(self.raw)):
            self.assertEqual(fetch_manifest('https://example.com/manifest'), self.release)
        with patch('gtleaderboard.online_updates.open_https', return_value=Response(b' ' * (MAX_MANIFEST + 1))):
            with self.assertRaises(ValidationError):
                fetch_manifest('https://example.com/manifest')

    def test_download_verifies_and_prepares_without_touching_old_files(self):
        with patch('gtleaderboard.online_updates.open_https', return_value=Response(self.zip.read_bytes())):
            target = download_and_prepare(self.release, self.directory, self.directory / 'no-model', '0.1.0')
        self.assertEqual((target / 'GTLeaderboard.exe').read_bytes(), b'fake exe')
        self.assertEqual((target / 'models/test.onnx').read_bytes(), b'test model')
        self.assertEqual(self.old.read_bytes(), b'original user league')
        self.assertFalse(list(self.directory.glob('.gtleaderboard-*')))

    def test_bad_hash_truncation_overflow_and_header_mismatch_leave_no_partial_update(self):
        payload = self.zip.read_bytes()
        scenarios = [(replace(self.release, sha256='0' * 64), payload, {}), (self.release, payload[:-1], {}), (self.release, payload + b'extra', {}), (self.release, payload, {'Content-Length': '1'})]
        for release, content, headers in scenarios:
            with patch('gtleaderboard.online_updates.open_https', return_value=Response(content, headers)):
                with self.assertRaises(ValidationError):
                    download_and_prepare(release, self.directory, self.directory, '0.1.0')
            self.assertFalse((self.directory / 'GTLeaderboard-9.0.0').exists())
            self.assertFalse(list(self.directory.glob('.gtleaderboard-*')))
            self.assertEqual(self.old.read_bytes(), b'original user league')

    def test_inner_version_mismatch_is_rejected(self):
        with patch('gtleaderboard.online_updates.open_https', return_value=Response(self.zip.read_bytes())):
            with self.assertRaisesRegex(ValidationError, '버전'):
                download_and_prepare(replace(self.release, version='9.1.0'), self.directory, self.directory, '0.1.0')
        self.assertFalse((self.directory / 'GTLeaderboard-9.1.0').exists())

    def test_cancel_during_download_cleans_temporary_file(self):
        cancelled = False
        def progress(*_):
            nonlocal cancelled
            cancelled = True
        with patch('gtleaderboard.online_updates.open_https', return_value=Response(self.zip.read_bytes())):
            with self.assertRaises(UpdateCancelled):
                download_and_prepare(self.release, self.directory, self.directory, '0.1.0', progress, lambda: cancelled)
        self.assertFalse(list(self.directory.glob('.gtleaderboard-*')))
        self.assertEqual(self.old.read_bytes(), b'original user league')

    def test_existing_target_and_same_version_fail_before_network(self):
        with patch('gtleaderboard.online_updates.open_https') as network:
            with self.assertRaises(ValidationError):
                download_and_prepare(self.release, self.directory, self.directory, '9.0.0')
            (self.directory / 'GTLeaderboard-9.0.0').mkdir()
            with self.assertRaises(ValidationError):
                download_and_prepare(self.release, self.directory, self.directory, '0.1.0')
            network.assert_not_called()

    def test_ui_new_equal_older_version_and_plain_changelog(self):
        dialog = UpdateDialog(settings=Settings())
        for version, available in (('9.0.0', True), (__version__, False), ('0.0.1', False)):
            dialog.online_checked(replace(self.release, version=version, changelog='<b>문자 그대로</b>'))
            dialog.refresh_buttons()
            self.assertEqual(dialog.download.isEnabled(), available)
            self.assertIn('<b>문자 그대로</b>', dialog.changelog.toPlainText())
        dialog.reject()

    def wait_worker(self, dialog):
        deadline = time.monotonic() + 5
        while dialog.worker is not None and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(.002)
        self.assertIsNone(dialog.worker)

    def test_manual_check_worker_and_close_cancellation(self):
        settings = Settings()
        settings.setValue('updates/url', 'https://example.com/old-custom-address.json')
        dialog = UpdateDialog(settings=settings)
        with patch('gtleaderboard.update_ui.fetch_manifest', return_value=self.release) as fetch:
            dialog.check_online()
            self.wait_worker(dialog)
            self.assertEqual(fetch.call_args.args[0], default_manifest_url())
        self.assertTrue(dialog.download.isEnabled())
        self.assertEqual(dialog.source_label.text(), default_manifest_url())
        def wait_cancel(worker):
            while not worker.isInterruptionRequested():
                time.sleep(.002)
            raise UpdateCancelled()
        dialog.run_operation(wait_cancel, lambda value: None)
        dialog.reject()
        self.wait_worker(dialog)
        self.assertTrue(dialog.closing)

    def test_startup_check_can_be_disabled_and_has_no_download(self):
        settings = Settings()
        settings.setValue('updates/automatic', False)
        settings.setValue('updates/url', 'https://example.com/old-custom-address.json')
        window = MainWindow()
        with patch('gtleaderboard.update_ui.update_settings', return_value=settings):
            checker = StartupUpdateCheck(window)
        with patch.object(checker, 'start') as start, patch('gtleaderboard.update_ui.QTimer.singleShot') as schedule:
            checker.schedule()
            start.assert_not_called()
            schedule.assert_not_called()
        with patch('gtleaderboard.update_ui.fetch_manifest', return_value=self.release) as fetch:
            checker.operation(checker)
            self.assertEqual(fetch.call_args.args[0], default_manifest_url())
        checker.stop()
        window.close()
