from pathlib import Path

from app.drop_utils import first_supported_file


def test_selects_supported_existing_file(tmp_path: Path):
    unsupported = tmp_path / "note.csv"
    supported = tmp_path / "document.hwpx"
    unsupported.write_text("x", encoding="utf-8")
    supported.write_text("x", encoding="utf-8")

    result = first_supported_file(
        [unsupported, supported],
        {".hwpx", ".docx", ".pdf", ".txt"},
    )

    assert result == str(supported)


def test_ignores_nonexistent_and_unsupported_paths(tmp_path: Path):
    unsupported = tmp_path / "image.png"
    unsupported.write_text("x", encoding="utf-8")

    result = first_supported_file(
        [tmp_path / "missing.hwpx", unsupported],
        {".hwpx", ".docx", ".pdf", ".txt"},
    )

    assert result is None


def test_supported_files_returns_multiple_up_to_limit(tmp_path: Path):
    from app.drop_utils import supported_files

    paths = []
    for index in range(5):
        path = tmp_path / f"{index}.txt"
        path.write_text("x", encoding="utf-8")
        paths.append(path)

    result = supported_files(paths, {".txt"}, limit=3)

    assert len(result) == 3
    assert result[0].endswith("0.txt")


def test_hwp_is_supported_for_drop(tmp_path: Path):
    from app.drop_utils import supported_files

    path = tmp_path / "document.hwp"
    path.write_bytes(b"hwp")

    result = supported_files(
        [path],
        {".hwp", ".hwpx", ".docx", ".pdf", ".txt"},
    )

    assert result == [str(path.resolve())]
