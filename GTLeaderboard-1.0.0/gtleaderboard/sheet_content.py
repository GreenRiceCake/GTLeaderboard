"""Visible leaderboard values shared by PNG and CSV output."""


def season_caption(league):
    confirmed = sum(r.confirmed for r in league.rounds)
    return f"시즌 종합 기록     ·     드라이버 {len(league.drivers)}명     ·     {confirmed} / {len(league.rounds)} 라운드 완료"


def round_display(rnd, driver_id, points):
    if points is None:
        return ""
    result = rnd.results[driver_id]
    if result.status in ("FINISHED", "POINTS"):
        return points
    return result.status if points == 0 else f"{result.status} · {points}"


def bonus_description(bonus):
    if not bonus.enabled:
        return "사용 안 함"
    conditions = []
    if bonus.finished_only:
        conditions.append("완주자만")
    if bonus.top_n:
        conditions.append(f"결승 {bonus.top_n}위 이내")
    return " · ".join(conditions) or "추가 자격 제한 없음"


def stack_description(rules):
    return "보너스 중복 지급" if rules.stack_bonuses else "자격 충족 보너스 중 큰 점수 1개 지급"


def footer_note(league):
    note = "동점은 공동 순위 · 빈칸은 미진행 또는 해당 라운드 등록 전"
    if any(r.status == "POINTS" for rnd in league.rounds for r in rnd.results.values()):
        note += " · 이전 종합표에서 옮긴 점수 포함"
    return note
