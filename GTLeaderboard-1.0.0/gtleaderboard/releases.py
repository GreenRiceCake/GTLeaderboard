"""Inspect local release ZIPs and prepare a new version without replacing old files."""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
from uuid import uuid4
from zipfile import ZipFile, BadZipFile

from .domain import ValidationError

MAX_PACKAGE = 1024 * 1024 * 1024
MAX_FILES = 1000
MANIFEST = "release-manifest.json"
ROOT_FILES = {"GTLeaderboard.exe", "README.txt", "RELEASE_NOTES.md", "BUILD_INFO.json", "SOURCE.zip", "VERSION.txt"}


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", value):
        raise ValidationError("배포 버전은 0.6.0 형태여야 합니다.")
    return tuple(map(int, value.split(".")))


def safe_payload_name(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValidationError("업데이트 파일 경로가 올바르지 않습니다.")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(p in (".", "..") or p.endswith((".", " ")) for p in path.parts):
        raise ValidationError("업데이트 파일 경로가 패키지 밖을 가리킵니다.")
    if any(p.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)], *[f"LPT{i}" for i in range(10)]} for p in path.parts):
        raise ValidationError("예약된 Windows 파일 이름입니다.")
    allowed = value in ROOT_FILES or (len(path.parts) >= 2 and path.parts[0] == "licenses" and path.suffix.lower() in (".txt", ".md")) or (len(path.parts) == 2 and path.parts[0] == "models" and path.suffix.lower() in (".onnx", ".md"))
    if not allowed:
        raise ValidationError(f"배포 대상이 아닌 파일이 들어 있습니다: {value}")
    return value


def digest_file(path):
    digest = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class ReleasePackage:
    path: Path
    manifest: dict


def inspect_package(path):
    path = Path(path)
    if path.stat().st_size > MAX_PACKAGE:
        raise ValidationError("업데이트 ZIP은 1 GB 이하만 지원합니다.")
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(infos) > MAX_FILES or len(set(n.casefold() for n in names)) != len(names):
                raise ValidationError("패키지 파일이 너무 많거나 이름이 중복됩니다.")
            if sum(i.file_size for i in infos) > MAX_PACKAGE or any(i.flag_bits & 1 or stat.S_ISLNK(i.external_attr >> 16) or i.is_dir() for i in infos):
                raise ValidationError("패키지 크기 또는 파일 형식이 올바르지 않습니다.")
            info = archive.getinfo(MANIFEST)
            if info.file_size > 256 * 1024:
                raise ValidationError("배포 정보가 너무 큽니다.")
            manifest = json.loads(archive.read(info).decode("utf-8"))
            if manifest["format"] != "GTLeaderboardRelease" or type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"] != 1:
                raise ValidationError("지원하지 않는 업데이트 패키지입니다.")
            version_tuple(manifest["version"])
            if manifest["platform"] != "windows-x64" or manifest["kind"] not in ("full", "update"):
                raise ValidationError("Windows x64용 배포 패키지가 아닙니다.")
            compatibility = manifest["leagueSchema"]
            if not all(type(compatibility[k]) is int for k in ("min", "max")) or not compatibility["min"] <= 3 <= compatibility["max"]:
                raise ValidationError("현재 리그 저장 형식을 지원하지 않는 업데이트입니다.")
            model = manifest["model"]
            safe_payload_name(model["file"])
            if not model["file"].startswith("models/") or not model["file"].endswith(".onnx") or not re.fullmatch(r"[0-9a-f]{64}", model["sha256"]):
                raise ValidationError("OCR 모델 배포 정보가 올바르지 않습니다.")
            files = manifest["files"]
            if not isinstance(files, dict) or "GTLeaderboard.exe" not in files or set(names) != set(files) | {MANIFEST}:
                raise ValidationError("배포 정보와 ZIP 파일 목록이 일치하지 않습니다.")
            if manifest["kind"] == "full" and model["file"] not in files:
                raise ValidationError("전체 패키지에 OCR 모델이 없습니다.")
            if model["file"] in files and files[model["file"]]["sha256"] != model["sha256"]:
                raise ValidationError("모델 체크섬 정보가 일치하지 않습니다.")
            for name, expected in files.items():
                safe_payload_name(name)
                info = archive.getinfo(name)
                if type(expected["size"]) is not int or expected["size"] != info.file_size or not re.fullmatch(r"[0-9a-f]{64}", expected["sha256"]):
                    raise ValidationError(f"파일 크기 정보가 올바르지 않습니다: {name}")
                digest = sha256()
                with archive.open(info) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest() != expected["sha256"]:
                    raise ValidationError(f"파일 손상이 감지되었습니다: {name}")
        return ReleasePackage(path.resolve(), manifest)
    except ValidationError:
        raise
    except (BadZipFile, KeyError, ValueError, TypeError, AttributeError, RuntimeError, RecursionError) as exc:
        raise ValidationError("업데이트 ZIP의 구조가 올바르지 않거나 손상되었습니다.") from exc


def prepare_update(package_path, destination_parent, existing_models, current_version):
    package = inspect_package(package_path)
    manifest = package.manifest
    if version_tuple(manifest["version"]) <= version_tuple(current_version):
        raise ValidationError("현재 버전보다 새로운 패키지를 선택하세요.")
    parent = Path(destination_parent).resolve()
    target = parent / f"GTLeaderboard-{manifest['version']}"
    if not parent.is_dir() or target.exists():
        raise ValidationError("대상 폴더가 없거나 같은 버전 폴더가 이미 있습니다. 다른 위치를 선택하세요.")
    stage = parent / f".gtleaderboard-stage-{uuid4().hex}"
    stage.mkdir()
    try:
        with ZipFile(package.path) as archive:
            for name, expected in manifest["files"].items():
                output = stage.joinpath(*PurePosixPath(name).parts)
                if not output.resolve().is_relative_to(stage.resolve()):
                    raise ValidationError("업데이트 파일 경로가 준비 폴더를 벗어납니다.")
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, output.open("xb") as destination:
                    digest = sha256()
                    size = 0
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        size += len(block)
                        if size > expected["size"]:
                            raise ValidationError("검사 후 업데이트 ZIP이 변경되었습니다.")
                        digest.update(block)
                        destination.write(block)
                if size != expected["size"] or digest.hexdigest() != expected["sha256"]:
                    raise ValidationError("검사 후 업데이트 ZIP이 변경되었습니다.")
        model = manifest["model"]
        model_target = stage / model["file"]
        if not model_target.exists():
            old_model = Path(existing_models) / PurePosixPath(model["file"]).name
            if not old_model.is_file() or digest_file(old_model) != model["sha256"]:
                raise ValidationError("기존 OCR 모델이 없거나 새 버전과 다릅니다. 모델이 포함된 전체 패키지를 선택하세요.")
            model_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(old_model, model_target)
            if digest_file(model_target) != model["sha256"]:
                raise ValidationError("모델을 복사하는 중 내용이 변경되었습니다.")
        (stage / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if target.resolve().parent != parent or target.exists():
            raise ValidationError("대상 경로가 변경되었습니다.")
        stage.rename(target)
        return target
    finally:
        # Only remove the private staging directory created by this call.
        if stage.exists() and stage.resolve().parent == parent and stage.name.startswith(".gtleaderboard-stage-"):
            shutil.rmtree(stage)
