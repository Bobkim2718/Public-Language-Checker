from __future__ import annotations

from pathlib import Path
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from .hancom_loader import HancomAutomationError, convert_hwp_to_hwpx
from .hwp_binary import HWPBinaryError, HWPBinaryUnsupported, extract_hwp_text


SUPPORTED_EXTENSIONS = {".txt", ".docx", ".pdf", ".hwp", ".hwpx"}


class DocumentLoadError(RuntimeError):
    pass


def load_document(path: str | Path) -> str:
    file_path = Path(path)
    ext = file_path.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise DocumentLoadError(
            f"지원하지 않는 파일 형식입니다: {ext or '(확장자 없음)'}"
        )

    try:
        if ext == ".txt":
            return _load_txt(file_path)
        if ext == ".docx":
            return _load_docx(file_path)
        if ext == ".pdf":
            return _load_pdf(file_path)
        if ext == ".hwp":
            return _load_hwp(file_path)
        if ext == ".hwpx":
            return _load_hwpx(file_path)
    except DocumentLoadError:
        raise
    except HancomAutomationError as exc:
        raise DocumentLoadError(str(exc)) from exc
    except Exception as exc:
        raise DocumentLoadError(f"문서를 읽는 중 오류가 발생했습니다: {exc}") from exc

    raise DocumentLoadError("문서를 읽을 수 없습니다.")


