import json
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from gtleaderboard.domain import (League, Round, Result, WeightRecord, WeightRules,
    ValidationError, add_drivers, apply_results, update_rules, validate_rules,
    validate_league, standings, reorder_rounds, remove_round, calculate_weight)
from gtleaderboard.ocr_import import ImportChoice, merge_review
from gtleaderboard.storage import serialize_league, deserialize_league, save_rules, load_rules
from gtleaderboard.export_png import render_sheet, save_png, measure_sheet
from gtleaderboard.export_csv import visible_rows
from gtleaderboard.png_data import read_png_document
from gtleaderboard.ui import MainWindow, RulesDialog
from gtleaderboard.session import RecoveryStore
from gtleaderboard.sheet_content import weight_cells
from test_ui import APP
from test_ocr import row
from test_support import WorkspaceDirectory


def fixture():
    league = League('웨이트 검증')
    add_drivers(league, ['선수 A', '선수 B', '선수 C'])
    league.rounds = [Round('R01'), Round('R02'), Round('R03')]
    league.rules.weight = WeightRules(True, [30, 0, -20] + [0] * 13, 100)
    return league


class WeightTests(unittest.TestCase):
    def test_previous_manual_planned_value_becomes_automatic_on_recalculation(self):
        old = WeightRecord(90, 30, 12, True, True)
        rules = fixture().rules.weight
        self.assertEqual(calculate_weight(old, Result('FINISHED', 1), rules), WeightRecord(90, 30, 100, True))
        self.assertEqual(old.planned, 12)  # Preserve the original historical snapshot.
        reduced = WeightRecord(10, -20, 90, True, True)
        self.assertEqual(calculate_weight(reduced, Result('FINISHED', 3), rules), WeightRecord(10, -20, 0, True))

    def test_empty_roster_ocr_initializes_zero_and_manual_weights_survive_reimport(self):
        league = fixture()
        league.drivers = []
        imported = merge_review(league, league.rounds[0].id,
            [ImportChoice(row(name='새 선수'), '', '새 선수', 1, 'FINISHED', "2'15.371")], '첫 OCR')
        driver = imported.drivers[0]
        rnd = imported.rounds[0]
        self.assertEqual(rnd.results[driver.id].weight, WeightRecord(0, 30, 30))
        result = deepcopy(rnd.results[driver.id])
        result.weight = WeightRecord(40, -5, 12, True, True)
        apply_results(imported, rnd.id, {driver.id: result}, '실제 중량 확인')
        updated = merge_review(imported, rnd.id,
            [ImportChoice(row(name='새 선수'), driver.id, '', 2, 'FINISHED', "2'15.371", True)], 'OCR 순위 수정')
        self.assertEqual(updated.rounds[0].results[driver.id].weight, WeightRecord(40, -5, 35, True))
        self.assertEqual(len(updated.rounds[0].history), 3)
        self.assertEqual(len(league.drivers), 0)

    def test_carry_increase_decrease_zero_and_caps_without_point_changes(self):
        league = fixture()
        a, b, c = [d.id for d in league.drivers]
        apply_results(league, league.rounds[0].id, {
            a: Result('FINISHED', 1, weight=WeightRecord(actual=90)),
            b: Result('FINISHED', 2, weight=WeightRecord(actual=40)),
            c: Result('FINISHED', 3, weight=WeightRecord(actual=10)),
        }, '초기')
        self.assertEqual([league.rounds[0].results[d].weight.planned for d in (a,b,c)], [100,40,0])
        self.assertEqual(league.rounds[0].results[a].weight.change, 30)
        self.assertEqual([r['total'] for r in standings(league)], [25,18,15])
        apply_results(league, league.rounds[1].id, {a: Result('FINISHED', 3)}, '다음 경기')
        self.assertEqual(league.rounds[1].results[a].weight, WeightRecord(100, -20, 80))
        self.assertEqual(league.rounds[1].results[b].weight, WeightRecord(40, 0, 40))
        self.assertEqual(league.rounds[1].results[b].status, 'DNS')

    def test_correcting_past_or_changing_rules_never_rewrites_later_actual(self):
        league = fixture()
        a = league.drivers[0].id
        apply_results(league, league.rounds[0].id, {a: Result('FINISHED', 1)}, 'R1')
        apply_results(league, league.rounds[1].id, {a: Result('FINISHED', 1)}, 'R2')
        second = deepcopy(league.rounds[1])
        edited = deepcopy(league.rounds[0].results)
        edited[a].weight.actual = 50
        apply_results(league, league.rounds[0].id, edited, '과거 실제 중량 정정')
        self.assertEqual(league.rounds[0].results[a].weight.planned, 80)
        self.assertEqual(league.rounds[1], second)
        rules = deepcopy(league.rules)
        rules.weight.max_total = 10
        update_rules(league, rules)
        self.assertEqual(league.rounds[1], second)
        self.assertEqual(deserialize_league(serialize_league(league)), league)
        # Unchanged past snapshots remain legal even after the cap is lowered.
        self.assertFalse(apply_results(league, second.id, second.results, '변경 없음'))
        notes = deepcopy(second.results)
        notes[a].note = '설명 보충'
        apply_results(league, second.id, notes, '메모 수정')
        self.assertEqual(league.rounds[1].results[a].weight, second.results[a].weight)

    def test_limits_and_nonfinisher_default(self):
        league = fixture()
        for value in (-1, 201, True):
            rules = deepcopy(league.rules)
            rules.weight.max_total = value
            with self.assertRaises(ValidationError): validate_rules(rules)
        a = league.drivers[0].id
        for weight in (WeightRecord(201), WeightRecord(-1), WeightRecord(change=201),
                       WeightRecord(planned=201)):
            with self.assertRaises(ValidationError):
                apply_results(league, league.rounds[0].id, {a: Result('FINISHED', 1, weight=weight)}, '잘못된 입력')
        self.assertFalse(league.rounds[0].confirmed)
        for status in ('DNS', 'DNQ', 'DNF', 'DSQ'):
            copy = fixture()
            key = copy.drivers[0].id
            apply_results(copy, copy.rounds[0].id, {key: Result(status, weight=WeightRecord(actual=35))}, '상태')
            self.assertEqual(copy.rounds[0].results[key].weight, WeightRecord(35, 0, 35))

    def test_legacy_and_new_png_rules_history_roundtrip(self):
        league = fixture()
        a = league.drivers[0].id
        apply_results(league, league.rounds[0].id, {a: Result('FINISHED', 1, weight=WeightRecord(actual=42))}, '기록')
        with WorkspaceDirectory() as directory:
            path = Path(directory) / 'weights.png'
            save_png(path, render_sheet(league, 1), serialize_league(league))
            self.assertEqual(deserialize_league(read_png_document(path)), league)
            rules_path = Path(directory) / 'weights.gtlr'
            save_rules(rules_path, league.rules)
            self.assertEqual(load_rules(rules_path), league.rules)
            legacy = json.loads(serialize_league(league))
            legacy['schemaVersion'] = 3
            legacy['data']['rules'].pop('weight')
            for rnd in legacy['data']['rounds']:
                for result in rnd['results'].values(): result.pop('weight')
                for rev in rnd['history']:
                    for result in rev['results'].values(): result.pop('weight')
            old = deserialize_league(json.dumps(legacy).encode())
            self.assertFalse(old.rules.weight.enabled)
            self.assertIsNone(old.rounds[0].results[a].weight)

    def test_standings_exports_hide_actual_and_handle_round_reorder(self):
        league = fixture()
        a = league.drivers[0].id
        apply_results(league, league.rounds[0].id, {a: Result('FINISHED', 1, weight=WeightRecord(actual=42))}, 'R1')
        apply_results(league, league.rounds[1].id, {a: Result('FINISHED', 2)}, 'R2')
        self.assertEqual(weight_cells(standings(league)[0]), ('0', '72'))
        rows = visible_rows(league)
        self.assertEqual(rows[4][-3:], ['증감 (kg)', '예정 (kg)', '총 포인트'])
        self.assertEqual(rows[6][-3:], ['0', '72', 43])
        self.assertNotIn('실제', str(rows))
        layout = measure_sheet(league)
        self.assertEqual(len(layout.columns), 8)
        snapshots = {r.id: deepcopy(r) for r in league.rounds}
        reorder_rounds(league, [r.id for r in reversed(league.rounds)])
        self.assertEqual(weight_cells(standings(league)[0]), ('+30', '72'))
        self.assertTrue(all(r == snapshots[r.id] for r in league.rounds))
        remove_round(league, league.rounds[-1].id)
        self.assertEqual(weight_cells(standings(league)[0]), ('0', '72'))


