from __future__ import annotations

from pathlib import Path
import re
import struct
import zlib

import olefile


HWP_SIGNATURE = b"HWP Document File"
HWPTAG_PARA_TEXT = 67

CONTROL_EXTEND_CODES = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}
CONTROL_INLINE_CODES = {4, 5, 6, 7, 8, 9, 19, 20}
CONTROL_CHAR_CODES = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}


class HWPBinaryError(RuntimeError):
    pass


class HWPBinaryUnsupported(HWPBinaryError):
    pass


def extract_hwp_text(path: str | Path) -> str:
    """HWP 5.x OLE 문서에서 본문 문단 텍스트를 직접 추출한다.

    한/글 프로그램이나 외부 서버를 사용하지 않는다.
    """
    file_path = Path(path)

    if not olefile.isOleFile(str(file_path)):
        raise HWPBinaryUnsupported(
            "HWP 5.x OLE 문서가 아닙니다. HWPX로 저장한 뒤 다시 시도해 주세요."
        )

    with olefile.OleFileIO(str(file_path)) as ole:
        header = _read_stream(ole, "FileHeader")
        if len(header) < 40 or not header[:32].startswith(HWP_SIGNATURE):
            raise HWPBinaryUnsupported(
                "지원되는 HWP 5.x 문서 형식이 아닙니다."
            )

        properties = int.from_bytes(header[36:40], "little", signed=False)
        compressed = bool(properties & 0x01)
        encrypted = bool(properties & 0x02)
        distribution = bool(properties & 0x04)
        drm = bool(properties & 0x10)

        if encrypted:
            raise HWPBinaryUnsupported(
                "암호가 설정된 HWP 문서는 직접 분석할 수 없습니다."
            )
        if drm:
            raise HWPBinaryUnsupported(
                "DRM이 적용된 HWP 문서는 직접 분석할 수 없습니다."
            )

        section_names = _section_stream_names(ole)
        if not section_names:
            preview = _read_preview_text(ole)
            if preview:
                return preview
            raise HWPBinaryError("HWP 본문 스트림(BodyText/Section)을 찾지 못했습니다.")

        paragraphs: list[str] = []
        failures: list[str] = []

        for stream_name in section_names:
            raw = _read_stream(ole, stream_name)
            try:
                data = _decompress_section(raw, compressed)
                paragraphs.extend(parse_section_records(data))
            except Exception as exc:
                failures.append(f"{stream_name}: {exc}")

        text = "\n".join(p for p in paragraphs if p.strip())
        if text.strip():
            return text

        # 배포용 문서는 BodyText가 보호되어 있을 수 있어 미리보기만이라도 보조 사용.
        preview = _read_preview_text(ole)
        if preview:
            return preview

        if distribution:
            raise HWPBinaryUnsupported(
                "배포용 HWP 문서의 본문을 직접 추출하지 못했습니다. "
                "한/글에서 HWPX 또는 일반 HWP 사본으로 저장해 주세요."
            )

        detail = "; ".join(failures[:3])
        raise HWPBinaryError(
            "HWP 본문 텍스트를 추출하지 못했습니다."
            + (f" ({detail})" if detail else "")
        )


def parse_section_records(data: bytes) -> list[str]:
    """BodyText Section 레코드에서 PARA_TEXT(67)만 추출한다."""
    paragraphs: list[str] = []
    offset = 0
    length = len(data)

    while offset + 4 <= length:
        header = struct.unpack_from("<I", data, offset)[0]
        offset += 4

        tag_id = header & 0x3FF
        size = (header >> 20) & 0xFFF

        if size == 0xFFF:
            if offset + 4 > length:
                break
            size = struct.unpack_from("<I", data, offset)[0]
            offset += 4

        if size < 0 or offset + size > length:
            break

        payload = data[offset:offset + size]
        offset += size

        if tag_id != HWPTAG_PARA_TEXT:
            continue

        text = _decode_para_text(payload)
        if text:
            paragraphs.append(text)

    return paragraphs


def _decode_para_text(payload: bytes) -> str:
    """HWP PARA_TEXT WCHAR 배열에서 제어 문자를 제거하고 평문만 남긴다."""
    if len(payload) % 2:
        payload = payload[:-1]

    parts: list[str] = []
    offset = 0
    length = len(payload)

    while offset + 2 <= length:
        code = int.from_bytes(payload[offset:offset + 2], "little")
        offset += 2

        if code in CONTROL_EXTEND_CODES:
            # 확장 컨트롤은 총 8 WCHAR. 첫 WCHAR는 이미 읽었으므로 7 WCHAR 건너뜀.
            offset = min(length, offset + 14)
            continue

        if code in CONTROL_INLINE_CODES:
            if code == 9:
                parts.append(" ")
            offset = min(length, offset + 14)
            continue

        if code in CONTROL_CHAR_CODES:
            if code == 10:
                parts.append(" / ")
            elif code == 13:
                # 문단 끝 표시는 별도 줄 구분으로 처리되므로 여기서는 생략.
                pass
            elif code == 24:
                parts.append("-")
            elif code in {30, 31}:
                parts.append(" ")
            continue

        try:
            parts.append(chr(code))
        except ValueError:
            continue

    text = "".join(parts)
    text = text.replace("\x00", "")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?:\s*/\s*){2,}", " / ", text)
    return text.strip(" /")


def _decompress_section(raw: bytes, compressed: bool) -> bytes:
    if not compressed:
        return raw
    try:
        return zlib.decompress(raw, -15)
    except zlib.error as exc:
        # 일부 문서는 헤더 플래그와 실제 스트림 상태가 어긋난 사례가 있어
        # 레코드처럼 보이면 원본도 한 번 허용한다.
        if len(raw) >= 4:
            header = int.from_bytes(raw[:4], "little")
            tag_id = header & 0x3FF
            if 16 <= tag_id <= 200:
                return raw
        raise HWPBinaryError("압축된 HWP 본문을 해제하지 못했습니다.") from exc


def _section_stream_names(ole: olefile.OleFileIO) -> list[str]:
    names: list[tuple[int, str]] = []

    for parts in ole.listdir(streams=True, storages=False):
        if len(parts) != 2 or parts[0] != "BodyText":
            continue

        match = re.fullmatch(r"Section(\d+)", parts[1], flags=re.IGNORECASE)
        if not match:
            continue

        names.append((int(match.group(1)), "/".join(parts)))

    names.sort(key=lambda item: item[0])
    return [name for _, name in names]


def _read_preview_text(ole: olefile.OleFileIO) -> str:
    if not ole.exists("PrvText"):
        return ""

    raw = _read_stream(ole, "PrvText")
    for encoding in ("utf-16-le", "utf-8-sig", "utf-8", "cp949"):
        try:
            text = raw.decode(encoding).replace("\x00", "").strip()
            if text:
                return text
        except UnicodeDecodeError:
            continue

    return ""


def _read_stream(ole: olefile.OleFileIO, name: str) -> bytes:
    try:
        return ole.openstream(name).read()
    except OSError as exc:
        raise HWPBinaryError(f"HWP 스트림을 읽지 못했습니다: {name}") from exc
