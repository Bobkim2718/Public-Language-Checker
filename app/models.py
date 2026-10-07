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
class BatchDocumentResult:
    path: str
    name: str
    size_bytes: int
    text_chars: int
    elapsed_seconds: float
    text: str = ""
    result: AnalysisResult | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.result is not None and not self.error
