from __future__ import annotations

from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {".txt", ".docx", ".pdf", ".hwpx"}


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
        if ext == ".hwpx":
            return _load_hwpx(file_path)
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
    """
    DOCX의 본문과 표를 실제 문서 순서대로 읽는다.
    표는 행 단위로 '셀1 | 셀2 | 셀3' 형식으로 보존한다.
    """
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
        cells: list[str] = []
        for cell in row.cells:
            text = _normalize_cell_text(cell.text)
            cells.append(text)

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


def _load_hwpx(path: Path) -> str:
    """
    HWPX 본문 XML을 문서 순서대로 읽는다.

    v2.1부터 표(tbl)는 행(tr)·셀(tc) 구조를 유지하여
    '셀1 | 셀2 | 셀3' 형식의 한 줄로 추출한다.
    표 안의 문단은 별도 일반 문단으로 중복 추출하지 않는다.
    """
    chunks: list[str] = []

    with zipfile.ZipFile(path, "r") as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if re.fullmatch(r"Contents/section\d+\.xml", name)
        )
        if not names:
            raise DocumentLoadError("HWPX 본문 XML을 찾지 못했습니다.")

        for name in names:
            root = ET.fromstring(archive.read(name))
            chunks.extend(_extract_hwpx_section(root))

    return "\n".join(line for line in chunks if line.strip())


def _extract_hwpx_section(root: ET.Element) -> list[str]:
    lines: list[str] = []
    parent_map = {child: parent for parent in root.iter() for child in parent}

    for elem in root.iter():
        local_name = _local_name(elem.tag)

        if local_name == "tbl":
            lines.extend(_extract_hwpx_table(elem))
            continue

        if local_name != "p":
            continue

        if _has_ancestor_with_name(elem, "tbl", parent_map):
            continue

        text = _extract_text(elem)
        if text:
            lines.append(text)

    if not lines:
        fallback = _extract_text(root)
        if fallback:
            lines.append(fallback)

    return lines


def _extract_hwpx_table(table: ET.Element) -> list[str]:
    lines: list[str] = []

    for row in table.iter():
        if _local_name(row.tag) != "tr":
            continue

        cells: list[str] = []
        for child in list(row):
            if _local_name(child.tag) != "tc":
                continue

            text = _extract_cell_text(child)
            cells.append(text)

        if any(cells):
            lines.append(" | ".join(cells))

    return lines


def _extract_cell_text(cell: ET.Element) -> str:
    paragraphs: list[str] = []

    for elem in cell.iter():
        if _local_name(elem.tag) != "p":
            continue
        text = _extract_text(elem)
        if text:
            paragraphs.append(text)

    if paragraphs:
        return " / ".join(paragraphs)

    return _extract_text(cell)


def _extract_text(elem: ET.Element) -> str:
    texts = [
        node.text
        for node in elem.iter()
        if _local_name(node.tag) == "t" and node.text
    ]
    return _normalize_cell_text("".join(texts))


def _normalize_cell_text(text: str) -> str:
    text = text.replace("\r", " ").replace("\n", " / ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?:\s*/\s*){2,}", " / ", text)
    return text.strip(" /")


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