class WeightUiTests(unittest.TestCase):
    def setUp(self):
        self.league = fixture()
        self.window = MainWindow(self.league)
        self.window.error = lambda error: self.fail(str(error))
        self.a = self.league.drivers[0].id

    def tearDown(self):
        self.window.dirty = self.window.editor_dirty = False
        self.window.close()

    def test_planned_is_display_only_and_recalculates_from_actual_and_change(self):
        window = self.window
        window.row_widgets[self.a][1].setValue(1)
        editor = window.weight_widgets[self.a]
        self.assertEqual(editor.value(), WeightRecord(0, 30, 30))
        editor.actual.setValue(40)
        self.assertEqual(editor.value().planned, 70)
        editor.change.setValue(-10)
        self.assertEqual(editor.value().planned, 30)
        self.assertFalse(hasattr(editor.planned, "setValue"))
        editor.actual.setValue(50)
        self.assertEqual(editor.value().planned, 40)
        self.assertTrue(window.apply_editor())
        weight = window.league.rounds[0].results[self.a].weight
        self.assertEqual(weight, WeightRecord(50, -10, 40, True))
        window.results_table.selectRow(0)
        window.recalculate_selected_weight()
        self.assertEqual(window.weight_widgets[self.a].value(), WeightRecord(50, 30, 80))
        self.assertTrue(window.apply_editor())
        self.assertEqual(window.league.rounds[0].results[self.a].weight, WeightRecord(50, 30, 80))

    def test_rule_dialog_limits_and_disabled_feature_hide_columns(self):
        dialog = RulesDialog(self.league)
        panel = dialog.weight_panel
        panel.cap.setValue(999)
        self.assertEqual(panel.cap.value(), 200)
        panel.changes[4].setValue(-15)
        self.assertEqual(dialog.values().weight.position_changes[4], -15)
        dialog.close()
        self.league.rules.weight.enabled = False
        self.window.refresh()
        self.assertEqual(self.window.standings_table.columnCount(), 6)
        self.assertTrue(self.window.results_table.isColumnHidden(7))

    def test_weight_draft_recovery_and_undo_restore_all_fields(self):
        window = self.window
        with WorkspaceDirectory() as directory:
            window.recovery = RecoveryStore(Path(directory))
            window.row_widgets[self.a][1].setValue(1)
            window.weight_widgets[self.a].actual.setValue(42)
            window.weight_widgets[self.a].change.setValue(35)
            self.assertTrue(window.write_recovery())
            data, league = window.recovery.read(window.recovery.path)
            window.restore_snapshot(data, league)
            self.assertEqual(window.weight_widgets[self.a].value(), WeightRecord(42,35,77,True))
            self.assertTrue(window.apply_editor())
            window.undo_work(True)
            self.assertFalse(window.league.rounds[0].confirmed)
            window.undo_work(False)
            self.assertEqual(window.league.rounds[0].results[self.a].weight.planned,77)
            window.recovery.close()
            window.recovery = None

    def test_history_restore_keeps_weight_snapshot_under_new_rules(self):
        window = self.window
        rnd = window.current_round()
        apply_results(window.league, rnd.id, {self.a: Result('FINISHED', 1, weight=WeightRecord(actual=40))}, '처음')
        first = deepcopy(rnd.results)
        apply_results(window.league, rnd.id, {self.a: Result('FINISHED', 2, weight=WeightRecord(actual=50))}, '정정')
        rules = deepcopy(window.league.rules)
        rules.weight.max_total = 10
        update_rules(window.league, rules)
        window.mark_dirty()
        window.refresh()
        self.assertTrue(window.restore_revision(1))
        self.assertEqual(window.current_round().results, first)
