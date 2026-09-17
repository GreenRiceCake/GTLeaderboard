from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QMessageBox
from test_ui import APP
from test_support import WorkspaceDirectory
from test_online_updates import Settings

from gtleaderboard.domain import League, Round, Result, ValidationError, add_drivers, apply_results, remove_round, standings
from gtleaderboard.session import RecoveryStore, UndoHistory
from gtleaderboard.storage import load_league, save_league
from gtleaderboard.ui import MainWindow
from gtleaderboard.workflow_ui import SeasonWizard
from gtleaderboard.update_ui import UpdateDialog


class SessionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder = WorkspaceDirectory()
        self.root = Path(self.folder.name)
        league = League('복구 테스트')
        add_drivers(league, ['A', 'B'])
        league.rounds = [Round('R01'), Round('R02')]
        self.window = MainWindow(league)
        self.window.enable_session(Settings(), self.root)
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.dirty = self.window.editor_dirty = False
        self.window.close()
        APP.processEvents()
        self.folder.cleanup()

    def test_undo_delete_restores_ids_results_history_order_and_redo(self):
        window = self.window
        rnd = window.league.rounds[0]
        apply_results(window.league, rnd.id, {window.league.drivers[0].id: Result('FINISHED', 1)}, '처음')
        window.mark_dirty()
        before = deepcopy(window.league)
        remove_round(window.league, rnd.id)
        window.mark_dirty()
        window.refresh()
        window.undo_work(True)
        self.assertEqual(window.league, before)
        self.assertEqual(standings(window.league)[0]['total'], 25)
        window.undo_work(False)
        self.assertEqual([r.name for r in window.league.rounds], ['R02'])

    def test_save_then_undo_and_redo_track_disk_state(self):
        window = self.window
        window.league.name = '수정된 이름'
        window.mark_dirty()
        window.path = self.root / 'saved.png'
        self.assertTrue(window.save())
        window.undo_work(True)
        self.assertTrue(window.dirty)
        window.undo_work(False)
        self.assertFalse(window.dirty)
        self.assertEqual(load_league(window.path), window.league)
        window.undo_work(True)
        window.league.name = '다른 수정'
        window.mark_dirty()
        self.assertFalse(window.history.redo)

    def test_restore_revision_appends_and_preserves_prior_history(self):
        window = self.window
        rid = window.current_round_id
        a, b = [d.id for d in window.league.drivers]
        apply_results(window.league, rid, {a: Result('FINISHED', 1), b: Result('FINISHED', 2)}, '처음')
        apply_results(window.league, rid, {a: Result('FINISHED', 2), b: Result('FINISHED', 1)}, '정정')
        window.mark_dirty()
        window.refresh()
        before = deepcopy(window.current_round().history)
        self.assertTrue(window.restore_revision(1, '심사 재검토'))
        self.assertEqual(window.current_round().history[:2], before)
        self.assertEqual(window.current_round().history[-1].number, 3)
        self.assertEqual(window.current_round().results, before[0].results)
        with self.assertRaises(ValidationError):
            window.restore_revision(1, ' ')

    def test_recovery_preserves_invalid_unapplied_draft_and_source_png(self):
        window = self.window
        window.path = self.root / 'original.png'
        self.assertTrue(window.save())
        original = window.path.read_bytes()
        a, b = list(window.row_widgets)
        window.row_widgets[a][1].setValue(1)
        window.row_widgets[b][1].setValue(1)
        window.reason.setText('입력 중')
        self.assertTrue(window.write_recovery())
        data, league = window.recovery.read(window.recovery.path)
        window.restore_snapshot(data, league)
        self.assertIsNone(window.path)
        self.assertTrue(window.editor_dirty)
        self.assertTrue(window.dirty)
        self.assertEqual(window.row_widgets[a][1].value(), 1)
        self.assertEqual(window.row_widgets[b][1].value(), 1)
        self.assertEqual(window.reason.text(), '입력 중')
        self.assertFalse(window.current_round().confirmed)
        self.assertEqual((self.root / 'original.png').read_bytes(), original)
        self.assertEqual(window.png_suggestion.name, 'original_복구.png')

    def test_active_recovery_is_not_offered_to_second_instance(self):
        window = self.window
        window.league.name = '미저장'
        window.mark_dirty()
        window.write_recovery()
        second = RecoveryStore(self.root)
        try:
            self.assertEqual(second.candidates(), [])
            window.recovery.lock.unlock()  # Simulate a process that stopped before cleanup.
            self.assertEqual(second.candidates(), [window.recovery.path])
            _, league = second.read(window.recovery.path)
            self.assertEqual(league.name, '미저장')
        finally:
            second.close()

    def test_crashed_process_snapshot_is_discovered_after_real_lock_owner_exits(self):
        window = self.window
        next(iter(window.row_widgets.values()))[1].setValue(1)
        window.write_recovery()
        source = self.root / 'crash-input.json'
        source.write_bytes(window.recovery.path.read_bytes())
        code = "import json, os, sys; from pathlib import Path; from PySide6.QtCore import QCoreApplication; from gtleaderboard.session import RecoveryStore; app=QCoreApplication([]); store=RecoveryStore(sys.argv[1]); store.write(json.loads(Path(sys.argv[2]).read_bytes())); os._exit(77)"
        completed = subprocess.run([sys.executable, '-c', code, str(self.root), str(source)], cwd=Path(__file__).resolve().parents[1], timeout=20, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.assertEqual(completed.returncode, 77)
        candidates = window.recovery.candidates()
        self.assertEqual(len(candidates), 1)
        data, league = window.recovery.read(candidates[0])
        window.restore_snapshot(data, league)
        self.assertTrue(window.editor_dirty)
        self.assertEqual(next(iter(window.row_widgets.values()))[1].value(), 1)

    def test_recovery_file_rejects_malformed_draft_and_is_preserved(self):
        window = self.window
        window.league.name = '변경'
        window.mark_dirty()
        window.write_recovery()
        path = window.recovery.path
        data = json.loads(path.read_bytes())
        data['draft'] = {'not-a-driver': ['FINISHED', 1, False, False, 0, '']}
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValidationError):
            window.recovery.read(path)
        self.assertTrue(path.exists())

    def test_clean_save_clears_recovery_and_cancel_close_keeps_it(self):
        window = self.window
        window.league.name = '변경'
        window.mark_dirty()
        window.write_recovery()
        with patch.object(window, 'maybe_save', return_value=False):
            window.close()
        self.assertTrue(window.recovery.path.exists())
        window.path = self.root / 'saved.png'
        window.save()
        window.write_recovery()
        self.assertFalse(window.recovery.path.exists())

    def test_recent_files_deduplicate_and_open_clears_old_undo(self):
        window = self.window
        path = self.root / 'league.gtlb'
        save_league(path, window.league)
        window.remember_file(path)
        window.remember_file(path)
        self.assertEqual(window.recent_files(), [str(path.resolve())])
        window.league.name = '바뀐 이름'
        window.mark_dirty()
        with patch.object(window, 'maybe_save', return_value=True):
            self.assertTrue(window.load_path(path))
        self.assertFalse(window.history.undo)
        self.assertIsNone(window.path)  # GTLB stays export-only.
        self.assertFalse(window.dirty)

    def test_missing_recent_file_can_be_relocated(self):
        window = self.window
        missing = self.root / 'missing.png'
        window.remember_file(missing)
        replacement = self.root / 'moved.gtlb'
        save_league(replacement, window.league)
        with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName', return_value=(str(replacement), '')):
            window.open_recent(str(missing))
        self.assertEqual(window.recent_files(), [str(replacement.resolve())])

    def test_wizard_builds_valid_league_and_rejects_duplicate_drivers(self):
        wizard = SeasonWizard(self.window.catalog, self.window)
        wizard.show()
        wizard.name.setText('새 시즌')
        wizard.next()
        wizard.drivers.setPlainText('A\nA')
        with patch('gtleaderboard.workflow_ui.QMessageBox.warning'):
            wizard.next()
        self.assertEqual(wizard.currentId(), 1)
        wizard.drivers.setPlainText('A\nB')
        wizard.next()
        self.assertTrue(wizard.validateCurrentPage())
        self.assertEqual(wizard.league.name, '새 시즌')
        self.assertEqual(len(wizard.league.drivers), 2)
        self.assertEqual(wizard.league.rounds[0].name, 'R01')
        APP.processEvents()
        finish = wizard.button(wizard.WizardButton.FinishButton)
        self.assertTrue(finish.isEnabled())
        finish.click()
        self.assertEqual(wizard.result(), wizard.DialogCode.Accepted)

    def test_update_launch_cancelled_save_keeps_current_app(self):
        window = self.window
        dialog = UpdateDialog(window, settings=Settings())
        dialog.prepared = self.root
        (self.root / 'GTLeaderboard.exe').write_bytes(b'test')
        with patch.object(window, 'save', return_value=False), patch('gtleaderboard.update_ui.QProcess.startDetached') as launch, patch.object(window, 'close') as close:
            dialog.launch_prepared()
            launch.assert_not_called()
            close.assert_not_called()
        dialog.reject()

    def test_update_launch_passes_saved_png_and_preserves_app_on_failure(self):
        window = self.window
        window.path = self.root / 'league.png'
        self.assertTrue(window.save())
        dialog = UpdateDialog(window, settings=Settings())
        dialog.prepared = self.root
        exe = self.root / 'GTLeaderboard.exe'
        exe.write_bytes(b'test')
        with patch('gtleaderboard.update_ui.QProcess.startDetached', return_value=(False, 0)), patch.object(dialog, 'failed') as failed, patch.object(window, 'close') as close:
            dialog.launch_prepared()
            failed.assert_called_once()
            close.assert_not_called()
        with patch('gtleaderboard.update_ui.QProcess.startDetached', return_value=(True, 123)) as launch, patch.object(window, 'close') as close:
            dialog.launch_prepared()
            launch.assert_called_once_with(str(exe), [str(window.path.resolve())], str(self.root))
            close.assert_called_once()

    def test_undo_is_bounded_and_unapplied_input_requires_explicit_discard(self):
        history = UndoHistory(self.window.league)
        for index in range(40):
            candidate = deepcopy(self.window.league)
            candidate.name = str(index)
            history.record(candidate)
        self.assertEqual(len(history.undo), 30)
        fields = next(iter(self.window.row_widgets.values()))
        fields[1].setValue(1)
        with patch('gtleaderboard.workflow_ui.QMessageBox.question', return_value=QMessageBox.No):
            self.window.undo_work(True)
        self.assertTrue(self.window.editor_dirty)
        with patch('gtleaderboard.workflow_ui.QMessageBox.question', return_value=QMessageBox.Yes):
            self.window.undo_work(True)
        self.assertFalse(self.window.editor_dirty)
        self.assertFalse(self.window.current_round().confirmed)
