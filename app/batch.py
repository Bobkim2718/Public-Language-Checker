from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from time import perf_counter

from .analyzer import PublicLanguageAnalyzer
from .document_loader import DocumentLoadError, SUPPORTED_EXTENSIONS, load_document
from .models import BatchDocumentResult


MAX_BATCH_FILES = 20
MAX_SINGLE_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_FILE_BYTES = 500 * 1024 * 1024
MAX_EXTRACTED_CHARS_PER_FILE = 5_000_000
MAX_TOTAL_EXTRACTED_CHARS = 25_000_000


class BatchLimitError(RuntimeError):
    pass


def select_batch_files(
    paths: Iterable[str | Path],
    limit: int = MAX_BATCH_FILES,
) -> list[Path]:
    selected: list[Path] = []
    seen: set[str] = set()

    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        key = str(path.resolve()).casefold()
        if key in seen:
            continue

        seen.add(key)
        selected.append(path)
        if len(selected) >= limit:
            break

    return selected


def validate_source_sizes(paths: list[Path]) -> None:
    total = 0
    for path in paths:
        size = path.stat().st_size
        if size > MAX_SINGLE_FILE_BYTES:
            raise BatchLimitError(
                f"‘{path.name}’의 파일 크기가 {format_bytes(size)}로 "
                f"안전 한도 {format_bytes(MAX_SINGLE_FILE_BYTES)}를 넘습니다."
            )
        total += size

    if total > MAX_TOTAL_FILE_BYTES:
        raise BatchLimitError(
            f"선택한 파일의 총 크기가 {format_bytes(total)}로 "
            f"안전 한도 {format_bytes(MAX_TOTAL_FILE_BYTES)}를 넘습니다."
        )


def analyze_files(
    paths: list[Path],
    analyzer: PublicLanguageAnalyzer,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[BatchDocumentResult]:
    if len(paths) > MAX_BATCH_FILES:
        raise BatchLimitError(f"한 번에 최대 {MAX_BATCH_FILES}개까지 분석할 수 있습니다.")

    validate_source_sizes(paths)

    results: list[BatchDocumentResult] = []
    total_chars = 0
    total = len(paths)

    for index, path in enumerate(paths, start=1):
        started = perf_counter()
        size = path.stat().st_size

        if progress:
            progress(index - 1, total, path.name)

        try:
            text = load_document(path)
            text_chars = len(text)

            if text_chars > MAX_EXTRACTED_CHARS_PER_FILE:
                raise BatchLimitError(
                    f"추출된 본문이 {text_chars:,}자로 "
                    f"문서별 안전 한도 {MAX_EXTRACTED_CHARS_PER_FILE:,}자를 넘습니다."
                )

            if total_chars + text_chars > MAX_TOTAL_EXTRACTED_CHARS:
                raise BatchLimitError(
                    f"배치의 추출 본문 합계가 안전 한도 "
                    f"{MAX_TOTAL_EXTRACTED_CHARS:,}자를 넘습니다."
                )

            total_chars += text_chars
            analysis = analyzer.analyze(text)
            results.append(
                BatchDocumentResult(
                    path=str(path),
                    name=path.name,
                    size_bytes=size,
                    text_chars=text_chars,
                    elapsed_seconds=perf_counter() - started,
                    text=text,
                    result=analysis,
                )
            )
        except (DocumentLoadError, BatchLimitError, OSError) as exc:
            results.append(
                BatchDocumentResult(
                    path=str(path),
                    name=path.name,
                    size_bytes=size,
                    text_chars=0,
                    elapsed_seconds=perf_counter() - started,
                    error=str(exc),
                )
            )

        if progress:
            progress(index, total, path.name)

    return results


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"
