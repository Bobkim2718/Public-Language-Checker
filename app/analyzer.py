from __future__ import annotations

import re
from collections import Counter

from .models import AnalysisResult, Issue


CATEGORY_TERMS = "알기 쉬운 용어"
CATEGORY_SENTENCES = "알기 쉬운 문장"
CATEGORY_NORMS = "어문규범"
CATEGORY_HANGUL = "한글 사용"


class PublicLanguageAnalyzer:
    def __init__(self, terms: list[dict], rules: dict) -> None:
        self.terms = terms
        self.rules = rules
        self.weights = rules.get(
            "weights",
            {
                CATEGORY_TERMS: 35,
                CATEGORY_SENTENCES: 35,
                CATEGORY_NORMS: 20,
                CATEGORY_HANGUL: 10,
            },
        )

    def analyze(self, text: str) -> AnalysisResult:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        issues: list[Issue] = []

        term_penalty = self._check_terms(normalized, issues)
        sentence_penalty = self._check_sentences(normalized, issues)
        norm_penalty = self._check_norms(normalized, issues)
        hangul_penalty = self._check_hangul(normalized, issues)

        penalties = {
            CATEGORY_TERMS: term_penalty,
            CATEGORY_SENTENCES: sentence_penalty,
            CATEGORY_NORMS: norm_penalty,
            CATEGORY_HANGUL: hangul_penalty,
        }

        scores = {
            category: max(0, int(weight) - min(int(weight), int(penalties.get(category, 0))))
            for category, weight in self.weights.items()
        }
        total = sum(scores.values())

        severity_counts = Counter(issue.severity for issue in issues)
        return AnalysisResult(
            total_score=total,
            scores=scores,
            issues=issues,
            stats={
                "characters": len(normalized),
                "issues": len(issues),
                "change": severity_counts.get("변경 권장", 0),
                "review": severity_counts.get("검토 권장", 0),
                "reference": severity_counts.get("참고", 0),
            },
        )

    def _check_terms(self, text: str, issues: list[Issue]) -> int:
        penalty = 0.0
        severity_cost = {"change": 1.5, "review": 0.8, "reference": 0.2}
        severity_label = {
            "change": "변경 권장",
            "review": "검토 권장",
            "reference": "참고",
        }

        for entry in self.terms:
            term = str(entry.get("term", "")).strip()
            if not term:
                continue

            matches = list(re.finditer(re.escape(term), text, flags=re.IGNORECASE))
            if not matches:
                continue

            severity = str(entry.get("severity", "review"))
            alternatives = [str(x) for x in entry.get("alternatives", []) if str(x).strip()]
            source = str(entry.get("source", "사전 데이터"))
            suggestion = ", ".join(alternatives) if alternatives else "문맥에 맞는 쉬운 표현을 검토하세요."

            for match in matches:
                sentence = _sentence_around(text, match.start())
                issues.append(
                    Issue(
                        category=CATEGORY_TERMS,
                        severity=severity_label.get(severity, "검토 권장"),
                        message=f"‘{match.group(0)}’ 표현을 검토해 보세요.",
                        suggestion=suggestion,
                        evidence=source,
                        sentence=sentence,
                        start=match.start(),
                        end=match.end(),
                    )
                )
            penalty += severity_cost.get(severity, 0.8) * min(len(matches), 3)

        return round(min(self.weights.get(CATEGORY_TERMS, 35), penalty))

    def _check_sentences(self, text: str, issues: list[Issue]) -> int:
        config = self.rules.get("sentence", {})
        recommended = int(config.get("recommended_max_chars", 100))
        severe = int(config.get("severe_max_chars", 150))
        penalty = 0

        for sentence, start in _split_sentences(text):
            length = len(re.sub(r"\s+", " ", sentence).strip())
            if length <= recommended:
                continue

            cost = 3 if length > severe else 2
            penalty += cost
            issues.append(
                Issue(
                    category=CATEGORY_SENTENCES,
                    severity="변경 권장" if length > severe else "검토 권장",
                    message=f"문장이 {length}자로 길어 권장 기준 {recommended}자를 넘습니다.",
                    suggestion="한 문장에 하나의 중심 내용만 남기고 둘 이상의 문장으로 나누어 보세요.",
                    evidence="쉬운 공문서 쓰기: 짧고 명료한 문장",
                    sentence=sentence.strip(),
                    start=start,
                    end=start + len(sentence),
                )
            )

        connective_pattern = re.compile(r"(하며|하고|하고자|함으로써|뿐만 아니라|그리고).{0,80}(하며|하고|하고자|함으로써|뿐만 아니라|그리고)")
        for match in connective_pattern.finditer(text):
            issues.append(
                Issue(
                    category=CATEGORY_SENTENCES,
                    severity="검토 권장",
                    message="여러 행동이나 내용을 한 문장에 연달아 연결한 부분이 있습니다.",
                    suggestion="핵심 행동별로 문장을 나누어 의미 관계를 분명하게 해 보세요.",
                    evidence="쉬운 공문서 쓰기: 한 문장에는 하나의 화제",
                    sentence=_sentence_around(text, match.start()),
                    start=match.start(),
                    end=match.end(),
                )
            )
            penalty += 1

        return min(self.weights.get(CATEGORY_SENTENCES, 35), penalty)

    def _check_norms(self, text: str, issues: list[Issue]) -> int:
        penalty = 0

        for match in re.finditer(r"(?m)[^\n]\s{2,}[^\n]", text):
            issues.append(
                Issue(
                    category=CATEGORY_NORMS,
                    severity="검토 권장",
                    message="문장 안에 불필요하게 연속된 공백이 있습니다.",
                    suggestion="띄어쓰기를 확인하여 공백을 한 칸으로 정리하세요.",
                    evidence="어문규범 및 표기 일관성 검사",
                    sentence=_sentence_around(text, match.start()),
                    start=match.start(),
                    end=match.end(),
                )
            )
            penalty += 1

        for match in re.finditer(r"[가-힣][,.;:!?]", text):
            # 정상적인 문장부호 사용은 문제로 보지 않는다.
            pass

        latin_tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9_-]{1,}\b", text)
        variants: dict[str, set[str]] = {}
        for token in latin_tokens:
            variants.setdefault(token.lower(), set()).add(token)
        for forms in variants.values():
            if len(forms) > 1:
                ordered = sorted(forms)
                issues.append(
                    Issue(
                        category=CATEGORY_NORMS,
                        severity="검토 권장",
                        message=f"같은 영문 표현의 대소문자 표기가 혼용됩니다: {', '.join(ordered)}",
                        suggestion=f"문서 전체에서 표기를 하나로 통일하세요. 예: {ordered[0]}",
                        evidence="쉬운 공문서 쓰기: 문서 내부 표기 일관성",
                    )
                )
                penalty += 1

        return min(self.weights.get(CATEGORY_NORMS, 20), penalty)

    def _check_hangul(self, text: str, issues: list[Issue]) -> int:
        penalty = 0
        seen: set[str] = set()
        token_pattern = re.compile(r"\b[A-Za-z][A-Za-z0-9&+._-]{1,}\b")

        for match in token_pattern.finditer(text):
            token = match.group(0)
            lowered = token.lower()
            if lowered in seen or _looks_like_url_or_email(text, match.start(), match.end()):
                continue
            seen.add(lowered)

            if _inside_parentheses(text, match.start()):
                issues.append(
                    Issue(
                        category=CATEGORY_HANGUL,
                        severity="참고",
                        message=f"외국 글자 ‘{token}’가 괄호 안에 병기되어 있습니다.",
                        suggestion="뜻을 정확히 전달하는 데 필요한 병기인지 확인하세요.",
                        evidence="쉬운 공문서 쓰기: 필요한 경우에 한해 괄호 안에 외국 글자 병기",
                        sentence=_sentence_around(text, match.start()),
                        start=match.start(),
                        end=match.end(),
                    )
                )
                continue

            issues.append(
                Issue(
                    category=CATEGORY_HANGUL,
                    severity="변경 권장",
                    message=f"외국 글자 ‘{token}’가 본문에 직접 사용되었습니다.",
                    suggestion="가능하면 한글 또는 우리말 명칭을 먼저 쓰고, 원어가 필요하면 처음 한 번 괄호 안에 병기하세요.",
                    evidence="쉬운 공문서 쓰기: 공문서는 한글로 작성",
                    sentence=_sentence_around(text, match.start()),
                    start=match.start(),
                    end=match.end(),
                )
            )
            penalty += 1

        return min(self.weights.get(CATEGORY_HANGUL, 10), penalty)


def _split_sentences(text: str) -> list[tuple[str, int]]:
    results: list[tuple[str, int]] = []
    start = 0
    for match in re.finditer(r"(?<=[.!?])\s+|\n+", text):
        chunk = text[start:match.start()]
        if chunk.strip():
            results.append((chunk, start))
        start = match.end()
    tail = text[start:]
    if tail.strip():
        results.append((tail, start))
    return results


def _sentence_around(text: str, index: int) -> str:
    left = max(text.rfind("\n", 0, index), text.rfind(".", 0, index), text.rfind("?", 0, index), text.rfind("!", 0, index))
    right_candidates = [
        x for x in (text.find("\n", index), text.find(".", index), text.find("?", index), text.find("!", index)) if x != -1
    ]
    right = min(right_candidates) + 1 if right_candidates else min(len(text), index + 180)
    return text[left + 1:right].strip()


def _inside_parentheses(text: str, index: int) -> bool:
    left = text.rfind("(", 0, index)
    right = text.rfind(")", 0, index)
    return left > right


def _looks_like_url_or_email(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - 20): min(len(text), end + 30)]
    return "http://" in window or "https://" in window or "@" in window or "www." in window
