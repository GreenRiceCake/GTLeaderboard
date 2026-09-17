"""Bounded HTTPS update discovery and verified side-by-side package preparation."""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from .domain import ValidationError
from .releases import MANIFEST, MAX_PACKAGE, inspect_package, prepare_update, version_tuple

UPDATER_PROTOCOL = 1
MAX_MANIFEST = 256 * 1024


class UpdateCancelled(Exception):
    pass


def https_url(value):
    if not isinstance(value, str) or len(value) > 4096 or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValidationError("업데이트 주소는 공백 없는 HTTPS URL이어야 합니다.")
    try:
        parsed = urlsplit(value)
        value.encode('ascii')
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or '\\' in value:
            raise ValueError()
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError()
    except (ValueError, UnicodeError) as exc:
        raise ValidationError("업데이트 주소에는 Markdown 링크 대신 실제 HTTPS URL을 넣어 주세요.") from exc
    return value


def default_manifest_url():
    path = Path(__file__).resolve().parent / 'data/update_source.json'
    return https_url(json.loads(path.read_text(encoding='utf-8'))['manifest_url'])


def check_cancelled(cancelled, deadline):
    if cancelled():
        raise UpdateCancelled("업데이트 작업을 취소했습니다.")
    if time.monotonic() > deadline:
        raise ValidationError("업데이트 서버 응답 시간이 초과되었습니다. 나중에 다시 시도하세요.")


class HttpsRedirect(HTTPRedirectHandler):
    def __init__(self, cancelled, deadline):
        self.cancelled, self.deadline = cancelled, deadline
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_cancelled(self.cancelled, self.deadline)
        https_url(newurl)
        self.count += 1
        if self.count > 5:
            raise ValidationError("업데이트 주소의 리디렉션이 너무 많습니다.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_https(url, cancelled, deadline):
    check_cancelled(cancelled, deadline)
    request = Request(https_url(url), headers={'User-Agent': 'GTLeaderboard-Updater/1', 'Cache-Control': 'no-cache', 'Accept-Encoding': 'identity'})
    response = build_opener(HttpsRedirect(cancelled, deadline)).open(request, timeout=10)
    try:
        https_url(response.geturl())
        if response.status != 200:
            raise ValidationError("업데이트 서버가 정상 파일을 반환하지 않았습니다.")
    except Exception:
        response.close()
        raise
    return response


@dataclass(frozen=True)
class OnlineRelease:
    version: str
    title: str
    changelog: str
    url: str
    size: int
    sha256: str


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("업데이트 매니페스트에 중복된 필드가 있습니다.")
        result[key] = value
    return result


def parse_manifest(raw):
    if len(raw) > MAX_MANIFEST:
        raise ValidationError("업데이트 매니페스트가 너무 큽니다.")
    try:
        data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object)
        if data['app'] != 'GTLeaderboard' or type(data['schema_version']) is not int or data['schema_version'] != 1:
            raise ValidationError("GTLeaderboard용 업데이트 매니페스트가 아닙니다.")
        version_tuple(data['version'])
        for key, limit in (('title', 200), ('changelog', 20000)):
            if not isinstance(data[key], str) or len(data[key]) > limit:
                raise ValidationError("업데이트 설명 형식이 올바르지 않습니다.")
        protocol = data['min_updater_protocol']
        if type(protocol) is not int or protocol < 1:
            raise ValidationError("업데이터 프로토콜 정보가 올바르지 않습니다.")
        if protocol > UPDATER_PROTOCOL:
            raise ValidationError("더 새로운 업데이터가 필요합니다. GitHub에서 최신 전체 ZIP을 직접 받아 주세요.")
        package = data['transactional_package']
        if data['update_type'] != 'zip' or package['type'] != 'zip' or package['package_manifest'] != MANIFEST:
            raise ValidationError("지원하지 않는 업데이트 패키지 방식입니다.")
        url = https_url(package['url'])
        if data['download_url'] != url:
            raise ValidationError("다운로드 주소와 패키지 주소가 일치하지 않습니다.")
        if type(package['size']) is not int or not 0 < package['size'] <= MAX_PACKAGE:
            raise ValidationError("업데이트 ZIP 크기 정보가 올바르지 않습니다.")
        if not isinstance(package['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', package['sha256']):
            raise ValidationError("업데이트 ZIP 체크섬 정보가 올바르지 않습니다.")
        return OnlineRelease(data['version'], data['title'], data['changelog'], url, package['size'], package['sha256'])
    except ValidationError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise ValidationError("업데이트 매니페스트가 올바른 JSON 형식이 아닙니다.") from exc


def fetch_manifest(url, cancelled=lambda: False):
    deadline = time.monotonic() + 30
    with open_https(url, cancelled, deadline) as response:
        content = bytearray()
        while True:
            check_cancelled(cancelled, deadline)
            block = response.read1(min(16384, MAX_MANIFEST + 1 - len(content)))
            if not block:
                break
            content.extend(block)
            if len(content) > MAX_MANIFEST:
                raise ValidationError("업데이트 매니페스트가 너무 큽니다.")
    return parse_manifest(bytes(content))


def download_and_prepare(release, parent, existing_models, current_version, progress=lambda *_: None, cancelled=lambda: False):
    if version_tuple(release.version) <= version_tuple(current_version):
        raise ValidationError("현재 버전보다 새로운 업데이트가 아닙니다.")
    parent = Path(parent).resolve()
    if not parent.is_dir() or (parent / f'GTLeaderboard-{release.version}').exists():
        raise ValidationError("대상 폴더가 없거나 같은 버전 폴더가 이미 있습니다. 다른 위치를 선택하세요.")
    temporary = parent / f'.gtleaderboard-download-{uuid4().hex}.zip.part'
    deadline = time.monotonic() + 1800
    try:
        with open_https(release.url, cancelled, deadline) as response, temporary.open('xb') as output:
            declared = response.headers.get('Content-Length')
            if declared is not None and declared != str(release.size):
                raise ValidationError("서버의 ZIP 크기가 매니페스트와 다릅니다.")
            digest, size = sha256(), 0
            while True:
                check_cancelled(cancelled, deadline)
                block = response.read1(256 * 1024)
                if not block:
                    break
                size += len(block)
                if size > release.size:
                    raise ValidationError("다운로드가 지정된 파일 크기를 초과했습니다.")
                digest.update(block)
                output.write(block)
                progress(size, release.size)
        check_cancelled(cancelled, deadline)
        if size != release.size or digest.hexdigest() != release.sha256:
            raise ValidationError("다운로드한 ZIP의 크기 또는 SHA-256이 일치하지 않습니다. 기존 앱은 변경하지 않았습니다.")
        package = inspect_package(temporary)
        if package.manifest['version'] != release.version:
            raise ValidationError("ZIP의 버전이 온라인 매니페스트와 다릅니다.")
        check_cancelled(cancelled, deadline)
        # Extraction is transactional and completes once begun; the old app remains intact.
        return prepare_update(temporary, parent, existing_models, current_version)
    finally:
        if temporary.exists():
            temporary.unlink()
