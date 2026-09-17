from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from test_support import WorkspaceDirectory

from gtleaderboard.domain import (
    Bonus, League, Result, Round, Rules, ValidationError, add_drivers,
    apply_results, score, standings, update_rules, validate_league,
)
from gtleaderboard.storage import load_league, load_rules, save_league, save_rules


def sample(count=3):
    league = League("테스트 리그")
    add_drivers(league, [f"드라이버 {n + 1:02}" for n in range(count)])
    league.rounds = [Round("R01"), Round("R02")]
    return league


class ScoringTests(unittest.TestCase):
    def test_position_and_two_bonuses(self):
        self.assertEqual(score(Result("FINISHED", 1, True, True), Rules()), 31)

    def test_configurable_conditions_and_nonstacking(self):
        rules = Rules(pole=Bonus(points=5), fastest=Bonus(points=7, top_n=3), stack_bonuses=False)
        self.assertEqual(score(Result("FINISHED", 2, True, True), rules), 25)
        self.assertEqual(score(Result("FINISHED", 4, True, True), rules), 17)
        rules.fastest.enabled = False
        self.assertEqual(score(Result("FINISHED", 2, True, True), rules), 23)

    def test_status_and_completion_condition(self):
        rules = Rules()
        rules.status_points["DNF"] = 2
        result = Result("DNF", fastest=True)
        self.assertEqual(score(result, rules), 2)
        rules.fastest.finished_only = False
        self.assertEqual(score(result, rules), 5)
        rules.fastest.top_n = 10
        self.assertEqual(score(result, rules), 2)

    def test_negative_total_is_not_silently_clamped(self):
        self.assertEqual(score(Result("FINISHED", 16, penalty=5, note="심사"), Rules()), -4)

    def test_competition_ties_and_unplayed_round(self):
        league = sample()
        a, b, c = [d.id for d in league.drivers]
        league.rules.position_points[:3] = [10, 10, 5]
        apply_results(league, league.rounds[0].id, {a: Result("FINISHED", 1), b: Result("FINISHED", 2), c: Result("FINISHED", 3)}, "입력")
        rows = standings(league)
        self.assertEqual([r["rank"] for r in rows], [1, 1, 3])
        self.assertEqual(rows[0]["points"], [10, None])
        self.assertFalse(league.rounds[1].confirmed)

    def test_18_registered_16_results_auto_dns(self):
        league = sample(18)
        rnd = league.rounds[0]
        supplied = {d.id: Result("FINISHED", n) for n, d in enumerate(league.drivers[:16], 1)}
        apply_results(league, rnd.id, supplied, "입력")
        self.assertEqual(len(rnd.results), 18)
        self.assertEqual(sum(r.source == "auto_dns" for r in rnd.results.values()), 2)
        validate_league(league)

    def test_late_registration_does_not_change_old_round(self):
        league = sample(2)
        apply_results(league, league.rounds[0].id, {league.drivers[0].id: Result("FINISHED", 1)}, "입력")
        add_drivers(league, ["뒤늦은 참가"])
        late = league.drivers[-1].id
        self.assertNotIn(late, league.rounds[0].roster)
        apply_results(league, league.rounds[1].id, {late: Result("FINISHED", 1)}, "입력")
        self.assertIn(late, league.rounds[1].roster)
        self.assertIsNone(next(r for r in standings(league) if r["id"] == late)["points"][0])

    def test_steward_correction_recalculates_bonus_and_preserves_original(self):
        league = sample(2)
        a, b = [d.id for d in league.drivers]
        league.rules.fastest.top_n = 1
        rnd = league.rounds[0]
        apply_results(league, rnd.id, {a: Result("FINISHED", 1, fastest=True), b: Result("FINISHED", 2)}, "최초")
        self.assertEqual(standings(league)[0]["total"], 28)
        apply_results(league, rnd.id, {a: Result("FINISHED", 2, fastest=True), b: Result("FINISHED", 1)}, "심사 순위 변경")
        self.assertEqual(standings(league)[0]["id"], b)
        self.assertEqual(score(rnd.results[a], league.rules), 18)
        self.assertEqual(rnd.history[0].results[a].position, 1)
        self.assertEqual(len(rnd.history), 2)
        validate_league(league)

    def test_duplicate_positions_rejected_without_mutation(self):
        league = sample(2)
        before = deepcopy(league)
        with self.assertRaises(ValidationError):
            apply_results(league, league.rounds[0].id, {d.id: Result("FINISHED", 1) for d in league.drivers}, "입력")
        self.assertEqual(league, before)

    def test_17_participants_rejected(self):
        league = sample(17)
        supplied = {d.id: Result("DNF") for d in league.drivers}
        with self.assertRaises(ValidationError):
            apply_results(league, league.rounds[0].id, supplied, "입력")

    def test_rules_changes_keep_history_and_recalculate(self):
        league = sample(1)
        apply_results(league, league.rounds[0].id, {league.drivers[0].id: Result("FINISHED", 1)}, "입력")
        rules = deepcopy(league.rules)
        rules.position_points[0] = 100
        update_rules(league, rules)
        self.assertEqual(standings(league)[0]["total"], 100)
        self.assertEqual(league.rules_history[0]["before"]["position_points"][0], 25)
        validate_league(league)

    def test_duplicate_driver_names_are_atomic(self):
        league = sample(1)
        with self.assertRaises(ValidationError):
            add_drivers(league, ["새 이름", "드라이버 01"])
        self.assertEqual(len(league.drivers), 1)

    def test_noop_does_not_add_revision_or_require_reason(self):
        league = sample(1)
        rnd = league.rounds[0]
        apply_results(league, rnd.id, {}, "입력")
        self.assertFalse(apply_results(league, rnd.id, rnd.results, ""))
        self.assertEqual(len(rnd.history), 1)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = WorkspaceDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "한글 리그.gtlb"
        self.league = sample(2)
        self.league.rounds[0].track_name = "왓킨스 글렌 롱 코스"
        apply_results(self.league, self.league.rounds[0].id, {self.league.drivers[0].id: Result("FINISHED", 1)}, "최초 입력")

    def test_full_roundtrip_including_revisions_and_unicode(self):
        save_league(self.path, self.league)
        restored = load_league(self.path)
        self.assertEqual(asdict(restored), asdict(self.league))
        self.assertEqual(standings(restored), standings(self.league))

    def test_rules_file_roundtrip_and_kind_rejection(self):
        save_rules(self.path, self.league.rules)
        self.assertEqual(load_rules(self.path), self.league.rules)
        with self.assertRaises(ValidationError):
            load_league(self.path)

    def test_invalid_documents_are_rejected(self):
        save_league(self.path, self.league)
        good = json.loads(self.path.read_text(encoding="utf-8"))
        variants = []
        wrong_version = deepcopy(good)
        wrong_version["schemaVersion"] = 42
        variants.append(wrong_version)
        wrong_id = deepcopy(good)
        wrong_id["data"]["rounds"][0]["roster"].append("unknown")
        variants.append(wrong_id)
        wrong_points = deepcopy(good)
        wrong_points["data"]["rules"]["position_points"][0] = True
        variants.append(wrong_points)
        bad_history = deepcopy(good)
        bad_history["data"]["rounds"][0]["history"] = []
        variants.append(bad_history)
        variants.extend([None, [], {"format": "GTLeaderboard"}])
        for value in variants:
            with self.subTest(document=value):
                self.path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(ValidationError):
                    load_league(self.path)

    def test_failed_replace_keeps_existing_file(self):
        save_league(self.path, self.league)
        previous = self.path.read_bytes()
        self.league.name = "새 이름"
        with patch("gtleaderboard.storage.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                save_league(self.path, self.league)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(len(list(self.path.parent.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
