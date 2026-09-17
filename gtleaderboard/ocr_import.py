"""Transactional merge of human-reviewed OCR rows into a league."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from .domain import Driver, Result, ValidationError, apply_results, validate_league
from .ocr import OcrRow, PROFILE, normalize_name, parse_lap


@dataclass
class ImportChoice:
    row: OcrRow
    driver_id: str
    new_name: str
    position: int
    status: str
    best_lap_text: str
    overwrite: bool = False


def matching_driver(row, drivers):
    key = normalize_name(row.name)
    matches = [d.id for d in drivers if key and key in [normalize_name(n) for n in [d.name] + d.aliases]]
    return matches[0] if len(matches) == 1 else ""


def merge_review(league, round_id, choices, reason, recalculate_fastest=False, remember_aliases=False):
    if not choices:
        raise ValidationError("반영할 결과 행을 하나 이상 선택하세요.")
    candidate = deepcopy(league)
    rnd = next(r for r in candidate.rounds if r.id == round_id)
    supplied = deepcopy(rnd.results)
    chosen_ids, positions = set(), set()
    for choice in choices:
        driver_id = choice.driver_id
        if choice.new_name:
            if rnd.confirmed:
                raise ValidationError("이미 반영된 라운드는 당시 등록된 드라이버에 연결해야 합니다.")
            driver = Driver(choice.new_name.strip())
            candidate.drivers.append(driver)
            driver_id = driver.id
        driver = next((d for d in candidate.drivers if d.id == driver_id), None)
        if not driver:
            raise ValidationError(f"'{choice.row.name}'을 등록 드라이버에 연결하거나 새 이름으로 등록하세요.")
        if rnd.confirmed and driver_id not in rnd.roster:
            raise ValidationError(f"{driver.name}: 이 라운드의 당시 명단에 없는 드라이버입니다.")
        if driver_id in chosen_ids:
            raise ValidationError(f"{driver.name}: 서로 다른 인식 행을 같은 드라이버에 연결했습니다.")
        chosen_ids.add(driver_id)
        if remember_aliases and choice.row.name and normalize_name(choice.row.name) != normalize_name(driver.name):
            if choice.row.name not in driver.aliases:
                driver.aliases.append(choice.row.name)
        old = supplied.get(driver_id)
        if old and old.source != "auto_dns" and not choice.overwrite:
            continue  # Existing reviewed/manual/stewarded records are protected by default.
        if choice.position in positions:
            raise ValidationError("가져올 화면 순위가 중복됩니다. 다른 경기의 페이지인지 확인하세요.")
        positions.add(choice.position)
        if not choice.status:
            raise ValidationError(f"{driver.name}: 출전 상태를 확인하세요.")
        result = deepcopy(old) if old else Result()
        result.status = choice.status
        result.recorded_points = None
        result.position = choice.position if choice.status == "FINISHED" else None
        result.screen_position = choice.position
        result.best_lap_ms = parse_lap(choice.best_lap_text)
        if result.best_lap_ms is None and choice.best_lap_text.strip() and any(c.isdigit() for c in choice.best_lap_text):
            raise ValidationError(f"{driver.name}: 베스트 랩 형식은 2'15.371처럼 입력하세요.")
        result.source = "ocr"
        result.raw = {
            "name": choice.row.name, "time": choice.row.time_text,
            "best_lap": choice.row.best_lap_text, "game_penalty": choice.row.game_penalty,
            "file": Path(choice.row.image_path).name, "sha256": choice.row.image_hash, "profile": PROFILE,
        }
        supplied[driver_id] = result
    if recalculate_fastest:
        if any(r.status == "POINTS" for r in supplied.values()):
            raise ValidationError("점수만 보존된 기록은 랩 기록을 알 수 없습니다. 모든 경기 기록을 입력하거나 최단 랩 재계산을 해제하세요.")
        if any(r.status == "FINISHED" and r.best_lap_ms is None for r in supplied.values()):
            raise ValidationError("완주자의 베스트 랩이 빠져 있습니다. 기록을 수정하거나 최단 랩 재계산을 해제하고 수동으로 지정하세요.")
        valid_laps = [r.best_lap_ms for r in supplied.values() if r.best_lap_ms is not None]
        if not valid_laps:
            raise ValidationError("비교할 베스트 랩 기록이 없습니다. 최단 랩 재계산을 해제하세요.")
        fastest = min(valid_laps)
        if sum(r.best_lap_ms == fastest for r in supplied.values()) > 1:
            raise ValidationError("최단 랩이 동률입니다. 최단 랩 재계산을 해제해 결과를 반영한 뒤, 라운드 결과에서 패스티스트랩 수상자 한 명을 선택하세요.")
        for result in supplied.values():
            result.fastest = result.best_lap_ms == fastest
    apply_results(candidate, round_id, supplied, reason)
    validate_league(candidate)
    return candidate
