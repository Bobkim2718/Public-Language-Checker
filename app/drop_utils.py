from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable


def first_supported_file(
    paths: Iterable[str | Path],
    supported_extensions: set[str],
) -> str | None:
    """드롭된 경로 중 실제 존재하고 지원 확장자인 첫 파일을 고른다."""
    for raw in paths:
        if not raw:
            continue
        path = Path(raw)
        if not path.is_file():
            continue
        if path.suffix.lower() in supported_extensions:
            return str(path)
    return None
