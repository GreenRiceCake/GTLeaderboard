"""Bounded PNG iTXt project data; image chunks are never re-encoded.

PNG iTXt layout: https://www.w3.org/TR/png-3/#11iTXt
CRC validates accidental chunk damage, not authorship or authenticity.
"""

from pathlib import Path
import struct
import zlib

from .domain import ValidationError
from .storage import MAX_BYTES, deserialize_league

SIGNATURE = b"\x89PNG\r\n\x1a\n"
KEY = b"GTLeaderboard"
MAX_PNG_BYTES = 128 * 1024 * 1024


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(data, zlib.crc32(kind)))


def chunks(raw):
    if len(raw) > MAX_PNG_BYTES:
        raise ValidationError("PNG 파일은 128 MB까지 열 수 있습니다.")
    if not raw.startswith(SIGNATURE):
        raise ValidationError("올바른 PNG 파일이 아닙니다.")
    offset, seen_header, seen_image = 8, False, False
    while offset + 12 <= len(raw):
        size = struct.unpack_from(">I", raw, offset)[0]
        end = offset + size + 12
        if end > len(raw):
            raise ValidationError("PNG 파일이 잘렸거나 청크 길이가 올바르지 않습니다.")
        kind = raw[offset + 4:offset + 8]
        data = raw[offset + 8:end - 4]
        crc = struct.unpack_from(">I", raw, end - 4)[0]
        if crc != zlib.crc32(data, zlib.crc32(kind)):
            raise ValidationError("PNG 파일의 손상이 감지되었습니다 (청크 CRC 불일치).")
        if not seen_header:
            if kind != b"IHDR" or size != 13:
                raise ValidationError("PNG 이미지 헤더가 올바르지 않습니다.")
            w, h = struct.unpack_from(">II", data)
            if not w or not h:
                raise ValidationError("PNG 이미지 크기가 올바르지 않습니다.")
            seen_header = True
        elif kind == b"IHDR":
            raise ValidationError("PNG 이미지 헤더가 중복되어 있습니다.")
        if kind == b"IDAT":
            seen_image = True
        yield kind, data, offset, end
        offset = end
        if kind == b"IEND":
            if size or not seen_image or end != len(raw):
                raise ValidationError("PNG 이미지의 끝부분이 올바르지 않습니다.")
            return
    raise ValidationError("PNG 이미지가 완전하지 않습니다 (IEND 없음).")


def project_text(data):
    keyword, separator, rest = data.partition(b"\0")
    if keyword != KEY:
        return None
    if not separator or len(rest) < 4:
        raise ValidationError("PNG 안의 리그 데이터 헤더가 손상되었습니다.")
    compressed, method = rest[:2]
    if compressed not in (0, 1) or (compressed and method != 0):
        raise ValidationError("지원하지 않는 PNG 텍스트 압축 방식입니다.")
    fields = rest[2:].split(b"\0", 2)
    if len(fields) != 3:
        raise ValidationError("PNG 안의 리그 데이터 필드가 손상되었습니다.")
    payload = fields[2]
    if compressed:
        try:
            decoder = zlib.decompressobj()
            payload = decoder.decompress(payload, MAX_BYTES + 1)
            if len(payload) > MAX_BYTES or decoder.unconsumed_tail:
                raise ValidationError("PNG 안의 리그 데이터가 16 MB 제한을 초과합니다.")
            if not decoder.eof or decoder.unused_data:
                raise ValidationError("PNG 안의 압축된 리그 데이터가 손상되었습니다.")
        except zlib.error as exc:
            raise ValidationError("PNG 안의 압축된 리그 데이터를 읽을 수 없습니다.") from exc
    if len(payload) > MAX_BYTES:
        raise ValidationError("PNG 안의 리그 데이터가 16 MB 제한을 초과합니다.")
    return payload


def embed_document(png, document):
    # Use exactly the same envelope and validation as .gtlb files.
    deserialize_league(document)
    addition = chunk(b"iTXt", KEY + b"\0\x01\x00\0\0" + zlib.compress(document))
    output = bytearray(SIGNATURE)
    for kind, data, start, end in chunks(png):
        if kind in (b"iTXt", b"tEXt", b"zTXt") and data.partition(b"\0")[0] == KEY:
            continue  # Replace an existing project entry; never accumulate copies.
        if kind == b"IEND":
            output.extend(addition)
        output.extend(png[start:end])
    if len(output) > MAX_PNG_BYTES:
        raise ValidationError("데이터 포함 PNG가 128 MB 제한을 초과합니다.")
    return bytes(output)


def read_png_document(path):
    with Path(path).open("rb") as f:
        raw = f.read(MAX_PNG_BYTES + 1)
    found = None
    for kind, data, _, _ in chunks(raw):
        if kind in (b"tEXt", b"zTXt") and data.partition(b"\0")[0] == KEY:
            raise ValidationError("지원하지 않는 리그 데이터 청크입니다. 원본 데이터 포함 PNG를 사용하세요.")
        if kind == b"iTXt":
            payload = project_text(data)
            if payload is not None:
                if found is not None:
                    raise ValidationError("PNG에 리그 데이터가 중복되어 복원할 수 없습니다.")
                found = payload
    if found is None:
        raise ValidationError("이 PNG에는 복원할 리그 데이터가 없습니다. 일반 이미지이거나 데이터가 제거된 파일입니다. 원본 데이터 포함 PNG 또는 .gtlb 파일을 열어 주세요.")
    return found
