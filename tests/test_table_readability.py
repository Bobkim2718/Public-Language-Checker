from app.models import DocumentContent, DocumentTableData, TableCellData
from app.table_readability import TableReadabilityAnalyzer


def make_table(rows: int, cols: int, cells: list[TableCellData]) -> DocumentTableData:
    return DocumentTableData(
        index=1,
        rows=rows,
        cols=cols,
        cells=cells,
        source_format="HWPX",
    )


def test_marks_text_only_formats_without_penalty():
    content = DocumentContent(
        text="일반 본문",
        table_structure_supported=False,
        table_structure_note="텍스트만 검사",
    )

    result = TableReadabilityAnalyzer({}).analyze(content)

    assert result.supported is False
    assert result.status == "텍스트만"
    assert result.issues == []


def test_wide_and_long_table_gets_improvement_recommendation():
    cells = []
    for col in range(9):
        text = "제목" if col < 8 else ("긴 설명 " * 60)
        cells.append(TableCellData(row=0, col=col, text=text))

    table = make_table(1, 9, cells)
    content = DocumentContent(
        text="",
        tables=[table],
        table_structure_supported=True,
    )

    result = TableReadabilityAnalyzer({}).analyze(content)

    assert result.status == "개선 권장"
    assert any("9열" in issue.message for issue in result.issues)
    assert any("긴 내용" in issue.message for issue in result.issues)


def test_merged_and_nested_table_gets_review_recommendation():
    cells = [
        TableCellData(row=0, col=0, text="구분", col_span=2),
        TableCellData(row=0, col=2, text="내용", col_span=2),
        TableCellData(row=1, col=0, text="1", row_span=2),
        TableCellData(row=1, col=1, text="내용", nested_table_count=1),
        TableCellData(row=1, col=2, text="값"),
        TableCellData(row=1, col=3, text="값"),
        TableCellData(row=2, col=1, text="내용"),
        TableCellData(row=2, col=2, text="값"),
        TableCellData(row=2, col=3, text="값"),
    ]
    table = make_table(3, 4, cells)
    content = DocumentContent(
        text="",
        tables=[table],
        table_structure_supported=True,
    )

    result = TableReadabilityAnalyzer({}).analyze(content)

    assert result.status == "검토 권장"
    assert any("병합" in issue.message for issue in result.issues)
    assert any("중첩 표" in issue.message for issue in result.issues)


def test_clean_small_table_is_good():
    cells = [
        TableCellData(row=0, col=0, text="항목"),
        TableCellData(row=0, col=1, text="내용"),
        TableCellData(row=1, col=0, text="대상"),
        TableCellData(row=1, col=1, text="고등학생"),
        TableCellData(row=2, col=0, text="기간"),
        TableCellData(row=2, col=1, text="10월"),
    ]
    content = DocumentContent(
        text="",
        tables=[make_table(3, 2, cells)],
        table_structure_supported=True,
    )

    result = TableReadabilityAnalyzer({}).analyze(content)

    assert result.status == "양호"
    assert result.issues == []
