"""Spreadsheet-friendly CSV of visible sheet content, without project metadata."""
import csv
from io import StringIO

from .domain import standings, validate_league
from .sheet_content import bonus_description, footer_note, round_display, season_caption, stack_description
from .storage import atomic_write


def visible_rows(league):
    validate_league(league)
    rows = [
        ["GT LEAGUE  /  SEASON STANDINGS"], [league.name], [season_caption(league)], [],
        ["순위", "드라이버", *[r.name for r in league.rounds], "총 포인트"],
        ["", "", *[r.track_name for r in league.rounds], ""],
    ]
    confirmed = any(r.confirmed for r in league.rounds)
    for row in standings(league):
        values = [round_display(rnd, row["id"], points) for rnd, points in zip(league.rounds, row["points"])]
        rows.append([row["rank"] if confirmed else "—", row["name"], *values, row["total"]])
    rows.extend([[], ["순위별 배점"]])
    for start in (0, 8):
        rows.append([f"{i + 1}위" for i in range(start, start + 8)])
        rows.append(league.rules.position_points[start:start + 8])
    rows.append([f"{status} {points}점" for status, points in league.rules.status_points.items()])
    rows.extend([[], ["보너스 규정"]])
    for name, rule in (("예선 폴", league.rules.pole), ("패스티스트랩", league.rules.fastest)):
        rows.append([name, f"+{rule.points}점" if rule.enabled else "미사용", bonus_description(rule)])
    rows.extend([[stack_description(league.rules)], [], [footer_note(league)], ["GTLeaderboard"]])
    return rows


def spreadsheet_cell(value):
    # Quoting alone does not prevent Excel from evaluating formula-like text.
    # Numeric points stay numeric, including legitimate negative totals.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def save_csv(path, league):
    rows = visible_rows(league)
    width = max(map(len, rows))
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    for row in rows:
        writer.writerow([spreadsheet_cell(v) for v in row] + [""] * (width - len(row)))
    atomic_write(path, stream.getvalue().encode("utf-8-sig"))
