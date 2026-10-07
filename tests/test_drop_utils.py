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
