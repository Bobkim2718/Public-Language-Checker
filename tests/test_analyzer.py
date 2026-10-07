from app.analyzer import PublicLanguageAnalyzer


RULES = {
    "weights": {
        "알기 쉬운 용어": 35,
        "알기 쉬운 문장": 35,
        "어문규범": 20,
        "한글 사용": 10,
    },
    "sentence": {"recommended_max_chars": 100, "severe_max_chars": 150},
}


def test_finds_dictionary_term():
    analyzer = PublicLanguageAnalyzer(
        [
            {
                "term": "피드백",
                "alternatives": ["반응", "회신"],
                "alt_text": "반응, 회신",
                "severity": "review",
                "source": "쉬운 우리말 공식 사전 스냅샷",
                "source_type": "OFFICIAL",
            }
        ],
        RULES,
    )
    result = analyzer.analyze("학생의 피드백을 반영한다.")
    assert result.total_score < 100
    assert result.stats["official_unique"] == 1
    assert any(issue.source_type == "OFFICIAL" for issue in result.issues)
    assert any("반응, 회신" == issue.suggestion for issue in result.issues)


def test_prefers_longer_dictionary_phrase():
    analyzer = PublicLanguageAnalyzer(
        [
            {
                "term": "데이터",
                "alternatives": ["자료"],
                "severity": "review",
                "source": "official",
                "source_type": "OFFICIAL",
            },
            {
                "term": "데이터 바우처",
                "alternatives": ["자료 이용권"],
                "severity": "review",
                "source": "official",
                "source_type": "OFFICIAL",
            },
        ],
        RULES,
    )
    result = analyzer.analyze("중소기업에 데이터 바우처를 지원한다.")
    term_issues = [x for x in result.issues if x.category == "알기 쉬운 용어"]
    assert len(term_issues) == 1
    assert term_issues[0].term == "데이터 바우처"


def test_ascii_keyword_respects_boundary():
    analyzer = PublicLanguageAnalyzer(
        [
            {
                "term": "AI",
                "alternatives": ["인공 지능"],
                "severity": "review",
                "source": "official",
                "source_type": "OFFICIAL",
            }
        ],
        RULES,
    )
    result = analyzer.analyze("MAIL 시스템과 AI 교육을 구분한다.")
    official = [x for x in result.issues if x.source_type == "OFFICIAL"]
    assert len(official) == 1
    assert official[0].term == "AI"


def test_official_latin_term_is_not_double_penalized_as_hangul_rule():
    analyzer = PublicLanguageAnalyzer(
        [
            {
                "term": "AI",
                "alternatives": ["인공 지능"],
                "severity": "review",
                "source": "official",
                "source_type": "OFFICIAL",
            }
        ],
        RULES,
    )
    result = analyzer.analyze("AI 교육을 운영한다.")
    assert any(x.source_type == "OFFICIAL" for x in result.issues)
    assert not any(x.category == "한글 사용" and x.term == "AI" for x in result.issues)


def test_flags_direct_latin_text():
    analyzer = PublicLanguageAnalyzer([], RULES)
    result = analyzer.analyze("XYZ 기반 교육을 운영한다.")
    assert result.scores["한글 사용"] < 10


def test_flags_long_sentence():
    analyzer = PublicLanguageAnalyzer([], RULES)
    text = "이 사업은 " + ("학생의 학습 활동을 지원하고 " * 10) + "운영한다."
    result = analyzer.analyze(text)
    assert result.scores["알기 쉬운 문장"] < 35


def test_repeated_official_term_is_aggregated_into_one_finding():
    analyzer = PublicLanguageAnalyzer(
        [
            {
                "term": "피드백",
                "alternatives": ["반응", "회신"],
                "alt_text": "반응, 회신",
                "severity": "review",
                "source": "official",
                "source_type": "OFFICIAL",
            }
        ],
        RULES,
    )

    result = analyzer.analyze(
        "피드백을 반영한다. 피드백을 정리한다. 피드백을 다시 확인한다."
    )

    term_issues = [x for x in result.issues if x.category == "알기 쉬운 용어"]

    assert len(term_issues) == 1
    assert term_issues[0].occurrence_count == 3
    assert len(term_issues[0].positions) == 3
    assert "3회" in term_issues[0].message
    assert result.stats["official_unique"] == 1
    assert result.stats["official_hits"] == 3
    assert result.stats["term_unique"] == 1
    assert result.stats["term_occurrences"] == 3


def test_repetition_penalty_is_dampened_not_linear():
    analyzer = PublicLanguageAnalyzer(
        [
            {
                "term": "피드백",
                "alternatives": ["반응"],
                "alt_text": "반응",
                "severity": "review",
                "source": "official",
                "source_type": "OFFICIAL",
            }
        ],
        RULES,
    )

    once = analyzer.analyze("피드백을 반영한다.")
    repeated = analyzer.analyze(" ".join(["피드백을 반영한다."] * 10))

    once_penalty = 35 - once.scores["알기 쉬운 용어"]
    repeated_penalty = 35 - repeated.scores["알기 쉬운 용어"]

    assert once_penalty >= 1
    assert repeated_penalty <= once_penalty + 1
    assert repeated.stats["official_hits"] == 10
    assert len([x for x in repeated.issues if x.category == "알기 쉬운 용어"]) == 1


def test_repeated_unknown_latin_token_is_aggregated():
    analyzer = PublicLanguageAnalyzer([], RULES)

    result = analyzer.analyze("XYZ 계획과 XYZ 운영, XYZ 결과를 검토한다.")

    hangul = [x for x in result.issues if x.category == "한글 사용"]
    assert len(hangul) == 1
    assert hangul[0].occurrence_count == 3
    assert "3회" in hangul[0].message
