import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import unittest
from unittest.mock import patch
from test_support import WorkspaceDirectory

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gtleaderboard.catalog import load_catalog
from gtleaderboard.domain import League, Round, add_drivers, standings
from gtleaderboard.storage import load_league
from gtleaderboard.ui import MainWindow, RoundDialog, RulesDialog
from gtleaderboard.application import configure_app


APP = QApplication.instance() or QApplication([])
configure_app(APP)


class UiWorkflowTests(unittest.TestCase):
    def setUp(self):
        league = League("UI 테스트")
        add_drivers(league, ["한글 닉네임", "Early Dawn", "Rocket_Silvia"])
        league.rounds = [Round("R01"), Round("R02")]
        self.window = MainWindow(league)
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.dirty = self.window.editor_dirty = False
        self.window.close()
        APP.processEvents()

    def test_manual_entry_dns_edit_and_save(self):
        window = self.window
        window.tabs.setCurrentIndex(1)
        a, b, c = [d.id for d in window.league.drivers]
        window.row_widgets[a][1].setValue(1)
        window.row_widgets[a][2].setChecked(True)
        window.row_widgets[b][1].setValue(2)
        QTest.mouseClick(window.apply_button, Qt.MouseButton.LeftButton)
        rnd = window.league.rounds[0]
        self.assertEqual(rnd.results[c].source, "auto_dns")
        self.assertEqual(standings(window.league)[0]["total"], 28)
        window.row_widgets[a][1].setValue(2)
        window.row_widgets[b][1].setValue(1)
        window.reason.setText("심사 반영")
        QTest.mouseClick(window.apply_button, Qt.MouseButton.LeftButton)
        self.assertEqual(standings(window.league)[0]["id"], b)
        self.assertEqual(len(rnd.history), 2)
        with WorkspaceDirectory() as folder:
            window.path = Path(folder) / "저장.png"
            self.assertTrue(window.save())
            self.assertEqual(load_league(window.path), window.league)
            self.assertFalse(window.dirty)

    def test_invalid_positions_show_error_and_preserve_draft(self):
        a, b, _ = list(self.window.row_widgets)
        self.window.row_widgets[a][1].setValue(1)
        self.window.row_widgets[b][1].setValue(1)
        with patch.object(self.window, "error") as error:
            self.assertFalse(self.window.apply_editor())
            error.assert_called_once()
        self.assertTrue(self.window.editor_dirty)
        self.assertFalse(self.window.league.rounds[0].confirmed)

    def test_cancel_round_switch_preserves_editor(self):
        first = self.window.current_round_id
        driver = next(iter(self.window.row_widgets))
        self.window.row_widgets[driver][1].setValue(1)
        with patch.object(self.window, "resolve_editor", return_value=False):
            self.window.round_combo.setCurrentIndex(1)
        self.assertEqual(self.window.current_round_id, first)
        self.assertEqual(self.window.round_combo.currentData(), first)
        self.assertEqual(self.window.row_widgets[driver][1].value(), 1)

    def test_dialogs_and_official_catalog(self):
        catalog = load_catalog()
        self.assertGreaterEqual(len(catalog["tracks"]), 121)
        self.assertEqual(len({t["id"] for t in catalog["tracks"]}), len(catalog["tracks"]))
        dialog = RoundDialog("R03", catalog)
        dialog.track.setCurrentIndex(1)
        self.assertEqual(dialog.value().track_id, catalog["tracks"][0]["id"])
        rules = RulesDialog(self.window.league)
        self.assertEqual(rules.values(), self.window.league.rules)


if __name__ == "__main__":
    unittest.main()
