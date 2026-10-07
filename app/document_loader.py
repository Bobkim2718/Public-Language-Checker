from __future__ import annotations

from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET

from docx import Document
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
    doc = Document(path)
    parts: list[str] = []

    for p in doc.paragraphs:
        if p.text.strip():
            parts.append(p.text)

    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))

    return "\n".join(parts)


def _load_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    if not text.strip():
        raise DocumentLoadError(
            "PDF에서 텍스트를 추출하지 못했습니다. 스캔 PDF는 OCR 기능이 추가될 때까지 지원하지 않습니다."
        )
    return text


def _load_hwpx(path: Path) -> str:
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
            current: list[str] = []
            for elem in root.iter():
                local_name = elem.tag.rsplit("}", 1)[-1]
                if local_name == "t" and elem.text:
                    current.append(elem.text)
                elif local_name in {"p", "tr"} and current:
                    chunks.append("".join(current))
                    current = []
            if current:
                chunks.append("".join(current))

    return "\n".join(line for line in chunks if line.strip())
