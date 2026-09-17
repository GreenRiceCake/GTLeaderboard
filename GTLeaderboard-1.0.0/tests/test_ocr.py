from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import unittest

from test_support import WorkspaceDirectory
from gtleaderboard.domain import League, Result, Round, ValidationError, add_drivers, apply_results
from gtleaderboard.ocr import MODEL_NAME, OcrRow, TextRecognizer, combine_rows, parse_lap, parse_status, recognize_screenshot
from gtleaderboard.catalog import model_directory
from gtleaderboard.ocr_import import ImportChoice, matching_driver, merge_review
from gtleaderboard.storage import load_league, save_league


def row(position=1, name="가나다", status="FINISHED", lap="2'15.371", page="abc"):
    return OcrRow(position, name, status, "30'16.295" if status == "FINISHED" else status, lap, "--'--.---", "page.jpg", page, position - 1)


def choice(driver, rank=1, lap="2'15.371", status="FINISHED", overwrite=False):
    source = row(rank, driver.name, status, lap)
    return ImportChoice(source, driver.id, "", rank, status, lap, overwrite)


def league_fixture():
    league = League("OCR 테스트")
    add_drivers(league, ["가나다", "Rocket_Silvia", "불참자"])
    league.rounds = [Round("R04")]
    return league


class ParsingTests(unittest.TestCase):
    def test_time_formats_and_status_are_separate(self):
        self.assertEqual(parse_lap("2'15.371"), 135371)
        self.assertEqual(parse_lap("2:15.371"), 135371)
        for text in ("--'--.---", "DNF", "+15.371", "2'65.371", "0'00.000"):
            self.assertIsNone(parse_lap(text))
        self.assertEqual(parse_status("+11.610"), "FINISHED")
        self.assertEqual(parse_status("DNF"), "DNF")
        self.assertEqual(parse_status("30'16.295"), "FINISHED")
        self.assertEqual(parse_status("?"), "")

    def test_same_pages_deduplicate_but_conflicts_remain_for_review(self):
        original = row()
        same = deepcopy(original)
        self.assertEqual(len(combine_rows([original], [same])), 1)
        same.image_hash = "different-photo"
        self.assertEqual(len(combine_rows([original], [same])), 1)
        same.name = "다른 드라이버"
        self.assertEqual(len(combine_rows([original], [same])), 2)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.league = league_fixture()
        self.rnd = self.league.rounds[0]
        self.a, self.b, self.c = self.league.drivers

    def test_import_dnf_screen_position_and_auto_dns(self):
        imported = merge_review(self.league, self.rnd.id, [choice(self.a), choice(self.b, 14, "", "DNF")], "최초", True)
        results = imported.rounds[0].results
        self.assertEqual(results[self.b.id].status, "DNF")
        self.assertIsNone(results[self.b.id].position)
        self.assertEqual(results[self.b.id].screen_position, 14)
        self.assertEqual(results[self.c.id].source, "auto_dns")
        self.assertTrue(results[self.a.id].fastest)
        self.assertEqual(results[self.a.id].penalty, 0)
        self.assertFalse(self.rnd.confirmed)
        self.assertEqual(results[self.a.id].raw["game_penalty"], "--'--.---")

    def test_page_two_preserves_page_one_and_replaces_auto_dns(self):
        first = merge_review(self.league, self.rnd.id, [choice(self.a)], "첫 화면", True)
        second = merge_review(first, self.rnd.id, [choice(self.b, 2, "2'14.100")], "추가 화면", True)
        results = second.rounds[0].results
        self.assertEqual(results[self.a.id].position, 1)
        self.assertEqual(results[self.b.id].position, 2)
        self.assertFalse(results[self.a.id].fastest)
        self.assertTrue(results[self.b.id].fastest)
        self.assertEqual(len(second.rounds[0].history), 2)

    def test_existing_manual_record_is_protected_unless_explicitly_replaced(self):
        apply_results(self.league, self.rnd.id, {self.a.id: Result("FINISHED", 2, pole=True, penalty=3, note="심사")}, "심사")
        untouched = merge_review(self.league, self.rnd.id, [choice(self.a)], "재입력")
        self.assertEqual(untouched.rounds[0].results[self.a.id].position, 2)
        changed = merge_review(self.league, self.rnd.id, [choice(self.a, overwrite=True)], "원본 재확인")
        result = changed.rounds[0].results[self.a.id]
        self.assertEqual(result.position, 1)
        self.assertTrue(result.pole)
        self.assertEqual((result.penalty, result.note), (3, "심사"))
        self.assertEqual(changed.rounds[0].history[0].results[self.a.id].position, 2)

    def test_unknown_or_duplicate_connections_fail_without_mutation(self):
        before = deepcopy(self.league)
        for choices in ([ImportChoice(row(), "", "", 1, "FINISHED", "2'15.371")], [choice(self.a), choice(self.a, 2)], [choice(self.a), choice(self.b)]):
            with self.assertRaises(ValidationError):
                merge_review(self.league, self.rnd.id, choices, "입력")
            self.assertEqual(self.league, before)

    def test_new_name_is_explicit_and_aliases_are_remembered_only_if_selected(self):
        new = ImportChoice(row(name="새 이름"), "", "수정한 이름", 1, "FINISHED", "2'15.371")
        imported = merge_review(self.league, self.rnd.id, [new], "추가", remember_aliases=True)
        driver = imported.drivers[-1]
        self.assertEqual(driver.name, "수정한 이름")
        self.assertEqual(matching_driver(row(name="새 이름"), imported.drivers), driver.id)
        self.assertEqual(len(self.league.drivers), 3)

    def test_missing_laps_cannot_silently_award_fastest(self):
        with self.assertRaises(ValidationError):
            merge_review(self.league, self.rnd.id, [choice(self.a, lap="")], "입력", True)
        imported = merge_review(self.league, self.rnd.id, [choice(self.a, lap="")], "입력", False)
        self.assertFalse(imported.rounds[0].results[self.a.id].fastest)

    def test_metadata_and_original_history_roundtrip(self):
        imported = merge_review(self.league, self.rnd.id, [choice(self.a)], "최초", True)
        with WorkspaceDirectory() as folder:
            path = Path(folder) / "ocr.gtlb"
            save_league(path, imported)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schemaVersion"], 3)
            self.assertEqual(load_league(path), imported)

    def test_legacy_v1_document_still_loads(self):
        apply_results(self.league, self.rnd.id, {self.a.id: Result("FINISHED", 1)}, "입력")
        data = asdict(self.league)
        for driver in data["drivers"]:
            driver.pop("aliases")
        for rnd in data["rounds"]:
            for result in list(rnd["results"].values()) + [r for rev in rnd["history"] for r in rev["results"].values()]:
                for key in ("screen_position", "best_lap_ms", "raw", "recorded_points"):
                    result.pop(key)
        with WorkspaceDirectory() as folder:
            path = Path(folder) / "v1.gtlb"
            path.write_text(json.dumps({"format": "GTLeaderboard", "schemaVersion": 1, "kind": "league", "data": data}), encoding="utf-8")
            self.assertEqual(load_league(path), self.league)


SAMPLES = Path(__file__).parent / "fixtures" / "gt7"


@unittest.skipUnless((SAMPLES / "r04-page1.jpg").is_file() and (SAMPLES / "r04-page2.jpg").is_file() and (model_directory() / MODEL_NAME).is_file(), "Local sample images and OCR model required")
class RealScreenshotTests(unittest.TestCase):
    def test_user_supplied_two_pages_with_actual_cpu_model(self):
        engine = TextRecognizer()
        rows = recognize_screenshot(SAMPLES / "r04-page1.jpg", engine) + recognize_screenshot(SAMPLES / "r04-page2.jpg", engine)
        self.assertEqual([r.position for r in rows], list(range(1, 15)))
        self.assertEqual([r.status for r in rows], ["FINISHED"] * 13 + ["DNF"])
        self.assertEqual(rows[0].name, "Rocket_Silvia")
        self.assertEqual(rows[-1].name, "우주먼지")
        expected_laps = [135371, 136527, 136049, 136268, 136144, 136829, 137322, 135997, 136610, 137129, 138504, 136775, 137614, None]
        self.assertEqual([parse_lap(r.best_lap_text) for r in rows], expected_laps)


if __name__ == "__main__":
    unittest.main()