def _load_txt(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentLoadError("TXT 파일의 문자 인코딩을 확인할 수 없습니다.")


def _load_docx(path: Path) -> str:
    doc = Document(path)
    parts: list[str] = []

    for child in doc.element.body.iterchildren():
        local_name = child.tag.rsplit("}", 1)[-1]

        if local_name == "p":
            paragraph = Paragraph(child, doc)
            text = paragraph.text.strip()
            if text:
                parts.append(text)

        elif local_name == "tbl":
            table = Table(child, doc)
            parts.extend(_docx_table_lines(table))

    return "\n".join(parts)


def _docx_table_lines(table: Table) -> list[str]:
    lines: list[str] = []

    for row in table.rows:
        cells = [_normalize_cell_text(cell.text) for cell in row.cells]
        if any(cells):
            lines.append(" | ".join(cells))

    return lines


def _load_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    if not text.strip():
        raise DocumentLoadError(
            "PDF에서 텍스트를 추출하지 못했습니다. 스캔 PDF는 OCR 기능이 추가될 때까지 지원하지 않습니다."
        )
    return text


def _load_hwp(path: Path) -> str:
    """HWP 5.x를 직접 파싱하고, 필요할 때만 설치된 한/글을 보조 경로로 사용."""
    direct_error: Exception | None = None

    try:
        return extract_hwp_text(path)
    except (HWPBinaryUnsupported, HWPBinaryError) as exc:
        direct_error = exc

    # 직접 파싱이 불가능한 구형/보호 문서는 설치된 한/글이 있으면 HWPX 변환을 시도한다.
    try:
        converted = convert_hwp_to_hwpx(path)
    except HancomAutomationError:
        if direct_error is not None:
            raise DocumentLoadError(
                f"{direct_error}\n\n"
                "이 문서는 직접 분석하지 못했고, 설치된 한/글 Automation도 사용할 수 없습니다. "
                "가능하면 한/글에서 HWPX로 저장한 뒤 다시 열어 주세요."
            ) from direct_error
        raise

    temp_dir = converted.parent
    try:
        return _load_hwpx(converted)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _load_hwpx(path: Path) -> str:
    chunks: list[str] = []

    with zipfile.ZipFile(path, "r") as archive:
        names = [
            name
            for name in archive.namelist()
            if re.fullmatch(r"Contents/section\d+\.xml", name)
        ]
        names.sort(key=_section_number)

        if not names:
            preview = _read_hwpx_preview(archive)
            if preview:
                return preview
            raise DocumentLoadError("HWPX 본문 XML을 찾지 못했습니다.")

        for name in names:
            root = ET.fromstring(archive.read(name))
            chunks.extend(_extract_hwpx_section(root))

        text = "\n".join(line for line in chunks if line.strip())
        if text.strip():
            return text

        preview = _read_hwpx_preview(archive)
        if preview:
            return preview

    raise DocumentLoadError("HWPX에서 본문 텍스트를 추출하지 못했습니다.")


def _section_number(name: str) -> int:
    match = re.search(r"section(\d+)\.xml$", name)
    return int(match.group(1)) if match else 0


def _read_hwpx_preview(archive: zipfile.ZipFile) -> str:
    candidates = {
        name.lower(): name
        for name in archive.namelist()
    }
    real_name = candidates.get("preview/prvtext.txt")
    if not real_name:
        return ""

    raw = archive.read(real_name)
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp949"):
        try:
            text = raw.decode(encoding)
            if text.strip():
                return text.strip()
        except UnicodeDecodeError:
            continue
    return ""


def _extract_hwpx_section(root: ET.Element) -> list[str]:
    lines: list[str] = []
    parent_map = {child: parent for parent in root.iter() for child in parent}

    for elem in root.iter():
        name = _local_name(elem.tag)

        if name == "p":
            # 표 셀 내부 문단은 바깥 표를 처리할 때 재귀적으로 읽는다.
            if _has_ancestor_with_name(elem, "tbl", parent_map):
                continue
            text = _extract_paragraph_content(elem)
            if text:
                lines.append(text)
            continue

        if name == "tbl":
            # 일반 HWPX 표는 문단(run) 안에 있으므로 그 문단 처리에서 이미 읽힌다.
            # 문단 밖에 직접 놓인 특수 표만 여기에서 처리한다.
            if _has_ancestor_with_name(elem, "p", parent_map):
                continue
            if _has_ancestor_with_name(elem, "tbl", parent_map):
                continue
            lines.extend(_extract_hwpx_table(elem))

    if not lines:
        fallback = _extract_text_no_tables(root)
        if fallback:
            lines.append(fallback)

    return lines


def _extract_hwpx_table(table: ET.Element) -> list[str]:
    """병합셀과 열 주소를 고려하여 행 단위 텍스트 그리드를 복원한다."""
    col_count = _int_attr(table, ("colCnt", "colCount"), default=0)
    rows: list[list[str]] = []
    inferred_max = col_count

    row_elements = [
        child for child in list(table) if _local_name(child.tag) == "tr"
    ]

    for row_index, row in enumerate(row_elements):
        cells = [
            child for child in list(row) if _local_name(child.tag) == "tc"
        ]

        placements: list[tuple[int, int, str]] = []
        sequential_col = 0

        for cell in cells:
            col_addr, _row_addr = _cell_address(cell)
            col_span, _row_span = _cell_span(cell)

            if col_addr is None:
                col_addr = sequential_col
            if col_span < 1:
                col_span = 1

            text = _extract_cell_content(cell)
            placements.append((col_addr, col_span, text))
            sequential_col = max(sequential_col, col_addr + col_span)
            inferred_max = max(inferred_max, col_addr + col_span)

        width = max(1, inferred_max, sequential_col)
        grid = [""] * width

        for col_addr, col_span, text in placements:
            if col_addr >= len(grid):
                grid.extend([""] * (col_addr - len(grid) + col_span))
            grid[col_addr] = text
            for offset in range(1, col_span):
                index = col_addr + offset
                if index >= len(grid):
                    grid.append("")
                elif not grid[index]:
                    grid[index] = ""

        rows.append(grid)

    lines: list[str] = []
    for grid in rows:
        # 오른쪽 끝의 빈 병합 셀은 제거하되 중간 빈 열은 유지한다.
        while grid and not grid[-1]:
            grid.pop()
        if any(grid):
            lines.append(" | ".join(grid))

    return lines


def _cell_address(cell: ET.Element) -> tuple[int | None, int | None]:
    for node in cell.iter():
        name = _local_name(node.tag)
        if name in {"cellAddr", "tcPr"}:
            col = _maybe_int(node.attrib.get("colAddr"))
            row = _maybe_int(node.attrib.get("rowAddr"))
            if col is not None or row is not None:
                return col, row
    return None, None


def _cell_span(cell: ET.Element) -> tuple[int, int]:
    for node in cell.iter():
        name = _local_name(node.tag)
        if name in {"cellSpan", "tcPr"}:
            col_span = _maybe_int(node.attrib.get("colSpan"))
            row_span = _maybe_int(node.attrib.get("rowSpan"))
            if col_span is not None or row_span is not None:
                return col_span or 1, row_span or 1
    return 1, 1


def _extract_cell_content(cell: ET.Element) -> str:
    pieces: list[str] = []

    # 셀의 subList 내부 문단을 문서 순서대로 처리한다.
    sublists = [
        node for node in list(cell) if _local_name(node.tag) == "subList"
    ]
    containers = sublists or [cell]

    for container in containers:
        for child in list(container):
            name = _local_name(child.tag)
            if name == "p":
                text = _extract_paragraph_content(child)
                if text:
                    pieces.append(text)
            elif name == "tbl":
                nested = _extract_hwpx_table(child)
                if nested:
                    pieces.append(" / ".join(nested))

    if not pieces:
        fallback = _extract_text_no_tables(cell)
        if fallback:
            pieces.append(fallback)

    return " / ".join(_dedupe_adjacent(pieces))


def _extract_paragraph_content(paragraph: ET.Element) -> str:
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        name = _local_name(node.tag)

        if name == "tbl":
            nested_lines = _extract_hwpx_table(node)
            if nested_lines:
                parts.append(" / ".join(nested_lines))
            return

        if name == "t" and node.text:
            parts.append(node.text)
            return

        if name == "tab":
            parts.append(" ")
            return

        if name in {"lineBreak", "br"}:
            parts.append(" / ")
            return

        for child in list(node):
            walk(child)

    walk(paragraph)
    return _normalize_cell_text("".join(parts))


def _extract_text_no_tables(elem: ET.Element) -> str:
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        name = _local_name(node.tag)
        if name == "tbl":
            return
        if name == "t" and node.text:
            parts.append(node.text)
            return
        for child in list(node):
            walk(child)

    walk(elem)
    return _normalize_cell_text("".join(parts))


def _dedupe_adjacent(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        value = item.strip()
        if not value:
            continue
        if result and result[-1] == value:
            continue
        result.append(value)
    return result


def _normalize_cell_text(text: str) -> str:
    text = text.replace("\r", " ").replace("\n", " / ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?:\s*/\s*){2,}", " / ", text)
    return text.strip(" /")


def _int_attr(elem: ET.Element, names: tuple[str, ...], default: int) -> int:
    for name in names:
        value = _maybe_int(elem.attrib.get(name))
        if value is not None:
            return value
    return default


def _maybe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _has_ancestor_with_name(
    elem: ET.Element,
    target_name: str,
    parent_map: dict[ET.Element, ET.Element],
) -> bool:
    current = parent_map.get(elem)
    while current is not None:
        if _local_name(current.tag) == target_name:
            return True
        current = parent_map.get(current)
    return False
