from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable


def supported_files(
    paths: Iterable[str | Path],
    supported_extensions: set[str],
    limit: int | None = None,
) -> list[str]:
    """드롭된 경로에서 존재하는 지원 파일만 중복 없이 고른다."""
    selected: list[str] = []
    seen: set[str] = set()

    for raw in paths:
        if not raw:
            continue
        path = Path(raw)
        if not path.is_file():
            continue
        if path.suffix.lower() not in supported_extensions:
            continue

        resolved = str(path.resolve())
        key = resolved.casefold()
        if key in seen:
            continue

        seen.add(key)
        selected.append(resolved)
        if limit is not None and len(selected) >= limit:
            break

    return selected


def first_supported_file(
    paths: Iterable[str | Path],
    supported_extensions: set[str],
) -> str | None:
    files = supported_files(paths, supported_extensions, limit=1)
    return files[0] if files else None
