from app.data_store import DataStore


def test_official_snapshot_has_expected_record_count():
    store = DataStore()
    info = store.dictionary_info()
    assert info["official_count"] == 3581


def test_official_snapshot_is_loaded_into_analyzer_terms():
    store = DataStore()
    official = [x for x in store.load_terms() if x.get("source_type") == "OFFICIAL"]
    assert len(official) == 3581

    by_term = {x["term"]: x for x in official}
    assert "AI" in by_term
    assert "인공 지능" in by_term["AI"]["alt_text"]
    assert "피드백" in by_term
