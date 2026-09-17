"""League rules and results; deliberately independent of Qt and OCR."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


STATUSES = ("FINISHED", "DNS", "DNQ", "DNF", "DSQ")
DEFAULT_POINTS = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1, 1, 1, 1, 1, 1, 1]


class ValidationError(ValueError):
    pass


def uid():
    return uuid4().hex


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def integer(value, label, minimum=0, maximum=10000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(f"{label}: {minimum}~{maximum} 사이의 정수가 필요합니다.")


def text(value, label, allow_empty=False, maximum=200):
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value.strip()):
        raise ValidationError(f"{label}: 올바른 텍스트를 입력하세요 (최대 {maximum}자).")


def boolean(value, label):
    if type(value) is not bool:
        raise ValidationError(f"{label}: 참/거짓 값이 필요합니다.")


@dataclass
class Bonus:
    enabled: bool = True
    points: int = 3
    finished_only: bool = True
    top_n: int = 0  # 0 means no finishing-position requirement.


@dataclass
class Rules:
    position_points: list[int] = field(default_factory=lambda: DEFAULT_POINTS.copy())
    status_points: dict[str, int] = field(default_factory=lambda: {s: 0 for s in STATUSES if s != "FINISHED"})
    pole: Bonus = field(default_factory=Bonus)
    fastest: Bonus = field(default_factory=Bonus)
    stack_bonuses: bool = True


@dataclass
class Driver:
    name: str
    id: str = field(default_factory=uid)
    aliases: list[str] = field(default_factory=list)


@dataclass
class Result:
    status: str = "DNS"
    position: int | None = None
    pole: bool = False
    fastest: bool = False
    penalty: int = 0
    note: str = ""
    source: str = "manual"
    screen_position: int | None = None
    best_lap_ms: int | None = None
    raw: dict[str, str] = field(default_factory=dict)
    recorded_points: int | None = None  # Historical table score; race details unknown.


@dataclass
class Revision:
    number: int
    at: str
    reason: str
    results: dict[str, Result]


@dataclass
class Round:
    name: str
    track_id: str = ""
    track_name: str = "미정"
    catalog_date: str = ""
    id: str = field(default_factory=uid)
    roster: list[str] = field(default_factory=list)
    results: dict[str, Result] = field(default_factory=dict)
    confirmed: bool = False
    history: list[Revision] = field(default_factory=list)


@dataclass
class League:
    name: str = "새 리그"
    id: str = field(default_factory=uid)
    drivers: list[Driver] = field(default_factory=list)
    rounds: list[Round] = field(default_factory=list)
    rules: Rules = field(default_factory=Rules)
    rules_history: list[dict] = field(default_factory=list)


def validate_rules(rules):
    if len(rules.position_points) != 16:
        raise ValidationError("1~16위 배점을 모두 지정해야 합니다.")
    for value in rules.position_points:
        integer(value, "순위 배점")
    if set(rules.status_points) != set(STATUSES) - {"FINISHED"}:
        raise ValidationError("DNS·DNQ·DNF·DSQ 배점이 필요합니다.")
    for value in rules.status_points.values():
        integer(value, "상태 배점")
    for bonus in (rules.pole, rules.fastest):
        boolean(bonus.enabled, "보너스 활성화")
        boolean(bonus.finished_only, "완주 조건")
        integer(bonus.points, "보너스 점수")
        integer(bonus.top_n, "보너스 순위 조건", 0, 16)
    boolean(rules.stack_bonuses, "보너스 중복 지급")


def validate_results(results, roster, unique_bonuses=True):
    if set(results) - set(roster):
        raise ValidationError("라운드 참가자 목록에 없는 드라이버의 결과입니다.")
    positions = []
    for result in results.values():
        if result.status not in (*STATUSES, "POINTS"):
            raise ValidationError("지원하지 않는 출전 상태입니다.")
        if result.status == "POINTS":
            integer(result.recorded_points, "종합표 기록 점수", -10000, 10000)
            if result.pole or result.fastest or result.penalty:
                raise ValidationError("점수만 보존한 기록에는 보너스·벌점을 중복 적용할 수 없습니다. 경기 결과로 전환해 입력하세요.")
            text(result.note, "점수 기록 출처")
        elif result.recorded_points is not None:
            raise ValidationError("점수만 보존 상태 외에는 기록 점수를 비워 주세요.")
        if result.status == "FINISHED":
            integer(result.position, "결승 순위", 1, 16)
            positions.append(result.position)
        elif result.position is not None:
            raise ValidationError("완주 외 상태에서는 결승 순위를 비워 주세요.")
        boolean(result.pole, "예선 폴")
        boolean(result.fastest, "패스티스트랩")
        integer(result.penalty, "벌점")
        text(result.note, "결과 메모", True, 2000)
        if result.penalty and not result.note.strip():
            raise ValidationError("벌점을 부여할 때는 사유를 입력하세요.")
        if result.source not in ("manual", "auto_dns", "ocr", "leaderboard"):
            raise ValidationError("지원하지 않는 입력 출처입니다.")
        if result.screen_position is not None:
            integer(result.screen_position, "화면 표시 순위", 1, 16)
        if result.best_lap_ms is not None:
            integer(result.best_lap_ms, "베스트 랩 (밀리초)", 1, 86_400_000)
        if not isinstance(result.raw, dict) or set(result.raw) - {"name", "time", "best_lap", "game_penalty", "file", "sha256", "profile"}:
            raise ValidationError("OCR 원본 기록의 구조가 올바르지 않습니다.")
        for value in result.raw.values():
            text(value, "OCR 원본 텍스트", True, 2000)
        if result.source == "auto_dns" and (result.status != "DNS" or result.pole or result.fastest or result.penalty):
            raise ValidationError("자동 DNS 기록의 내용이 올바르지 않습니다.")
    if len(positions) != len(set(positions)):
        raise ValidationError("결승 순위가 중복됩니다. 변경에 영향받는 드라이버들의 순위를 함께 수정하세요.")
    if unique_bonuses:
        for key, label in (("pole", "예선 폴"), ("fastest", "패스티스트랩")):
            if sum(getattr(r, key) for r in results.values()) > 1:
                raise ValidationError(f"{label}은 한 라운드에 한 명만 지정할 수 있습니다.")
    if sum(r.status not in ("DNS", "POINTS") for r in results.values()) > 16:
        raise ValidationError("한 라운드의 로비 인원은 최대 16명입니다 (DNS 제외).")


def validate_league(league):
    text(league.name, "리그 이름")
    text(league.id, "리그 ID")
    validate_rules(league.rules)
    if len(league.drivers) > 500 or len(league.rounds) > 100:
        raise ValidationError("첫 버전은 드라이버 500명, 라운드 100개까지 지원합니다.")
    ids, names = [], []
    identities = {}
    for driver in league.drivers:
        text(driver.id, "드라이버 ID")
        text(driver.name, "드라이버 이름", maximum=80)
        ids.append(driver.id)
        names.append(driver.name.strip().casefold())
        if not isinstance(driver.aliases, list) or len(driver.aliases) > 100:
            raise ValidationError("드라이버 별칭은 100개까지 저장할 수 있습니다.")
        for alias in [driver.name] + driver.aliases:
            text(alias, "드라이버 이름·별칭", maximum=80)
            key = " ".join(alias.split()).casefold()
            if key in identities and identities[key] != driver.id:
                raise ValidationError(f"이름 또는 별칭이 다른 드라이버와 겹칩니다: {alias}")
            identities[key] = driver.id
    if len(ids) != len(set(ids)) or len(names) != len(set(names)):
        raise ValidationError("드라이버 ID 또는 이름이 중복됩니다.")
    round_ids = []
    for rnd in league.rounds:
        text(rnd.id, "라운드 ID")
        text(rnd.name, "라운드 이름", maximum=80)
        text(rnd.track_id, "코스 ID", True)
        text(rnd.track_name, "코스 이름")
        text(rnd.catalog_date, "코스 목록 날짜", True)
        boolean(rnd.confirmed, "결과 반영 여부")
        round_ids.append(rnd.id)
        if len(rnd.roster) != len(set(rnd.roster)) or set(rnd.roster) - set(ids):
            raise ValidationError("라운드 참가자 목록이 올바르지 않습니다.")
        validate_results(rnd.results, rnd.roster)
        if rnd.confirmed and set(rnd.results) != set(rnd.roster):
            raise ValidationError("반영된 라운드에 결과가 누락되어 있습니다.")
        if not rnd.confirmed and (rnd.results or rnd.history):
            raise ValidationError("미진행 라운드에 확정 기록이 있습니다.")
        for index, rev in enumerate(rnd.history, 1):
            if type(rev.number) is not int or rev.number != index:
                raise ValidationError("라운드 개정 번호가 올바르지 않습니다.")
            text(rev.at, "수정 시각")
            text(rev.reason, "수정 사유", maximum=2000)
            validate_results(rev.results, rnd.roster, unique_bonuses=False)
            if set(rev.results) != set(rnd.roster):
                raise ValidationError("라운드 변경 이력에 결과가 누락되어 있습니다.")
        if rnd.confirmed and (not rnd.history or rnd.history[-1].results != rnd.results):
            raise ValidationError("라운드 결과와 최신 변경 이력이 일치하지 않습니다.")
    if len(round_ids) != len(set(round_ids)):
        raise ValidationError("라운드 ID가 중복됩니다.")
    for entry in league.rules_history:
        if set(entry) != {"at", "before", "after"}:
            raise ValidationError("규칙 변경 이력이 올바르지 않습니다.")
        text(entry["at"], "규칙 변경 시각")
        validate_rules(rules_from_dict(entry["before"]))
        validate_rules(rules_from_dict(entry["after"]))


def add_drivers(league, names):
    candidate = deepcopy(league)
    candidate.drivers.extend(Driver(name.strip()) for name in names if name.strip())
    validate_league(candidate)
    league.drivers = candidate.drivers


def reorder_rounds(league, round_ids):
    """Change display order using stable IDs, preserving each complete round."""
    existing = {rnd.id: rnd for rnd in league.rounds}
    if len(round_ids) != len(existing) or len(set(round_ids)) != len(round_ids) or set(round_ids) != set(existing):
        raise ValidationError("모든 라운드를 중복 없이 한 번씩 지정해야 합니다.")
    candidate = deepcopy(league)
    candidates = {rnd.id: rnd for rnd in candidate.rounds}
    candidate.rounds = [candidates[rid] for rid in round_ids]
    validate_league(candidate)
    league.rounds = candidate.rounds


def remove_round(league, round_id):
    if not any(rnd.id == round_id for rnd in league.rounds):
        raise ValidationError("삭제할 라운드를 찾을 수 없습니다.")
    candidate = deepcopy(league)
    candidate.rounds = [rnd for rnd in candidate.rounds if rnd.id != round_id]
    validate_league(candidate)
    league.rounds = candidate.rounds


def apply_results(league, round_id, supplied, reason):
    """Commit a full manually reviewed sheet, fill absent roster members with DNS."""
    rnd = next(r for r in league.rounds if r.id == round_id)
    roster = rnd.roster if rnd.confirmed else [d.id for d in league.drivers]
    if not roster:
        raise ValidationError("먼저 드라이버를 등록하세요.")
    validate_results(supplied, roster)
    results = {driver_id: deepcopy(supplied.get(driver_id, Result(source="auto_dns"))) for driver_id in roster}
    validate_results(results, roster)
    if rnd.confirmed and results == rnd.results:
        return False
    text(reason, "변경 사유", maximum=2000)
    rnd.roster = roster.copy()
    rnd.results = results
    rnd.confirmed = True
    rnd.history.append(Revision(len(rnd.history) + 1, timestamp(), reason.strip(), deepcopy(results)))
    return True


def update_rules(league, rules):
    validate_rules(rules)
    if rules != league.rules:
        league.rules_history.append({"at": timestamp(), "before": asdict(league.rules), "after": asdict(rules)})
        league.rules = deepcopy(rules)


def score(result, rules):
    if result.status == "POINTS":
        return result.recorded_points
    base = rules.position_points[result.position - 1] if result.status == "FINISHED" else rules.status_points[result.status]
    bonuses = []
    for earned, rule in ((result.pole, rules.pole), (result.fastest, rules.fastest)):
        eligible = not rule.finished_only or result.status == "FINISHED"
        eligible = eligible and (not rule.top_n or (result.position is not None and result.position <= rule.top_n))
        if earned and rule.enabled and eligible:
            bonuses.append(rule.points)
    bonus = sum(bonuses) if rules.stack_bonuses else max(bonuses, default=0)
    return base + bonus - result.penalty


def standings(league):
    rows = []
    for driver in league.drivers:
        points = [score(r.results[driver.id], league.rules) if r.confirmed and driver.id in r.results else None for r in league.rounds]
        rows.append({"id": driver.id, "name": driver.name, "points": points, "total": sum(p for p in points if p is not None)})
    rows.sort(key=lambda row: (-row["total"], row["name"].casefold()))
    previous, rank = None, 0
    for index, row in enumerate(rows, 1):
        if row["total"] != previous:
            rank = index
        row["rank"] = rank
        previous = row["total"]
    return rows


def rules_from_dict(data):
    return Rules(**{**data, "pole": Bonus(**data["pole"]), "fastest": Bonus(**data["fastest"])})
