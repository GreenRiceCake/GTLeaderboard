"""Versioned UTF-8 JSON documents and atomic local writes."""

import json
import os
from pathlib import Path
from uuid import uuid4
from dataclasses import asdict

from .domain import Driver, League, Result, Revision, Round, ValidationError, rules_from_dict, validate_league, validate_rules

MAX_BYTES = 16 * 1024 * 1024


def atomic_write(path, content):
    path = Path(path)
    temporary = None
    try:
        # Fail immediately when Windows ACLs/sandbox deny writes; tempfile retries
        # PermissionError on Windows when os.access incorrectly reports writable.
        temporary = path.parent / f".gtlb-{uuid4().hex}.tmp"
        with temporary.open("xb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def encode(kind, data):
    return json.dumps({"format": "GTLeaderboard", "schemaVersion": 3 if kind == "league" else 1, "kind": kind, "data": data}, ensure_ascii=False, indent=2).encode("utf-8")


def serialize_league(league):
    validate_league(league)
    content = encode("league", asdict(league))
    if len(content) > MAX_BYTES:
        raise ValidationError("저장 파일은 16 MB까지 지원합니다.")
    return content


def save_league(path, league):
    atomic_write(path, serialize_league(league))


def read_document(path, kind):
    with Path(path).open("rb") as f:
        raw = f.read(MAX_BYTES + 1)
    return decode_document(raw, kind)


def decode_document(raw, kind):
    if len(raw) > MAX_BYTES:
        raise ValidationError("16 MB를 초과하는 파일은 열 수 없습니다.")
    document = json.loads(raw.decode("utf-8-sig"))
    supported = (1, 2, 3) if kind == "league" else (1,)
    if document["format"] != "GTLeaderboard" or type(document["schemaVersion"]) is not int or document["schemaVersion"] not in supported:
        raise ValidationError("지원하지 않는 파일 형식 또는 버전입니다. 원본 파일은 변경하지 않았습니다.")
    if document["kind"] != kind:
        raise ValidationError("리그 파일(.gtlb)과 배점 파일(.gtlr)을 구분해서 열어 주세요.")
    return document["data"]


def load_league(path):
    if Path(path).suffix.lower() == ".png":
        from .png_data import read_png_document
        return deserialize_league(read_png_document(path))
    with Path(path).open("rb") as f:
        return deserialize_league(f.read(MAX_BYTES + 1))


def deserialize_league(content):
    try:
        data = decode_document(content, "league")
        rules = rules_from_dict(data["rules"])
        drivers = [Driver(**d) for d in data["drivers"]]
        rounds = []
        for rnd in data["rounds"]:
            results = {key: Result(**value) for key, value in rnd["results"].items()}
            history = [Revision(**{**rev, "results": {key: Result(**value) for key, value in rev["results"].items()}}) for rev in rnd["history"]]
            rounds.append(Round(**{**rnd, "results": results, "history": history}))
        league = League(**{**data, "rules": rules, "drivers": drivers, "rounds": rounds})
        validate_league(league)
        return league
    except ValidationError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise ValidationError("리그 파일의 구조 또는 값이 올바르지 않습니다.") from exc


def save_rules(path, rules):
    validate_rules(rules)
    atomic_write(path, encode("rules", asdict(rules)))


def load_rules(path):
    try:
        rules = rules_from_dict(read_document(path, "rules"))
        validate_rules(rules)
        return rules
    except ValidationError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise ValidationError("배점 파일의 구조 또는 값이 올바르지 않습니다.") from exc
