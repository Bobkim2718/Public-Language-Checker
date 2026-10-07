from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class Issue:
    category: str
    severity: str
    message: str
    suggestion: str
    evidence: str
    source_type: str = ""
    term: str = ""
    sentence: str = ""
    start: int = -1
    end: int = -1
    occurrence_count: int = 1
    positions: List[tuple[int, int]] = field(default_factory=list)


@dataclass
class AnalysisResult:
    total_score: int
    scores: Dict[str, int]
    issues: List[Issue] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


@dataclass
class TableCellData:
    row: int
    col: int
    text: str
    row_span: int = 1
    col_span: int = 1
    paragraph_count: int = 1
    nested_table_count: int = 0

    @property
    def char_count(self) -> int:
        return len(self.text.strip())

    @property
    def merged(self) -> bool:
        return self.row_span > 1 or self.col_span > 1


@dataclass
class DocumentTableData:
    index: int
    rows: int
    cols: int
    cells: List[TableCellData] = field(default_factory=list)
    source_format: str = ""

    @property
    def total_chars(self) -> int:
        return sum(cell.char_count for cell in self.cells)

    @property
    def nonempty_cells(self) -> int:
        return sum(1 for cell in self.cells if cell.text.strip())

    @property
    def empty_cells(self) -> int:
        occupied = {
            (cell.row + r, cell.col + c)
            for cell in self.cells
            for r in range(max(1, cell.row_span))
            for c in range(max(1, cell.col_span))
        }
        slots = max(0, self.rows * self.cols)
        return max(0, slots - len(occupied))

    @property
    def merged_cells(self) -> int:
        return sum(1 for cell in self.cells if cell.merged)

    @property
    def nested_tables(self) -> int:
        return sum(cell.nested_table_count for cell in self.cells)

    @property
    def max_cell_chars(self) -> int:
        return max((cell.char_count for cell in self.cells), default=0)


@dataclass
class DocumentContent:
    text: str
    tables: List[DocumentTableData] = field(default_factory=list)
    table_structure_supported: bool = False
    table_structure_note: str = ""


@dataclass
class TableReadabilityIssue:
    table_index: int
    severity: str
    message: str
    suggestion: str
    row: int | None = None
    col: int | None = None


@dataclass
class TableAssessment:
    table_index: int
    status: str
    rows: int
    cols: int
    total_chars: int
    empty_cells: int
    merged_cells: int
    nested_tables: int
    max_cell_chars: int


@dataclass
class TableReadabilityResult:
    supported: bool
    status: str
    table_count: int
    issues: List[TableReadabilityIssue] = field(default_factory=list)
    assessments: List[TableAssessment] = field(default_factory=list)
    note: str = ""


@dataclass
class BatchDocumentResult:
    path: str
    name: str
    size_bytes: int
    text_chars: int
    elapsed_seconds: float
    text: str = ""
    result: AnalysisResult | None = None
    table_result: TableReadabilityResult | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.result is not None and not self.error
