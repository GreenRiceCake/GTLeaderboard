from copy import deepcopy
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from test_ui import APP
from test_ocr import row, SAMPLES
from gtleaderboard.domain import League, Round, Result, add_drivers, apply_results
from gtleaderboard.ocr import MODEL_NAME
from gtleaderboard.catalog import model_directory
from gtleaderboard.ocr_ui import OcrDialog
from gtleaderboard.ui import MainWindow


class OcrReviewUiTests(unittest.TestCase):
    def setUp(self):
        self.league = League("OCR UI")
        self.league.rounds = [Round("R04")]
        self.dialog = OcrDialog(self.league, self.league.rounds[0].id)
        self.dialog.show()
        APP.processEvents()

    def tearDown(self):
        self.dialog.reject()
        APP.processEvents()

    def test_review_is_required_before_commit_and_new_names_can_be_corrected(self):
        self.dialog.receive_rows([row()])
        self.assertFalse(self.dialog.commit_button.isEnabled())
        fields = self.dialog.fields[0]
        self.assertEqual(fields[3].currentData(), "__new__")
        fields[2].setText("수정한 이름")
        self.dialog.reviewed.setChecked(True)
        self.assertTrue(self.dialog.commit_button.isEnabled())
        self.dialog.commit()
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.dialog.updated_league.drivers[0].name, "수정한 이름")
        self.assertTrue(self.dialog.updated_league.rounds[0].results[self.dialog.updated_league.drivers[0].id].fastest)
        self.assertEqual(len(self.league.drivers), 0)

    def test_adding_pages_preserves_user_edits_and_cancel_does_not_apply(self):
        self.dialog.receive_rows([row()])
        self.dialog.fields[0][2].setText("직접 수정")
        self.dialog.save_fields()
        self.dialog.receive_rows([row(2, "두번째", page="def")])
        self.assertEqual(self.dialog.fields[0][2].text(), "직접 수정")
        self.assertEqual(len(self.dialog.rows), 2)
        self.dialog.reject()
        self.assertFalse(self.league.rounds[0].confirmed)

    def test_manual_edit_preserves_ocr_evidence(self):
        add_drivers(self.league, ["드라이버"])
        driver_id = self.league.drivers[0].id
        result = Result("FINISHED", 1, source="ocr", screen_position=1, best_lap_ms=135371, raw={"name": "드라이버"})
        apply_results(self.league, self.league.rounds[0].id, {driver_id: result}, "OCR")
        window = MainWindow(self.league)
        window.row_widgets[driver_id][1].setValue(2)
        window.reason.setText("심사")
        self.assertTrue(window.apply_editor())
        changed = window.league.rounds[0].results[driver_id]
        self.assertEqual((changed.position, changed.screen_position, changed.best_lap_ms), (2, 1, 135371))
        self.assertEqual(changed.raw, {"name": "드라이버"})
        window.dirty = window.editor_dirty = False
        window.close()

    def test_focusing_an_editor_previews_its_original_row(self):
        self.dialog.receive_rows([row(), row(2, "두번째", page="def")])
        with patch.object(self.dialog, "show_original") as preview:
            self.dialog.fields[1][5].setFocus()
            APP.processEvents()
            preview.assert_called_with(1)

    @unittest.skipUnless((SAMPLES / "r04-page1.jpg").exists() and (model_directory() / MODEL_NAME).exists(), "Local sample/model required")
    def test_real_background_worker_finishes_without_blocking_review(self):
        self.dialog.start_recognition([str(SAMPLES / "r04-page1.jpg"), str(SAMPLES / "r04-page2.jpg")])
        self.assertFalse(self.dialog.add_button.isEnabled())
        deadline = time.monotonic() + 15
        while self.dialog.worker is not None and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.01)
        self.assertIsNone(self.dialog.worker)
        self.assertEqual(len(self.dialog.rows), 14)
        self.assertTrue(self.dialog.add_button.isEnabled())
        self.assertFalse(self.dialog.commit_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
