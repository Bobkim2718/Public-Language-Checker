import struct
from pathlib import Path

from app.hwp_binary import parse_section_records
from app.document_loader import load_document


def record(tag_id: int, payload: bytes, level: int = 0) -> bytes:
    size = len(payload)
    if size < 0xFFF:
        header = tag_id | (level << 10) | (size << 20)
        return struct.pack("<I", header) + payload

    header = tag_id | (level << 10) | (0xFFF << 20)
    return struct.pack("<II", header, size) + payload


def wchar(code: int) -> bytes:
    return int(code).to_bytes(2, "little")


def test_parse_para_text_records():
    payload1 = "사업 운영 계획".encode("utf-16-le") + wchar(13)
    payload2 = "피드백과 모니터링".encode("utf-16-le") + wchar(13)

    data = (
        record(66, b"ignored")
        + record(67, payload1)
        + record(67, payload2)
    )

    paragraphs = parse_section_records(data)

    assert paragraphs == ["사업 운영 계획", "피드백과 모니터링"]


def test_hwp_control_characters_are_removed_without_losing_text():
    # 표/그림 계열 확장 컨트롤(11)은 총 8 WCHAR(16바이트).
    extended_control = wchar(11) + b"t\x00b\x00l\x00 \x00" + b"\x00" * 4 + wchar(11)
    payload = (
        "표 앞".encode("utf-16-le")
        + extended_control
        + "표 안의 피드백".encode("utf-16-le")
        + wchar(10)
        + "다음 줄".encode("utf-16-le")
        + wchar(13)
    )

    paragraphs = parse_section_records(record(67, payload))

    assert len(paragraphs) == 1
    assert "표 앞" in paragraphs[0]
    assert "표 안의 피드백" in paragraphs[0]
    assert "다음 줄" in paragraphs[0]
    assert "tbl" not in paragraphs[0]


def test_document_loader_prefers_direct_hwp_parser(tmp_path: Path, monkeypatch):
    path = tmp_path / "sample.hwp"
    path.write_bytes(b"dummy")

    monkeypatch.setattr(
        "app.document_loader.extract_hwp_text",
        lambda _path: "직접 파싱한 HWP 본문",
    )

    def should_not_call_automation(_path):
        raise AssertionError("Hancom Automation should not be called")

    monkeypatch.setattr(
        "app.document_loader.convert_hwp_to_hwpx",
        should_not_call_automation,
    )

    text = load_document(path)

    assert text == "직접 파싱한 HWP 본문"
