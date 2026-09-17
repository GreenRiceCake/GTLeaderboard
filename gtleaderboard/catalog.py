import json
from pathlib import Path
import sys


def load_catalog():
    path = Path(__file__).resolve().parent / "data" / "tracks_kr.json"
    return json.loads(path.read_text(encoding="utf-8"))


def model_directory():
    """External OCR resources are relative to the exe, not CWD or _MEIPASS."""
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / "models"

