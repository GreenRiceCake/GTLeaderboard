import unittest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from test_ui import APP

from gtleaderboard.domain import League, Round, Result, add_drivers, apply_results
from gtleaderboard.ui import MainWindow


class FixedTotalTests(unittest.TestCase):
    def setUp(self):
        league = League('고정 총점 검사')
        add_drivers(league, [f'Driver {i:02}' for i in range(18)])
        league.rounds = [Round(f'R{i:02}', track_name='마운트 파노라마 모터레이싱 서킷') for i in range(6)]
        apply_results(league, league.rounds[0].id, {league.drivers[0].id: Result('FINISHED', 1)}, '초기 결과')
        self.window = MainWindow(league)
        self.window.show()
        APP.processEvents()
        self.grid = self.window.standings_table
        self.totals = self.window.standings_pane.totals

    def tearDown(self):
        self.window.dirty = self.window.editor_dirty = False
        self.window.close()

    def test_total_stays_at_right_while_rounds_scroll(self):
        column = self.grid.columnCount() - 1
        position = self.totals.mapTo(self.window, QPoint(0, 0))
        self.assertGreater(self.grid.horizontalScrollBar().maximum(), 0)
        self.grid.horizontalScrollBar().setValue(self.grid.horizontalScrollBar().maximum())
        APP.processEvents()
        self.assertEqual(self.totals.mapTo(self.window, QPoint(0, 0)), position)
        self.assertTrue(self.totals.visualRect(self.grid.model().index(0, column)).isValid())
        self.assertEqual(self.totals.model().index(0, column).data(), '25')
        self.assertTrue(self.grid.isColumnHidden(column))
        self.assertFalse(self.totals.isColumnHidden(column))

    def test_vertical_scrolling_and_row_selection_are_shared(self):
        self.assertFalse(self.grid.verticalScrollBar().isVisible())
        self.assertTrue(self.totals.verticalScrollBar().isVisible())
        bar_x = self.totals.verticalScrollBar().mapTo(self.window, QPoint(0, 0)).x()
        cell_right = self.totals.viewport().mapTo(self.window, self.totals.viewport().rect().topRight()).x()
        self.assertGreater(bar_x, cell_right)
        self.grid.verticalScrollBar().setValue(self.grid.verticalScrollBar().maximum())
        APP.processEvents()
        self.assertEqual(self.grid.viewport().height(), self.totals.viewport().height())
        self.assertEqual(self.grid.verticalScrollBar().value(), self.totals.verticalScrollBar().value())
        last = self.grid.rowCount() - 1
        self.assertEqual(self.grid.rowViewportPosition(last), self.totals.rowViewportPosition(last))
        index = self.grid.model().index(last, self.grid.columnCount() - 1)
        QTest.mouseClick(self.totals.viewport(), Qt.MouseButton.LeftButton, pos=self.totals.visualRect(index).center())
        self.assertEqual(self.grid.currentRow(), last)
        self.totals.verticalScrollBar().setValue(0)
        self.assertEqual(self.grid.verticalScrollBar().value(), 0)

    def test_round_changes_empty_league_and_resize_keep_headers_aligned(self):
        self.window.league.rounds.append(Round('R07'))
        self.window.refresh()
        APP.processEvents()
        last = self.grid.columnCount() - 1
        self.assertFalse(self.grid.isColumnHidden(last - 1))
        self.assertTrue(self.grid.isColumnHidden(last))
        self.grid.setColumnWidth(2, 110)
        self.window.resize(1050, 700)
        APP.processEvents()
        self.assertEqual(self.grid.horizontalHeader().height(), self.totals.horizontalHeader().height())
        self.assertEqual(self.grid.viewport().height(), self.totals.viewport().height())
        self.window.league = League()
        self.window.refresh()
        APP.processEvents()
        self.assertEqual(self.totals.model().rowCount(), 0)
        self.assertFalse(self.grid.horizontalScrollBar().isVisible())
        self.assertFalse(self.totals.isColumnHidden(2))
        self.assertEqual(self.grid.viewport().height(), self.totals.viewport().height())
