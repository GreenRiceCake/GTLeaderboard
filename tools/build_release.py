"""Build Windows x64 releases from explicit inputs; never package workspace data."""
import argparse
from datetime import datetime, timezone
from importlib.metadata import distribution, version
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gtleaderboard import __version__
from gtleaderboard.ocr import MODEL_NAME, MODEL_SHA256
from gtleaderboard.releases import MANIFEST, digest_file, inspect_package
from tools.make_update_manifest import make_manifest


def source_zip(destination):
    files = list((ROOT / "gtleaderboard").rglob("*.py")) + list((ROOT / "gtleaderboard/data").glob("*.json"))
    files += [ROOT / name for name in ("run.pyw", "requirements.txt", "requirements-build.txt", "BUILDING.md", "RELEASE_NOTES.md", "models/README.md", "tools/build_release.py", "tools/setup_ocr.py", "tools/fetch_release_licenses.py", "tools/smoke_release.py")]
    files += [p for p in (ROOT / "packaging").rglob("*") if p.is_file()]
    files += [ROOT / 'tools/make_update_manifest.py', ROOT / 'UPDATING.md']
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(ROOT).as_posix())


def copy_licenses(destination):
    shutil.copytree(ROOT / "packaging/licenses", destination, dirs_exist_ok=True)
    for name in ("Qt-LGPL-3.0.txt", "Qt-GPL-3.0.txt", "RapidOCR-Apache-2.0.txt", "PaddleOCR-Apache-2.0.txt"):
        if not (destination / name).is_file():
            raise RuntimeError("Missing licenses: run python tools/fetch_release_licenses.py")
    for package in ("numpy", "Pillow", "onnxruntime", "pyinstaller", "PySide6", "PySide6_Essentials", "shiboken6", "setuptools", "packaging", "charset-normalizer", "typing_extensions"):
        dist = distribution(package)
        for file in dist.files or []:
            if file.name.lower().startswith(("license", "copying", "thirdpartynotice", "notice")):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = destination / package / (str(file).replace("/", "_").replace("\\", "_") + ".txt")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    shutil.copyfile(Path(sys.base_prefix) / "LICENSE.txt", destination / "Python.txt")


def package_release(folder):
    files = [folder / n for n in ("GTLeaderboard.exe", "README.txt", "RELEASE_NOTES.md", "BUILD_INFO.json", "SOURCE.zip", "VERSION.txt")]
    files += [p for p in (folder / "licenses").rglob("*") if p.is_file()]
    files += [folder / "models/README.md"]
    outputs = []
    for kind in ("full", "update"):
        payload = files + ([folder / "models" / MODEL_NAME] if kind == "full" else [])
        manifest = {
            "format": "GTLeaderboardRelease", "schemaVersion": 1, "version": __version__,
            "platform": "windows-x64", "kind": kind, "leagueSchema": {"min": 1, "max": 3},
            "model": {"file": f"models/{MODEL_NAME}", "sha256": MODEL_SHA256},
            "files": {p.relative_to(folder).as_posix(): {"size": p.stat().st_size, "sha256": digest_file(p)} for p in payload},
        }
        output = ROOT / "dist" / f"GTLeaderboard-{__version__}-windows-x64-{kind}.zip"
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            for path in payload:
                archive.write(path, path.relative_to(folder).as_posix())
            archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        inspect_package(output)
        if kind == "full":
            (folder / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        outputs.append(output)
        print(f"{output.name}: {output.stat().st_size:,} bytes", flush=True)
    manifest_path = make_manifest(outputs[0], ROOT / 'dist/update_manifest.json', ROOT / 'RELEASE_NOTES.md')
    outputs.append(manifest_path)
    (ROOT / "dist/SHA256SUMS.txt").write_text("".join(f"{digest_file(p)}  {p.name}\n" for p in outputs), encoding="ascii")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--onedir", action="store_true", help="Build an editable DLL directory instead of release ZIPs")
    parser.add_argument("--repackage", action="store_true", help="Refresh documents and ZIPs without rebuilding the existing EXE")
    args = parser.parse_args()
    if sys.platform != "win32" or platform.architecture()[0] != "64bit":
        raise SystemExit("Build on Windows with 64-bit Python.")
    model = ROOT / "models" / MODEL_NAME
    if not model.is_file() or digest_file(model) != MODEL_SHA256:
        raise SystemExit("Run python tools/setup_ocr.py first.")
    folder = ROOT / "dist" / f"GTLeaderboard-{__version__}-windows-x64"
    folder.mkdir(parents=True, exist_ok=True)
    if not args.repackage:
        work = ROOT / "build" / uuid4().hex
        work.mkdir(parents=True)
        release_version = tuple(map(int, __version__.split("."))) + (0,)
        version_file = work / "version.txt"
        version_file.write_text(f"VSVersionInfo(ffi=FixedFileInfo(filevers={release_version!r}, prodvers={release_version!r}, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)), kids=[StringFileInfo([StringTable('040904B0', [StringStruct('ProductName', 'GTLeaderboard'), StringStruct('FileDescription', 'GTLeaderboard'), StringStruct('FileVersion', '{__version__}'), StringStruct('ProductVersion', '{__version__}'), StringStruct('OriginalFilename', 'GTLeaderboard.exe')])]), VarFileInfo([VarStruct('Translation', [1033,1200])])])", encoding="utf-8")
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--onedir" if args.onedir else "--onefile", "--name", "GTLeaderboard", "--distpath", str(work / "output"), "--workpath", str(work / "temp"), "--specpath", str(work), "--version-file", str(version_file), "--paths", str(ROOT), "--add-data", f"{ROOT / 'gtleaderboard/data'};gtleaderboard/data", "--collect-binaries", "onnxruntime"]
        for exclude in ("torch", "tensorflow", "scipy", "matplotlib", "pandas", "IPython", "pytest", "cv2", "tkinter", "PyQt5", "PyQt6"):
            command += ["--exclude-module", exclude]
        subprocess.run(command + [str(ROOT / "run.pyw")], cwd=ROOT, check=True)
        if args.onedir:
            output = work / "output/GTLeaderboard"
            (output / "models").mkdir()
            shutil.copyfile(model, output / "models" / MODEL_NAME)
            print(f"Directory build: {output}")
            return
        shutil.copyfile(work / "output/GTLeaderboard.exe", folder / "GTLeaderboard.exe")
        info = {"version": __version__, "python": platform.python_version(), "platform": platform.platform(), "builtAt": datetime.now(timezone.utc).isoformat(), "packages": {p: version(p) for p in ("PySide6", "Pillow", "numpy", "onnxruntime", "pyinstaller")}}
        (folder / "BUILD_INFO.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    shutil.copyfile(ROOT / "packaging/README.txt", folder / "README.txt")
    shutil.copyfile(ROOT / "RELEASE_NOTES.md", folder / "RELEASE_NOTES.md")
    (folder / "VERSION.txt").write_text(__version__ + "\n", encoding="ascii")
    (folder / "models").mkdir(exist_ok=True)
    shutil.copyfile(model, folder / "models" / MODEL_NAME)
    shutil.copyfile(ROOT / "models/README.md", folder / "models/README.md")
    copy_licenses(folder / "licenses")
    source_zip(folder / "SOURCE.zip")
    package_release(folder)


if __name__ == "__main__":
    main()
