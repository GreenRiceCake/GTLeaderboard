from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QDialog, QMessageBox
from test_ui import APP
from test_support import WorkspaceDirectory
from gtleaderboard.domain import League, Round, Result, ValidationError, add_drivers, apply_results, remove_round, reorder_rounds, standings
from gtleaderboard.export_csv import visible_rows
from gtleaderboard.export_png import render_sheet, save_png
from gtleaderboard.storage import serialize_league, load_league
from gtleaderboard.rounds_ui import RoundManagerDialog
from gtleaderboard.ui import MainWindow, RoundDialog


def fixture():
    league = League('라운드 관리 검증')
    add_drivers(league, ['A', 'B'])
    league.rounds = [Round('R01', track_name='코스 A'), Round('R02', track_name='코스 B'), Round('R03')]
    a, b = league.drivers
    apply_results(league, league.rounds[0].id, {a.id: Result('FINISHED', 1, note='원래 기록'), b.id: Result('FINISHED', 2)}, '첫 경기')
    apply_results(league, league.rounds[1].id, {a.id: Result('FINISHED', 2), b.id: Result('FINISHED', 1)}, '두 번째 경기')
    return league


class RoundManagementTests(unittest.TestCase):
    def test_reorder_preserves_complete_rounds_totals_and_png_order(self):
        league = fixture()
        originals = deepcopy(league.rounds)
        totals = {r['id']: r['total'] for r in standings(league)}
        reorder_rounds(league, [originals[2].id, originals[0].id, originals[1].id])
        self.assertEqual(league.rounds, [originals[2], originals[0], originals[1]])
        self.assertEqual({r['id']: r['total'] for r in standings(league)}, totals)
        self.assertEqual(visible_rows(league)[4][2:-1], ['R03', 'R01', 'R02'])
        with WorkspaceDirectory() as folder:
            path = Path(folder) / 'reordered.png'
            save_png(path, render_sheet(league, 1), serialize_league(league))
            self.assertEqual(load_league(path), league)

    def test_invalid_order_or_missing_delete_does_not_mutate(self):
        league = fixture()
        before = deepcopy(league)
        ids = [r.id for r in league.rounds]
        for order in (ids[:-1], [ids[0]] * 3, [*ids[:2], 'missing']):
            with self.assertRaises(ValidationError):
                reorder_rounds(league, order)
            self.assertEqual(league, before)
        with self.assertRaises(ValidationError):
            remove_round(league, 'missing')
        self.assertEqual(league, before)

    def test_delete_removes_score_and_history_only_for_target(self):
        league = fixture()
        keep = deepcopy(league.rounds[1:])
        remove_round(league, league.rounds[0].id)
        self.assertEqual(league.rounds, keep)
        self.assertEqual([(r['name'], r['total'], r['rank']) for r in standings(league)], [('B', 25, 1), ('A', 18, 2)])
        self.assertEqual(len(league.drivers), 2)

    def test_dialog_move_boundaries_and_cancel_preserve_source(self):
        league = fixture()
        before = deepcopy(league)
        dialog = RoundManagerDialog(league, league.rounds[0].id)
        self.assertFalse(dialog.up.isEnabled())
        dialog.move(-1)
        dialog.move(1)
        self.assertEqual(dialog.selected_id(), league.rounds[0].id)
        dialog.move(1)
        self.assertFalse(dialog.down.isEnabled())
        dialog.move(1)
        with patch('gtleaderboard.rounds_ui.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            dialog.delete_selected()
        dialog.reject()
        self.assertEqual(league, before)

    def test_decline_delete_preserves_dialog_and_original(self):
        league = fixture()
        before = deepcopy(league)
        dialog = RoundManagerDialog(league, league.rounds[0].id)
        with patch('gtleaderboard.rounds_ui.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as question:
            dialog.delete_selected()
        self.assertIn('결과 2명', question.call_args.args[2])
        self.assertEqual(dialog.league, before)
        self.assertEqual(league, before)
        dialog.reject()

    def test_main_window_applies_reordering_preserving_selected_round(self):
        window = MainWindow(fixture())
        selected = window.current_round_id
        def move(dialog):
            dialog.move(1)
            return QDialog.DialogCode.Accepted
        with patch.object(RoundManagerDialog, 'exec', new=move):
            window.manage_rounds()
        self.assertEqual(window.current_round_id, selected)
        self.assertEqual(window.round_combo.currentIndex(), 1)
        self.assertTrue(window.standings_table.horizontalHeaderItem(2).text().startswith('R02'))
        self.assertTrue(window.dirty)
        window.dirty = False
        window.close()

    def test_delete_all_updates_empty_editor_and_saves(self):
        window = MainWindow(fixture())
        def delete_all(dialog):
            while dialog.league.rounds:
                dialog.delete_selected()
            self.assertFalse(dialog.up.isEnabled())
            self.assertFalse(dialog.down.isEnabled())
            self.assertFalse(dialog.delete.isEnabled())
            return QDialog.DialogCode.Accepted
        with patch.object(RoundManagerDialog, 'exec', new=delete_all), patch('gtleaderboard.rounds_ui.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            window.manage_rounds()
        self.assertIsNone(window.current_round_id)
        self.assertFalse(window.apply_button.isEnabled())
        self.assertFalse(window.manage_rounds_button.isEnabled())
        self.assertEqual([r['total'] for r in standings(window.league)], [0, 0])
        with WorkspaceDirectory() as folder:
            window.path = Path(folder) / 'empty-rounds.png'
            self.assertTrue(window.save())
            self.assertEqual(load_league(window.path), window.league)
        window.close()

    def test_editor_cancel_and_noop_do_not_mutate(self):
        window = MainWindow(fixture())
        before = deepcopy(window.league)
        window.editor_dirty = True
        with patch.object(window, 'resolve_editor', return_value=False), patch.object(RoundManagerDialog, 'exec') as execute:
            window.manage_rounds()
            execute.assert_not_called()
        self.assertTrue(window.editor_dirty)
        window.editor_dirty = False
        with patch.object(RoundManagerDialog, 'exec', return_value=QDialog.DialogCode.Accepted):
            window.manage_rounds()
        self.assertFalse(window.dirty)
        self.assertEqual(window.league, before)
        window.close()

    def test_new_default_name_does_not_collide_after_deletion(self):
        league = fixture()
        remove_round(league, league.rounds[1].id)
        window = MainWindow(league)
        def inspect_name(dialog):
            self.assertEqual(dialog.name.text(), 'R04')
            return QDialog.DialogCode.Rejected
        with patch.object(RoundDialog, 'exec', new=inspect_name):
            window.add_round()
        window.close()
