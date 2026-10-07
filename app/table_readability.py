from __future__ import annotations

from collections import Counter

from .models import (
    DocumentContent,
    DocumentTableData,
    TableAssessment,
    TableReadabilityIssue,
    TableReadabilityResult,
)


SEVERITY_ORDER = {
    "양호": 0,
    "참고": 1,
    "검토 권장": 2,
    "개선 권장": 3,
}


class TableReadabilityAnalyzer:
    """문서의 표 구조를 언어 점수와 분리하여 진단한다.

    폰트/색상/실제 렌더링을 보지 않고 행·열·병합·셀 텍스트 밀도 같은
    구조적 지표만 사용한다.
    """

    def __init__(self, rules: dict | None = None) -> None:
        all_rules = rules or {}
        config = all_rules.get("table_readability", {})
        self.wide_review = int(config.get("wide_columns_review", 7))
        self.wide_change = int(config.get("wide_columns_change", 9))
        self.long_review = int(config.get("long_cell_chars_review", 120))
        self.long_change = int(config.get("long_cell_chars_change", 220))
        self.multi_paragraph_review = int(config.get("cell_paragraphs_review", 5))
        self.empty_ratio_review = float(config.get("empty_ratio_review", 0.35))
        self.merged_ratio_review = float(config.get("merged_ratio_review", 0.30))
        self.dense_rows_review = int(config.get("dense_rows_review", 25))
        self.dense_cols_review = int(config.get("dense_cols_review", 5))

    def analyze(self, content: DocumentContent) -> TableReadabilityResult:
        if not content.table_structure_supported:
            return TableReadabilityResult(
                supported=False,
                status="텍스트만",
                table_count=0,
                note=content.table_structure_note
                or "이 형식은 현재 표 구조 진단을 지원하지 않습니다.",
            )

        if not content.tables:
            return TableReadabilityResult(
                supported=True,
                status="표 없음",
                table_count=0,
                note="구조화된 표가 발견되지 않았습니다.",
            )

        issues: list[TableReadabilityIssue] = []
        assessments: list[TableAssessment] = []

        for table in content.tables:
            table_issues = self._analyze_table(table)
            issues.extend(table_issues)
            status = _status_from_issues(table_issues)

            assessments.append(
                TableAssessment(
                    table_index=table.index,
                    status=status,
                    rows=table.rows,
                    cols=table.cols,
                    total_chars=table.total_chars,
                    empty_cells=table.empty_cells,
                    merged_cells=table.merged_cells,
                    nested_tables=table.nested_tables,
                    max_cell_chars=table.max_cell_chars,
                )
            )

        overall = max(
            (assessment.status for assessment in assessments),
            key=lambda status: SEVERITY_ORDER.get(status, 0),
            default="양호",
        )

        return TableReadabilityResult(
            supported=True,
            status=overall,
            table_count=len(content.tables),
            issues=issues,
            assessments=assessments,
            note=(
                "표 가독성은 행·열 수, 병합, 빈 셀, 셀 안 글자 수, 중첩 표 등 "
                "구조 지표를 이용한 자체 진단입니다. 글꼴·색상·실제 인쇄 배치는 아직 평가하지 않습니다."
            ),
        )

    def _analyze_table(self, table: DocumentTableData) -> list[TableReadabilityIssue]:
        issues: list[TableReadabilityIssue] = []

        if table.cols >= self.wide_change:
            issues.append(
                TableReadabilityIssue(
                    table_index=table.index,
                    severity="개선 권장",
                    message=f"{table.cols}열 표로 가로 정보량이 매우 많습니다.",
                    suggestion="관련 열을 묶거나 표를 둘 이상으로 나누어 한 화면에서 비교해야 할 정보만 남겨 보세요.",
                )
            )
        elif table.cols >= self.wide_review:
            issues.append(
                TableReadabilityIssue(
                    table_index=table.index,
                    severity="검토 권장",
                    message=f"{table.cols}열 표로 가로 정보량이 많은 편입니다.",
                    suggestion="열 제목과 본문이 한눈에 대응되는지 확인하고, 중요도가 낮은 열은 분리하는 것을 검토하세요.",
                )
            )

        change_cells = [
            cell for cell in table.cells if cell.char_count >= self.long_change
        ]
        review_cells = [
            cell
            for cell in table.cells
            if self.long_review <= cell.char_count < self.long_change
        ]

        if change_cells:
            first = max(change_cells, key=lambda cell: cell.char_count)
            issues.append(
                TableReadabilityIssue(
                    table_index=table.index,
                    severity="개선 권장",
                    row=first.row + 1,
                    col=first.col + 1,
                    message=(
                        f"{len(change_cells)}개 셀에 {self.long_change}자 이상의 긴 내용이 들어 있습니다. "
                        f"가장 긴 셀은 {first.char_count}자입니다."
                    ),
                    suggestion="긴 설명은 표 아래 본문이나 별도 항목으로 옮기고, 셀에는 핵심어·수치·짧은 설명을 남기는 것을 권장합니다.",
                )
            )
        elif review_cells:
            first = max(review_cells, key=lambda cell: cell.char_count)
            issues.append(
                TableReadabilityIssue(
                    table_index=table.index,
                    severity="검토 권장",
                    row=first.row + 1,
                    col=first.col + 1,
                    message=(
                        f"{len(review_cells)}개 셀에 {self.long_review}자 이상의 긴 내용이 들어 있습니다. "
                        f"가장 긴 셀은 {first.char_count}자입니다."
                    ),
                    suggestion="셀 내용을 항목화하거나 행을 나누어 훑어보기 쉽게 만들 수 있는지 검토하세요.",
                )
            )

        paragraph_heavy = [
            cell
            for cell in table.cells
            if cell.paragraph_count >= self.multi_paragraph_review
        ]
        if paragraph_heavy:
            first = max(paragraph_heavy, key=lambda cell: cell.paragraph_count)
            issues.append(
                TableReadabilityIssue(
                    table_index=table.index,
                    severity="검토 권장",
                    row=first.row + 1,
                    col=first.col + 1,
                    message=(
                        f"{len(paragraph_heavy)}개 셀에 여러 문단이 집중되어 있습니다. "
                        f"최대 {first.paragraph_count}개 문단입니다."
                    ),
                    suggestion="하나의 셀에 여러 내용이 겹쳐 있다면 행을 나누거나 본문 설명으로 분리해 보세요.",
                )
            )

        slot_count = max(1, table.rows * table.cols)
        empty_ratio = table.empty_cells / slot_count
        if slot_count >= 12 and empty_ratio >= self.empty_ratio_review:
            issues.append(
                TableReadabilityIssue(
                    table_index=table.index,
                    severity="검토 권장",
                    message=(
                        f"표 공간의 약 {empty_ratio * 100:.0f}%가 빈 셀입니다 "
                        f"({table.empty_cells}/{slot_count})."
                    ),
                    suggestion="빈 칸이 의미 있는 구분인지 확인하고, 불필요한 공백 행·열이나 반복 구조를 줄여 표를 단순화해 보세요.",
                )
            )

        actual_cells = max(1, len(table.cells))
        merged_ratio = table.merged_cells / actual_cells
        if actual_cells >= 6 and merged_ratio >= self.merged_ratio_review:
            issues.append(
                TableReadabilityIssue(
                    table_index=table.index,
                    severity="검토 권장",
                    message=(
                        f"병합된 셀이 {table.merged_cells}개로 전체 셀 구조에서 비중이 높은 편입니다 "
                        f"(약 {merged_ratio * 100:.0f}%)."
                    ),
                    suggestion="병합이 제목 구분에 필요한 수준인지 확인하고, 데이터 영역의 과도한 병합은 줄이는 것을 권장합니다.",
                )
            )

        if table.nested_tables:
            issues.append(
                TableReadabilityIssue(
                    table_index=table.index,
                    severity="검토 권장",
                    message=f"셀 안에 중첩 표가 {table.nested_tables}개 포함되어 있습니다.",
                    suggestion="중첩 표는 읽는 순서가 복잡해질 수 있으므로 별도 표나 본문 항목으로 분리할 수 있는지 검토하세요.",
                )
            )

        if (
            table.rows >= self.dense_rows_review
            and table.cols >= self.dense_cols_review
        ):
            issues.append(
                TableReadabilityIssue(
                    table_index=table.index,
                    severity="검토 권장",
                    message=f"{table.rows}행 × {table.cols}열의 큰 표입니다.",
                    suggestion="긴 표는 소제목별로 나누거나 핵심 행·열을 먼저 제시해 탐색 부담을 줄이는 것을 검토하세요.",
                )
            )

        return issues


def _status_from_issues(issues: list[TableReadabilityIssue]) -> str:
    if not issues:
        return "양호"
    counts = Counter(issue.severity for issue in issues)
    if counts.get("개선 권장"):
        return "개선 권장"
    if counts.get("검토 권장"):
        return "검토 권장"
    return "참고"
