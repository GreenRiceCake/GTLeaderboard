from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from gtleaderboard.domain import ValidationError
from gtleaderboard.installer import (apply_job, create_job, legacy_installation,
                                    payload_files, prepare_repair, replace_file, launch_confirmed)
from gtleaderboard.releases import MANIFEST
from gtleaderboard.update_ui import UpdateDialog
from test_ui import APP
from gtleaderboard.ui import MainWindow


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.test_root = Path(__file__).resolve().parents[1] / 'artifacts/tests'
        self.test_root.mkdir(parents=True, exist_ok=True)
        self.work = self.test_root / f'.gtleaderboard-update-{uuid4().hex}'
        self.work.mkdir()
        self.stage = self.work / 'stage'
        self.target = self.test_root / f'gtleaderboard-install-test-{uuid4().hex}'
        self.target.mkdir()
        self.stage.mkdir()
        (self.target / 'GTLeaderboard.exe').write_bytes(b'old exe')
        (self.target / 'league.png').write_bytes(b'user league')
        (self.target / 'notes.gtlb').write_bytes(b'user json')
        self.make_stage()

    def tearDown(self):
        for path, prefix in ((self.work, '.gtleaderboard-update-'), (self.target, 'gtleaderboard-install-test-')):
            if path.resolve().parent != self.test_root.resolve() or not path.name.startswith(prefix):
                raise RuntimeError('Test cleanup escaped owned temporary directories')
            shutil.rmtree(path)

    def make_stage(self):
        files = {'GTLeaderboard.exe': b'new exe', 'VERSION.txt': b'1.1.1', 'models/test.onnx': b'model'}
        for name, data in files.items():
            path = self.stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        manifest = {'format': 'GTLeaderboardRelease', 'schemaVersion': 1, 'version': '1.1.1', 'model': {'file': 'models/test.onnx', 'sha256': sha256(b'model').hexdigest()}, 'files': {name: {'size': len(data), 'sha256': sha256(data).hexdigest()} for name, data in files.items()}}
        (self.stage / MANIFEST).write_text(json.dumps(manifest), encoding='utf-8')

    def apply(self, **kwargs):
        job = create_job(self.stage, self.target, [str(self.target / 'league.png')], parent_pid=0)
        return apply_job(job, wait=lambda pid: None, launch=kwargs.pop('launch', lambda *_: None), **kwargs)

    def test_replaces_files_in_existing_directory_and_preserves_personal_files(self):
        calls = []
        target = self.apply(launch=lambda *args: calls.append(args))
        self.assertEqual(target, self.target)
        self.assertEqual((target / 'GTLeaderboard.exe').read_bytes(), b'new exe')
        self.assertEqual((target / 'models/test.onnx').read_bytes(), b'model')
        self.assertEqual((target / 'league.png').read_bytes(), b'user league')
        self.assertEqual((target / 'notes.gtlb').read_bytes(), b'user json')
        self.assertFalse((target / 'GTLeaderboard-1.1.1').exists())
        self.assertEqual(calls, [(target, [str(target / 'league.png')])])
        self.assertEqual((self.work / 'backup/GTLeaderboard.exe').read_bytes(), b'old exe')
        self.assertTrue(json.loads((self.work / 'result.json').read_text())['ok'])

    def test_failure_after_exe_replacement_rolls_back_all_declared_files(self):
        failed = False
        def replacement(source, destination):
            nonlocal failed
            if destination.name == 'VERSION.txt' and not failed:
                failed = True
                raise OSError('simulated disk error')
            replace_file(source, destination)
        with self.assertRaisesRegex(ValidationError, '복원'):
            self.apply(replace=replacement)
        self.assertEqual((self.target / 'GTLeaderboard.exe').read_bytes(), b'old exe')
        self.assertFalse((self.target / 'VERSION.txt').exists())
        self.assertFalse((self.target / MANIFEST).exists())
        self.assertEqual((self.target / 'league.png').read_bytes(), b'user league')

    def test_failed_restart_restores_previous_exe(self):
        with self.assertRaises(ValidationError):
            self.apply(launch=lambda *_: (_ for _ in ()).throw(OSError('cannot start')))
        self.assertEqual((self.target / 'GTLeaderboard.exe').read_bytes(), b'old exe')

    def test_exited_new_app_without_startup_acknowledgement_is_failure(self):
        with patch('gtleaderboard.installer.launch_app') as start:
            start.return_value.poll.return_value = 1
            with self.assertRaisesRegex(ValidationError, '시작'):
                launch_confirmed(self.target, [], self.work / 'app-ready.json')

    def test_failure_before_any_replacement_keeps_locked_old_exe_untouched(self):
        def blocked(source, destination):
            raise PermissionError('locked')
        with self.assertRaises(ValidationError):
            self.apply(replace=blocked)
        self.assertEqual(json.loads((self.work / 'result.json').read_text())['rollback_errors'], [])

    def test_tampered_stage_rejected_before_backup_or_replacement(self):
        job = create_job(self.stage, self.target, parent_pid=0)
        (self.stage / 'GTLeaderboard.exe').write_bytes(b'tampered')
        with self.assertRaises(ValidationError):
            apply_job(job, wait=lambda _: None, launch=lambda *_: None)
        self.assertFalse((self.work / 'backup').exists())
        self.assertEqual((self.target / 'GTLeaderboard.exe').read_bytes(), b'old exe')

    def test_repair_uses_only_release_payload_and_recognizes_multiple_nested_versions(self):
        shutil.copyfile(self.stage / MANIFEST, self.target / MANIFEST)
        first = self.target / 'GTLeaderboard-1.1.0'
        second = first / 'GTLeaderboard-1.1.1'
        second.mkdir(parents=True)
        for path in (first, second):
            (path / 'GTLeaderboard.exe').write_bytes(b'new exe')
            shutil.copyfile(self.stage / MANIFEST, path / MANIFEST)
        self.assertEqual(legacy_installation(second), self.target)
        self.assertIsNone(legacy_installation(self.target))
        (self.stage / 'private.png').write_bytes(b'user')
        repair = prepare_repair(self.stage, self.work)
        self.assertNotIn('private.png', payload_files(repair))
        self.assertFalse((repair / 'private.png').exists())

    def test_no_folder_picker_for_installed_app_and_helper_failure_keeps_window(self):
        window = MainWindow()
        with patch('gtleaderboard.update_ui.installation_directory', return_value=self.target):
            dialog = UpdateDialog(window)
        with patch('gtleaderboard.update_ui.QFileDialog.getExistingDirectory') as picker, patch('gtleaderboard.update_ui.temporary_workspace', return_value=self.work):
            self.assertEqual(dialog.preparation_directory(), str(self.work))
            picker.assert_not_called()
        dialog.prepared = self.stage
        with patch('gtleaderboard.update_ui.start_updater', side_effect=OSError('failed')), patch.object(dialog, 'failed') as failure, patch.object(window, 'close') as close:
            dialog.launch_prepared()
            failure.assert_called_once()
            close.assert_not_called()
        dialog.reject()
        window.close()

    def test_installed_app_passes_saved_league_to_helper_and_closes_after_start(self):
        window = MainWindow()
        window.path = self.target / 'league.png'
        with patch('gtleaderboard.update_ui.installation_directory', return_value=self.target):
            dialog = UpdateDialog(window)
        dialog.prepared = self.stage
        with patch('gtleaderboard.update_ui.start_updater', return_value=self.work / 'updater-request.json') as start, patch('gtleaderboard.update_ui.updater_ready', return_value=True), patch.object(window, 'close') as close:
            dialog.launch_prepared()
            start.assert_called_once()
            self.assertEqual(start.call_args.args[1], self.target)
            self.assertEqual(start.call_args.args[3], [str(window.path.resolve())])
            close.assert_not_called()
            dialog.poll_updater()
            close.assert_called_once()
        window.close()

    def test_cancelled_league_save_never_starts_installed_app_update(self):
        window = MainWindow()
        window.dirty = True
        with patch('gtleaderboard.update_ui.installation_directory', return_value=self.target):
            dialog = UpdateDialog(window)
        dialog.prepared = self.stage
        with patch.object(window, 'save', return_value=False), patch('gtleaderboard.update_ui.start_updater') as start, patch.object(window, 'close') as close:
            dialog.launch_prepared()
            start.assert_not_called()
            close.assert_not_called()
            self.assertFalse((self.work / 'install-job.json').exists())
        dialog.reject()
        window.dirty = False
        window.close()

    def test_interrupted_transaction_restores_backup_on_resume(self):
        job_path = create_job(self.stage, self.target, parent_pid=0)
        job = json.loads(job_path.read_text())
        backup = self.work / 'backup'
        backup.mkdir()
        (backup / 'GTLeaderboard.exe').write_bytes(b'old exe')
        job['originals'] = {name: name == 'GTLeaderboard.exe' for name in job['files']}
        job['phase'] = 'applying'
        job_path.write_text(json.dumps(job))
        (self.target / 'GTLeaderboard.exe').write_bytes(b'partly updated')
        with self.assertRaisesRegex(ValidationError, '중단'):
            apply_job(job_path, wait=lambda _: None, launch=lambda *_: None)
        self.assertEqual((self.target / 'GTLeaderboard.exe').read_bytes(), b'old exe')

    def test_model_reuse_and_unsafe_destination(self):
        manifest = json.loads((self.stage / MANIFEST).read_text())
        del manifest['files']['models/test.onnx']
        (self.stage / MANIFEST).write_text(json.dumps(manifest))
        self.assertIn('models/test.onnx', payload_files(self.stage))
        (self.target / 'VERSION.txt').mkdir()
        with self.assertRaises(ValidationError):
            create_job(self.stage, self.target, parent_pid=0)

    def test_old_nested_release_cannot_replace_a_newer_parent_installation(self):
        manifest = json.loads((self.stage / MANIFEST).read_text())
        manifest['version'] = '1.2.0'
        (self.target / MANIFEST).write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValidationError, '더 새로운'):
            create_job(self.stage, self.target, parent_pid=0)
        self.assertEqual((self.target / 'GTLeaderboard.exe').read_bytes(), b'old exe')


if __name__ == '__main__':
    unittest.main()
