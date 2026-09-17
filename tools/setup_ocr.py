"""Download the pinned, checksum-verified Korean OCR model to ./models."""

from hashlib import sha256
from pathlib import Path
from urllib.request import urlopen

URL = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile.onnx"
SHA256 = "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b"
NAME = "korean_PP-OCRv5_rec_mobile.onnx"


def main():
    folder = Path(__file__).resolve().parents[1] / "models"
    folder.mkdir(exist_ok=True)
    target = folder / NAME
    if target.exists() and sha256(target.read_bytes()).hexdigest() == SHA256:
        print("OCR model already verified:", target)
        return
    print("Downloading the Korean OCR model...", flush=True)
    with urlopen(URL, timeout=60) as response:
        data = response.read(30 * 1024 * 1024)
    if sha256(data).hexdigest() != SHA256:
        raise RuntimeError("Model checksum mismatch; existing model was not changed.")
    temporary = target.with_suffix(".download")
    temporary.write_bytes(data)
    temporary.replace(target)
    print(f"Verified {len(data):,} bytes: {target}")


if __name__ == "__main__":
    main()
