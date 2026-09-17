import csv
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QDialog, QPushButton
from test_ui import APP
from test_support import WorkspaceDirectory
from gtleaderboard.domain import League, Round, Result, add_drivers, apply_results
from gtleaderboard.export_csv import save_csv, visible_rows
from gtleaderboard.export_png import render_sheet
from gtleaderboard.export_ui import ExportDialog
from gtleaderboard.storage import load_league, save_league
from gtleaderboard.ui import MainWindow


class SaveExportTests(unittest.TestCase):
    def setUp(self):
        self.preview_count = 0
        self.temp = WorkspaceDirectory()
        self.directory = Path(self.temp.name)
        self.league = League('한글, "리그"')
        add_drivers(self.league, ['드라이버, "A"', 'B', 'C'])
        self.league.rounds = [Round('R01', track_name='긴 서킷 이름'), Round('R02')]
        self.league.rules.status_points['DNF'] = 2
        a, b, c = self.league.drivers
        apply_results(self.league, self.league.rounds[0].id, {a.id: Result('FINISHED', 1, penalty=30, note='hidden penalty reason'), b.id: Result('DNF')}, 'hidden revision reason')
        self.window = MainWindow(self.league)

    def tearDown(self):
        self.window.dirty = self.window.editor_dirty = False
        self.window.close()
        self.temp.cleanup()

    def save_preview(self, dialog):
        self.preview_count += 1
        self.assertIsNotNone(dialog.league_document)
        self.assertTrue(dialog.view.fitted)
        dialog.scale.setCurrentIndex(1)
        dialog.save()
        dialog.reject()
        return QDialog.DialogCode.Rejected

    def test_first_save_uses_png_preview_and_restores_complete_data(self):
        target = self.directory / 'league.png'
        self.window.dirty = True
        with patch.object(ExportDialog, 'exec', new=lambda dialog: self.save_preview(dialog)) as preview, patch('gtleaderboard.ui.QFileDialog.getSaveFileName', return_value=(str(target), '')) as dialog, patch('gtleaderboard.export_ui.QMessageBox.information'):
            self.assertTrue(self.window.save())
        self.assertEqual(self.preview_count, 1)
        self.assertEqual(dialog.call_args.args[3], 'PNG 이미지 (*.png)')
        self.assertEqual(load_league(target), self.league)
        self.assertEqual(self.window.path, target)
        self.assertFalse(self.window.dirty)
        self.assertEqual(self.window.png_scale, 2)

    def test_gtlb_open_then_save_prompts_for_png_and_preserves_gtlb(self):
        original = self.directory / 'old.gtlb'
        save_league(original, self.league)
        before = original.read_bytes()
        with patch('gtleaderboard.ui.QFileDialog.getOpenFileName', return_value=(str(original), '')):
            self.window.open_league()
        self.assertIsNone(self.window.path)
        self.window.league.name = '수정된 리그'
        target = original.with_suffix('.png')
        with patch.object(ExportDialog, 'exec', new=lambda dialog: self.save_preview(dialog)), patch('gtleaderboard.ui.QFileDialog.getSaveFileName', return_value=(str(target), '')), patch('gtleaderboard.export_ui.QMessageBox.information'):
            self.assertTrue(self.window.save())
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(load_league(target).name, '수정된 리그')

    def test_exports_do_not_change_active_png_or_saved_state(self):
        active = self.directory / 'active.png'
        self.window.path = active
        self.assertTrue(self.window.save())
        before = active.read_bytes()
        self.window.league.name = '아직 PNG에 저장 안 한 수정'
        self.window.dirty = True
        for kind in ('gtlb', 'csv'):
            target = self.directory / f'copy.{kind}'
            with patch('gtleaderboard.ui.QFileDialog.getSaveFileName', return_value=(str(target), '')):
                self.window.export_document(kind)
            self.assertTrue(target.exists())
            self.assertEqual(self.window.path, active)
            self.assertTrue(self.window.dirty)
        self.assertEqual(load_league(self.directory / 'copy.gtlb'), self.window.league)
        self.assertEqual(active.read_bytes(), before)

    def test_cancel_save_as_and_export_keep_existing_state(self):
        active = self.directory / 'active.png'
        self.window.path = active
        self.window.dirty = True
        with patch.object(ExportDialog, 'exec', return_value=QDialog.DialogCode.Rejected), patch('gtleaderboard.ui.QFileDialog.getSaveFileName', return_value=('', '')):
            self.assertFalse(self.window.save_as())
            self.window.export_csv()
        self.assertEqual(self.window.path, active)
        self.assertTrue(self.window.dirty)
        self.assertFalse(active.exists())

    def test_existing_png_save_updates_directly_but_save_as_uses_preview(self):
        active = self.directory / 'active.png'
        other = self.directory / 'other.png'
        self.window.path = active
        with patch.object(ExportDialog, 'exec') as preview:
            self.assertTrue(self.window.save())
            preview.assert_not_called()
        before = active.read_bytes()
        self.window.league.name = '새 이름'
        self.window.dirty = True
        with patch.object(ExportDialog, 'exec', new=lambda dialog: self.save_preview(dialog)) as preview, patch('gtleaderboard.ui.QFileDialog.getSaveFileName', return_value=(str(other), '')), patch('gtleaderboard.export_ui.QMessageBox.information'):
            self.assertTrue(self.window.save_as())
            self.assertEqual(self.preview_count, 1)
        self.assertEqual(active.read_bytes(), before)
        self.assertEqual(self.window.path, other)
        self.assertEqual(load_league(other).name, '새 이름')

    def test_preview_always_saves_editable_project(self):
        target = self.directory / 'image.png'
        self.window.dirty = True
        def save_and_close(dialog):
            dialog.save()
            dialog.reject()
            return QDialog.DialogCode.Rejected
        with patch.object(ExportDialog, 'exec', new=save_and_close), patch('gtleaderboard.ui.QFileDialog.getSaveFileName', return_value=(str(target), '')), patch('gtleaderboard.export_ui.QMessageBox.information'):
            self.assertTrue(self.window.save())
        self.assertFalse(self.window.dirty)
        self.assertEqual(self.window.path, target)
        self.assertEqual(load_league(target), self.window.league)

    def test_failed_preview_save_does_not_clear_unsaved_changes(self):
        self.window.dirty = True
        target = self.directory / 'failed.png'
        with patch.object(ExportDialog, 'exec', new=lambda dialog: self.save_preview(dialog)), patch('gtleaderboard.ui.QFileDialog.getSaveFileName', return_value=(str(target), '')), patch('gtleaderboard.export_ui.save_png', side_effect=OSError('disk error')), patch('gtleaderboard.export_ui.QMessageBox.warning'):
            self.assertFalse(self.window.save())
        self.assertTrue(self.window.dirty)
        self.assertFalse(target.exists())

    def test_export_menu_labels(self):
        button = next(b for b in self.window.findChildren(QPushButton) if b.text() == '내보내기')
        self.assertEqual([a.text() for a in button.menu().actions()], ['GTLB로 저장', 'CSV로 저장'])

    def test_empty_league_can_be_saved_as_png(self):
        self.window.league = League('준비 중인 리그')
        self.window.path = self.directory / 'empty.png'
        self.assertTrue(self.window.save())
        self.assertEqual(load_league(self.window.path), self.window.league)

    def test_csv_contains_visible_values_and_no_hidden_history(self):
        target = self.directory / 'table.csv'
        save_csv(target, self.league)
        self.assertTrue(target.read_bytes().startswith(b'\xef\xbb\xbf'))
        content = target.read_text(encoding='utf-8-sig')
        rows = list(csv.reader(StringIO(content)))
        self.assertEqual(rows[1][0], self.league.name)
        self.assertEqual(rows[4][:5], ['순위', '드라이버', 'R01', 'R02', '총 포인트'])
        self.assertEqual(rows[5][2], '긴 서킷 이름')
        driver_rows = {r[1]: r for r in rows[6:9]}
        self.assertEqual(driver_rows['B'][2:5], ['DNF · 2', '', '2'])
        self.assertEqual(driver_rows['C'][2], 'DNS')
        self.assertEqual(driver_rows[self.league.drivers[0].name][2:5], ['-5', '', '-5'])
        self.assertIn('순위별 배점', content)
        self.assertIn('보너스 규정', content)
        for hidden in (self.league.id, self.league.drivers[0].id, 'hidden penalty reason', 'hidden revision reason', 'best_lap_ms', 'schemaVersion'):
            self.assertNotIn(hidden, content)

    def test_csv_values_are_present_in_png_drawing(self):
        painted = []
        class RecordingPainter(QPainter):
            def drawText(self, rect, flags, text):
                painted.append(text)
                return super().drawText(rect, flags, text)
        with patch('gtleaderboard.export_png.QPainter', RecordingPainter):
            render_sheet(self.league, 1)
        for row in visible_rows(self.league):
            for value in row:
                if value != '':
                    self.assertTrue(any(str(value) in text for text in painted), value)

    def test_unconfirmed_ranks_are_dashes_and_formula_text_is_literal(self):
        league = League('=1+1')
        add_drivers(league, ['@name'])
        target = self.directory / 'literal.csv'
        save_csv(target, league)
        rows = list(csv.reader(StringIO(target.read_text(encoding='utf-8-sig'))))
        self.assertEqual(rows[1][0], "'=1+1")
        self.assertEqual(rows[6][:3], ['—', "'@name", '0'])
