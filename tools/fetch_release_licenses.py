"""Fetch upstream license texts into the build inputs (not at app runtime)."""
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1] / "packaging" / "licenses"
SOURCES = {
    "Qt-LGPL-3.0.txt": "https://raw.githubusercontent.com/pyside/pyside-setup/v6.9.1/LICENSES/LGPL-3.0-only.txt",
    "Qt-GPL-3.0.txt": "https://raw.githubusercontent.com/pyside/pyside-setup/v6.9.1/LICENSES/GPL-3.0-only.txt",
    "RapidOCR-Apache-2.0.txt": "https://raw.githubusercontent.com/RapidAI/RapidOCR/v3.9.2/LICENSE",
    "PaddleOCR-Apache-2.0.txt": "https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/v3.0.0/LICENSE",
}

if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        with urlopen(url, timeout=45) as response:
            data = response.read()
        if len(data) < 1000 or b"<html" in data.lower():
            raise ValueError(f"Invalid license response: {url}")
        (ROOT / name).write_bytes(data)
        print(name, len(data))
