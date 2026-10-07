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


@dataclass
class AnalysisResult:
    total_score: int
    scores: Dict[str, int]
    issues: List[Issue] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)
