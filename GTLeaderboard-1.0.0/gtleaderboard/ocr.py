"""Offline OCR for the GT7 16:9, eight-row lobby results screen.

Uses the RapidAI conversion of PaddleOCR's Korean PP-OCRv5 recognizer.
The screen template locates text; no text detector or external service is used.
"""

from dataclasses import dataclass, field
from hashlib import sha256
import math
from pathlib import Path
import re
import sys
import unicodedata

from .catalog import model_directory
from .domain import ValidationError

MODEL_NAME = "korean_PP-OCRv5_rec_mobile.onnx"
MODEL_SHA256 = "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b"
PROFILE = "gt7-lobby-8rows-v1"
FIELDS = {"position": (142, 208), "name": (289, 590), "time": (1337, 1518), "game_penalty": (1535, 1700), "best_lap": (1742, 1895)}


class OcrCancelled(Exception):
    pass


@dataclass
class OcrRow:
    position: int | None
    name: str
    status: str
    time_text: str
    best_lap_text: str
    game_penalty: str
    image_path: str
    image_hash: str
    row_index: int
    scores: dict[str, float] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


def normalize_name(value):
    return " ".join(unicodedata.normalize("NFC", value).split()).casefold()


def parse_lap(value):
    cleaned = value.strip().replace("’", "'").replace("′", "'").replace(":", "'")
    match = re.fullmatch(r"(\d{1,3})'([0-5]\d)[.](\d{3})", cleaned)
    if not match:
        return None
    minutes, seconds, millis = map(int, match.groups())
    total = (minutes * 60 + seconds) * 1000 + millis
    return total if 0 < total <= 86_400_000 else None


def parse_status(value):
    cleaned = value.strip().upper().replace(" ", "")
    if cleaned in ("DNS", "DNQ", "DNF", "DSQ"):
        return cleaned
    if parse_lap(cleaned) is not None or re.fullmatch(r"\+\d+[.]\d{3}", cleaned):
        return "FINISHED"
    return ""  # Unknown values require a human choice, never implicit FINISHED.


def row_crop(image, row_index, field_name):
    left, right = FIELDS[field_name]
    top = 321 + 76.8 * row_index
    sx, sy = image.width / 2048, image.height / 1152
    return image.crop((round(left * sx), round(top * sy), round(right * sx), round((top + 49) * sy)))


class TextRecognizer:
    def __init__(self, path=None):
        try:
            import numpy as np
            import onnxruntime as ort
        except ImportError as exc:
            raise ValidationError("OCR 의존성을 설치하세요: python -m pip install -r requirements.txt") from exc
        path = Path(path) if path else model_directory() / MODEL_NAME
        if not path.is_file():
            help_text = "전체 배포 패키지의 models 폴더를 실행 파일 옆에 두세요." if getattr(sys, "frozen", False) else "python tools/setup_ocr.py로 준비하세요."
            raise ValidationError(f"한국어 OCR 모델이 없습니다. {help_text}\n모델 위치: {path}")
        if sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValidationError("OCR 모델의 체크섬이 맞지 않습니다. 전체 배포 패키지의 models 폴더로 다시 준비하세요." if getattr(sys, "frozen", False) else "OCR 모델의 체크섬이 맞지 않습니다. tools/setup_ocr.py로 다시 준비하세요.")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
        chars = self.session.get_modelmeta().custom_metadata_map["character"].splitlines()
        self.characters = [""] + chars + [" "]
        self.input_name = self.session.get_inputs()[0].name
        self.np = np

    def read(self, image):
        from PIL import Image
        np = self.np
        width = max(1, math.ceil(48 * image.width / image.height))
        resized = image.convert("RGB").resize((width, 48), Image.Resampling.BILINEAR)
        # PP-OCR models expect OpenCV's BGR order and [-1, 1] normalization.
        pixels = np.asarray(resized, dtype=np.float32)[:, :, ::-1]
        pixels = pixels.transpose(2, 0, 1) / 127.5 - 1
        padded = np.zeros((1, 3, 48, max(320, width)), dtype=np.float32)
        padded[0, :, :, :width] = pixels
        predictions = self.session.run(None, {self.input_name: padded})[0][0]
        if predictions.shape[-1] != len(self.characters):
            raise ValidationError("OCR 모델의 문자 사전이 맞지 않습니다.")
        indices = predictions.argmax(axis=1)
        output, confidence = [], []
        previous = -1
        for step, token in enumerate(indices):
            if token and token != previous:
                output.append(self.characters[token])
                confidence.append(float(predictions[step, token]))
            previous = token
        return unicodedata.normalize("NFC", "".join(output)).strip(), (sum(confidence) / len(confidence) if confidence else 0.0)


def recognize_screenshot(path, recognizer, progress=None, cancelled=lambda: False):
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise ValidationError("Pillow가 필요합니다: python -m pip install -r requirements.txt") from exc
    path = Path(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValidationError("스크린샷 파일은 32 MB 이하로 선택하세요.")
    digest = sha256(path.read_bytes()).hexdigest()
    with Image.open(path) as original:
        if original.width * original.height > 34_000_000:
            raise ValidationError("스크린샷은 8K 이하 해상도로 선택하세요.")
        image = ImageOps.exif_transpose(original).convert("RGB")
    if image.width < 1280 or abs(image.width / image.height - 16 / 9) > 0.03:
        raise ValidationError("첫 OCR 버전은 1280px 이상, 잘리지 않은 16:9 GT7 로비 결과 화면을 지원합니다.")
    rows = []
    for index in range(8):
        raw, scores = {}, {}
        for key in FIELDS:
            if cancelled():
                raise OcrCancelled()
            raw[key], scores[key] = recognizer.read(row_crop(image, index, key))
        rank = int(raw["position"]) if re.fullmatch(r"\d{1,2}", raw["position"]) else None
        if rank is not None and not 1 <= rank <= 16:
            rank = None
        # Empty trailing slots can produce low-confidence hallucinations.
        if rank is None and not raw["name"] and not parse_status(raw["time"]):
            continue
        if rank is None and max(scores["name"], scores["time"]) < 0.5:
            continue
        status = parse_status(raw["time"])
        issues = []
        if rank is None:
            issues.append("표시 순위 확인")
        if not status:
            issues.append("출전 상태 확인")
        if not raw["name"] or scores["name"] < 0.9:
            issues.append("이름 확인")
        if status == "FINISHED" and parse_lap(raw["best_lap"]) is None:
            issues.append("베스트 랩 확인")
        rows.append(OcrRow(rank, raw["name"], status, raw["time"], raw["best_lap"], raw["game_penalty"], str(path), digest, index, scores, issues))
        if progress:
            progress(f"{path.name} · {index + 1}/8행 인식")
    if not any(row.position for row in rows):
        raise ValidationError(f"{path.name}: 지원하는 결과 표를 찾지 못했습니다. 원본 로비 결과 화면인지 확인하세요.")
    return rows


def combine_rows(existing, incoming):
    """Deduplicate identical pages/rows, retain conflicts for explicit review."""
    result = list(existing)
    keys = {(r.image_hash, r.row_index) for r in result}
    for row in incoming:
        if (row.image_hash, row.row_index) in keys:
            continue
        equivalent = any((r.position, r.name, r.status, r.time_text, r.best_lap_text) == (row.position, row.name, row.status, row.time_text, row.best_lap_text) for r in result)
        if not equivalent:
            result.append(row)
            keys.add((row.image_hash, row.row_index))
    return sorted(result, key=lambda r: r.position or 99)
