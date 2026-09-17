"""Run a frozen app with no Python paths, from a separate working directory."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("exe", type=Path)
    parser.add_argument("--ocr-images", nargs="*", default=[])
    args = parser.parse_args()
    directory = ROOT / "artifacts" / "release-tests" / uuid4().hex
    directory.mkdir(parents=True)
    report = directory / "report.json"
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
        env.pop(name, None)
    env["PATH"] = str(Path(env.get("SystemRoot", "C:/Windows")) / "System32")
    env["QT_QPA_PLATFORM"] = "offscreen"
    command = [str(args.exe.resolve()), "--self-test", str(report)]
    if args.ocr_images:
        command += ["--ocr-images", *[str(Path(p).resolve()) for p in args.ocr_images]]
    result = subprocess.run(command, cwd=directory, env=env, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
    if not report.exists():
        raise RuntimeError(f"Frozen app did not write a report; exit={result.returncode}")
    data = json.loads(report.read_text(encoding="utf-8"))
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"Report: {report}")
    if result.returncode or not data.get("ok") or not data.get("frozen"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
