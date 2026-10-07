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
                "alternatives": ["의견"],
                "severity": "change",
                "source": "test",
            }
        ],
        RULES,
    )
    result = analyzer.analyze("학생의 피드백을 반영한다.")
    assert result.total_score < 100
    assert any("피드백" in issue.message for issue in result.issues)


def test_flags_direct_latin_text():
    analyzer = PublicLanguageAnalyzer([], RULES)
    result = analyzer.analyze("AI 기반 교육을 운영한다.")
    assert result.scores["한글 사용"] < 10


def test_flags_long_sentence():
    analyzer = PublicLanguageAnalyzer([], RULES)
    text = "이 사업은 " + ("학생의 학습 활동을 지원하고 " * 10) + "운영한다."
    result = analyzer.analyze(text)
    assert result.scores["알기 쉬운 문장"] < 35
