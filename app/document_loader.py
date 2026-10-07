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
from .models import DocumentContent, DocumentTableData, TableCellData


SUPPORTED_EXTENSIONS = {".txt", ".docx", ".pdf", ".hwp", ".hwpx"}


class DocumentLoadError(RuntimeError):
    pass


def load_document(path: str | Path) -> str:
    return load_document_content(path).text


def load_document_content(path: str | Path) -> DocumentContent:
    file_path = Path(path)
    ext = file_path.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise DocumentLoadError(
            f"지원하지 않는 파일 형식입니다: {ext or '(확장자 없음)'}"
        )

    try:
        if ext == ".txt":
            return DocumentContent(
                text=_load_txt(file_path),
                table_structure_supported=False,
                table_structure_note="TXT는 표 구조 정보가 없어 텍스트만 검사합니다.",
            )
        if ext == ".docx":
            return _load_docx_content(file_path)
        if ext == ".pdf":
            return DocumentContent(
                text=_load_pdf(file_path),
                table_structure_supported=False,
                table_structure_note="PDF는 현재 표의 행·열 구조를 안정적으로 복원하지 않고 텍스트만 검사합니다.",
            )
        if ext == ".hwp":
            return _load_hwp_content(file_path)
        if ext == ".hwpx":
            return _load_hwpx_content(file_path)
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


def _load_docx_content(path: Path) -> DocumentContent:
    doc = Document(path)
    parts: list[str] = []
    tables: list[DocumentTableData] = []

    for child in doc.element.body.iterchildren():
        local_name = _local_name(child.tag)

        if local_name == "p":
            paragraph = Paragraph(child, doc)
            text = paragraph.text.strip()
            if text:
                parts.append(text)

        elif local_name == "tbl":
            table = Table(child, doc)
            table_data = _docx_table_data(table, len(tables) + 1)
            tables.append(table_data)
            parts.extend(_render_table_lines(table_data))

    return DocumentContent(
        text="\n".join(parts),
        tables=tables,
        table_structure_supported=True,
        table_structure_note="DOCX 표의 행·열·병합 구조를 추출해 별도 가독성 진단을 수행합니다.",
    )


def _docx_table_data(table: Table, index: int) -> DocumentTableData:
    records: list[tuple[TableCellData, str | None]] = []
    by_position: dict[tuple[int, int], tuple[TableCellData, str | None]] = {}
    max_cols = 0

    row_elements = [
        child for child in list(table._tbl) if _local_name(child.tag) == "tr"
    ]

    for row_index, row_elem in enumerate(row_elements):
        col = 0
        tc_elements = [
            child for child in list(row_elem) if _local_name(child.tag) == "tc"
        ]

        for tc in tc_elements:
            col_span = max(1, _docx_grid_span(tc))
            vmerge = _docx_vmerge(tc)
            text = _normalize_cell_text(_xml_text(tc))
            paragraph_count = max(
                1,
                sum(1 for node in tc.iter() if _local_name(node.tag) == "p"),
            )
            nested_tables = sum(
                1 for node in tc.iter()
                if _local_name(node.tag) == "tbl" and node is not table._tbl
            )

            cell = TableCellData(
                row=row_index,
                col=col,
                text=text,
                row_span=1,
                col_span=col_span,
                paragraph_count=paragraph_count,
                nested_table_count=nested_tables,
            )
            records.append((cell, vmerge))
            by_position[(row_index, col)] = (cell, vmerge)

            col += col_span
            max_cols = max(max_cols, col)

    continuation_positions: set[tuple[int, int]] = set()

    for (row, col), (cell, vmerge) in list(by_position.items()):
        if vmerge != "restart":
            continue

        row_span = 1
        next_row = row + 1
        while True:
            next_record = by_position.get((next_row, col))
            if next_record is None or next_record[1] != "continue":
                break
            continuation_positions.add((next_row, col))
            row_span += 1
            next_row += 1
        cell.row_span = row_span

    cells = [
        cell
        for cell, _vmerge in records
        if (cell.row, cell.col) not in continuation_positions
    ]

    return DocumentTableData(
        index=index,
        rows=len(row_elements),
        cols=max_cols,
        cells=cells,
        source_format="DOCX",
    )


def _docx_grid_span(tc: ET.Element) -> int:
    for node in tc.iter():
        if _local_name(node.tag) != "gridSpan":
            continue
        value = _attribute_local(node, "val")
        parsed = _maybe_int(value)
        if parsed:
            return parsed
    return 1


def _docx_vmerge(tc: ET.Element) -> str | None:
    for node in tc.iter():
        if _local_name(node.tag) != "vMerge":
            continue
        value = (_attribute_local(node, "val") or "").lower()
        return "restart" if value == "restart" else "continue"
    return None


def _xml_text(elem: ET.Element) -> str:
    return "".join(
        node.text or ""
        for node in elem.iter()
        if _local_name(node.tag) == "t"
    )


def _load_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    if not text.strip():
        raise DocumentLoadError(
            "PDF에서 텍스트를 추출하지 못했습니다. 스캔 PDF는 OCR 기능이 추가될 때까지 지원하지 않습니다."
        )
    return text


