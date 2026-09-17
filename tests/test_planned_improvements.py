from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QFontMetrics, QWheelEvent
from PySide6.QtTest import QTest
from test_ui import APP
from test_support import WorkspaceDirectory
from test_ocr import choice, league_fixture
from gtleaderboard.catalog import load_catalog
from gtleaderboard.domain import Result, ValidationError, apply_results, validate_results
from gtleaderboard.export_ui import ExportDialog
from gtleaderboard.ocr_import import merge_review
from gtleaderboard.storage import load_league, serialize_league
from gtleaderboard.ui import MainWindow, RoundDialog


class PlannedImprovementsTests(unittest.TestCase):
    def setUp(self):
        self.league = league_fixture()
        self.window = MainWindow(self.league)
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.dirty = self.window.editor_dirty = False
        self.window.close()
        APP.processEvents()

    def test_long_circuit_header_grows_when_column_narrows(self):
        self.league.rounds[0].track_name = "마운트 파노라마 모터레이싱 서킷"
        self.window.refresh()
        header = self.window.standings_table.horizontalHeader()
        initial = header.height()
        self.window.standings_table.setColumnWidth(2, 100)
        APP.processEvents()
        text = self.window.standings_table.horizontalHeaderItem(2).text()
        needed = QFontMetrics(header.heading_font()).boundingRect(QRect(0, 0, 80, 10000), int(Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextWrapAnywhere), text).height() + 24
        self.assertGreater(header.height(), initial)
        self.assertGreaterEqual(header.height(), needed)

    def test_search_dropdown_contains_mouse_choice_and_tab(self):
        dialog = RoundDialog("R01", load_catalog())
        dialog.show()
        APP.processEvents()
        self.addCleanup(dialog.close)
        edit = dialog.track.lineEdit()
        edit.setText("파노라마")
        edit.textEdited.emit("파노라마")
        APP.processEvents()
        completer = dialog.track.completer()
        model = completer.completionModel()
        self.assertGreater(model.rowCount(), 0)
        self.assertTrue(all("파노라마" in model.index(i, 0).data() for i in range(model.rowCount())))
        popup = completer.popup()
        QTest.mouseClick(popup.viewport(), Qt.MouseButton.LeftButton, pos=popup.visualRect(model.index(0, 0)).center())
        self.assertIn("파노라마", dialog.value().track_name)
        edit.setFocus()
        edit.setText("롱 코스")
        edit.textEdited.emit("롱 코스")
        APP.processEvents()
        QTest.keyClick(edit, Qt.Key.Key_Tab)
        self.assertIn("롱 코스", dialog.value().track_name)
        edit.setText("")
        edit.textEdited.emit("")
        APP.processEvents()
        self.assertEqual(completer.completionCount(), dialog.track.count())
        popup.hide()
        QTest.mouseClick(dialog.track.arrow, Qt.MouseButton.LeftButton)
        self.assertTrue(popup.isVisible())
        popup.hide()

    def test_bonus_choices_are_exclusive_per_award_but_can_share_one_driver(self):
        a, b, _ = self.league.drivers
        first, second = self.window.row_widgets[a.id], self.window.row_widgets[b.id]
        first[1].setValue(1)
        second[1].setValue(2)
        first[2].setChecked(True)
        first[3].setChecked(True)
        second[3].setChecked(True)
        self.assertTrue(first[2].isChecked())
        self.assertFalse(first[3].isChecked())
        first[3].setChecked(True)
        self.assertFalse(second[3].isChecked())
        self.assertTrue(first[2].isChecked() and first[3].isChecked())
        for key in ("pole", "fastest"):
            results = {a.id: Result("FINISHED", 1, **{key: True}), b.id: Result("FINISHED", 2, **{key: True})}
            with self.assertRaisesRegex(ValidationError, "한 명"):
                apply_results(self.league, self.league.rounds[0].id, results, "중복")
        self.assertFalse(self.league.rounds[0].confirmed)

    def test_fastest_lap_tie_requires_selection_and_does_not_commit(self):
        before = deepcopy(self.league)
        a, b, _ = self.league.drivers
        with self.assertRaisesRegex(ValidationError, "동률"):
            merge_review(self.league, self.league.rounds[0].id, [choice(a), choice(b, 2)], "입력", True)
        self.assertEqual(before, self.league)

    def test_zoom_default_wheel_and_output_resolution_are_independent(self):
        dialog = ExportDialog(self.league)
        self.addCleanup(dialog.reject)
        dialog.show()
        APP.processEvents()
        self.assertEqual(dialog.scale.currentData(), 1)
        self.assertEqual(dialog.zoom.value(), 100)
        first_scale = dialog.view.transform().m11()
        original = dialog.image.copy()
        dialog.zoom.setValue(200)
        self.assertAlmostEqual(dialog.view.transform().m11(), 2 * first_scale)
        cursor = QPointF(dialog.view.viewport().rect().center())
        event = QWheelEvent(cursor, cursor, QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        APP.sendEvent(dialog.view.viewport(), event)
        self.assertEqual(dialog.zoom.value(), 225)
        self.assertEqual(dialog.image, original)
        dialog.view.fit_all()
        self.assertEqual(dialog.zoom.value(), 100)
        dialog.resize(1000, 700)
        APP.processEvents()
        visible = dialog.view.mapToScene(dialog.view.viewport().rect()).boundingRect()
        self.assertTrue(visible.contains(dialog.view.sceneRect()))
        dialog.scale.setCurrentIndex(1)
        self.assertEqual(dialog.image.width(), original.width() * 2)
        self.assertEqual(dialog.zoom.value(), 100)

    def test_png_export_marks_saved_only_for_current_data(self):
        self.window.mark_dirty()
        document = serialize_league(self.league)
        with WorkspaceDirectory() as folder:
            target = Path(folder) / "season.png"
            dialog = ExportDialog(self.league)
            self.addCleanup(dialog.reject)
            dialog.saved.connect(self.window.png_saved)
            with patch("gtleaderboard.export_ui.QFileDialog.getSaveFileName", return_value=(str(target), "")), patch("gtleaderboard.export_ui.QMessageBox.information"):
                dialog.save()
            self.assertFalse(self.window.dirty)
            self.assertEqual(self.window.path, target)
            self.assertTrue(self.window.maybe_save())
            self.league.name = "저장 후 변경"
            self.window.mark_dirty()
            self.window.png_saved(str(target), document, 1)
            self.assertTrue(self.window.dirty)
            self.assertTrue(self.window.save())
            self.assertEqual(load_league(target), self.league)

    def test_failed_png_save_preserves_file_and_unsaved_flag(self):
        with WorkspaceDirectory() as folder:
            self.window.path = Path(folder) / "season.png"
            self.assertTrue(self.window.save())
            previous = self.window.path.read_bytes()
            self.league.name = "변경"
            self.window.mark_dirty()
            with patch("gtleaderboard.storage.os.replace", side_effect=OSError("disk full")), patch.object(self.window, "error"):
                self.assertFalse(self.window.save())
            self.assertTrue(self.window.dirty)
            self.assertEqual(previous, self.window.path.read_bytes())