def _load_hwp_content(path: Path) -> DocumentContent:
    """일반 HWP 5.x는 직접 파싱하고 표 구조 진단은 텍스트 수준으로 제한한다."""
    direct_error: Exception | None = None

    try:
        text = extract_hwp_text(path)
        return DocumentContent(
            text=text,
            table_structure_supported=False,
            table_structure_note=(
                "HWP 5.x는 본문과 표 안의 글자는 검사하지만, 현재 버전에서는 "
                "표의 행·열·병합 구조 가독성은 평가하지 않습니다. HWPX로 저장하면 구조 진단이 가능합니다."
            ),
        )
    except (HWPBinaryUnsupported, HWPBinaryError) as exc:
        direct_error = exc

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
        content = _load_hwpx_content(converted)
        content.table_structure_note = (
            "HWP 문서를 설치된 한/글로 임시 HWPX 변환하여 표 구조까지 진단했습니다."
        )
        return content
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _load_hwpx_content(path: Path) -> DocumentContent:
    chunks: list[str] = []
    tables: list[DocumentTableData] = []

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
                return DocumentContent(
                    text=preview,
                    table_structure_supported=False,
                    table_structure_note="HWPX 본문 XML을 찾지 못해 미리보기 텍스트만 검사합니다.",
                )
            raise DocumentLoadError("HWPX 본문 XML을 찾지 못했습니다.")

        for name in names:
            root = ET.fromstring(archive.read(name))
            chunks.extend(_extract_hwpx_section(root))

            parent_map = {child: parent for parent in root.iter() for child in parent}
            for elem in root.iter():
                if _local_name(elem.tag) != "tbl":
                    continue
                if _has_ancestor_with_name(elem, "tbl", parent_map):
                    continue
                tables.append(_hwpx_table_data(elem, len(tables) + 1))

        text = "\n".join(line for line in chunks if line.strip())
        if text.strip():
            return DocumentContent(
                text=text,
                tables=tables,
                table_structure_supported=True,
                table_structure_note="HWPX 표의 행·열·병합 구조를 추출해 별도 가독성 진단을 수행합니다.",
            )

        preview = _read_hwpx_preview(archive)
        if preview:
            return DocumentContent(
                text=preview,
                table_structure_supported=False,
                table_structure_note="HWPX 본문 추출에 실패해 미리보기 텍스트만 검사합니다.",
            )

    raise DocumentLoadError("HWPX에서 본문 텍스트를 추출하지 못했습니다.")


def _section_number(name: str) -> int:
    match = re.search(r"section(\d+)\.xml$", name)
    return int(match.group(1)) if match else 0


def _read_hwpx_preview(archive: zipfile.ZipFile) -> str:
    candidates = {name.lower(): name for name in archive.namelist()}
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
            if _has_ancestor_with_name(elem, "tbl", parent_map):
                continue
            text = _extract_paragraph_content(elem)
            if text:
                lines.append(text)
            continue

        if name == "tbl":
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


def _hwpx_table_data(table: ET.Element, index: int) -> DocumentTableData:
    declared_cols = _int_attr(table, ("colCnt", "colCount"), default=0)
    row_elements = [
        child for child in list(table) if _local_name(child.tag) == "tr"
    ]
    cells: list[TableCellData] = []
    inferred_cols = declared_cols

    for row_index, row in enumerate(row_elements):
        sequential_col = 0
        tc_elements = [
            child for child in list(row) if _local_name(child.tag) == "tc"
        ]

        for cell_elem in tc_elements:
            col_addr, row_addr = _cell_address(cell_elem)
            col_span, row_span = _cell_span(cell_elem)

            if col_addr is None:
                col_addr = sequential_col
            if row_addr is None:
                row_addr = row_index

            text = _extract_cell_content(cell_elem)
            paragraph_count = max(
                1,
                sum(1 for node in cell_elem.iter() if _local_name(node.tag) == "p"),
            )
            nested_tables = sum(
                1
                for node in cell_elem.iter()
                if _local_name(node.tag) == "tbl" and node is not table
            )

            cells.append(
                TableCellData(
                    row=row_addr,
                    col=col_addr,
                    text=text,
                    row_span=max(1, row_span),
                    col_span=max(1, col_span),
                    paragraph_count=paragraph_count,
                    nested_table_count=nested_tables,
                )
            )
            sequential_col = max(sequential_col, col_addr + max(1, col_span))
            inferred_cols = max(inferred_cols, sequential_col)

    inferred_rows = max(
        len(row_elements),
        max((cell.row + cell.row_span for cell in cells), default=0),
    )

    return DocumentTableData(
        index=index,
        rows=inferred_rows,
        cols=inferred_cols,
        cells=cells,
        source_format="HWPX",
    )


def _extract_hwpx_table(table: ET.Element) -> list[str]:
    return _render_table_lines(_hwpx_table_data(table, 0))


def _render_table_lines(table: DocumentTableData) -> list[str]:
    if table.rows <= 0 or table.cols <= 0:
        return []

    grid = [["" for _ in range(table.cols)] for _ in range(table.rows)]

    for cell in table.cells:
        if 0 <= cell.row < table.rows and 0 <= cell.col < table.cols:
            grid[cell.row][cell.col] = cell.text

    lines: list[str] = []
    for row in grid:
        trimmed = list(row)
        while trimmed and not trimmed[-1]:
            trimmed.pop()
        if any(trimmed):
            lines.append(" | ".join(trimmed))

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


def _attribute_local(elem: ET.Element, local_name: str) -> str | None:
    for key, value in elem.attrib.items():
        if _local_name(key) == local_name:
            return value
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
