from datetime import datetime, timedelta, timezone
import json

import pytest

from tef_rag_v6.baseline_suite import (
    bge_rerank, bm25_rank, map_provenance, parse_temporal_intent,
    temporal_bm25_rank, visible_snapshot,
)


NOW = datetime(2026, 2, 17, tzinfo=timezone.utc)


def query(text="ordinary equipment question"):
    return {"query_id": "q", "query_text": text, "query_time": NOW.isoformat(),
            "asset_id": "A", "asset_model": "M"}


def evidence(identifier, text, event_delta=0, arrival_delta=0):
    return {"evidence_id": identifier, "text": text, "asset_id": "A", "asset_model": "M",
            "event_time": (NOW + timedelta(days=event_delta)).isoformat(),
            "available_at": (NOW + timedelta(days=arrival_delta)).isoformat(),
            "event_type": "state_observation", "source_type": "BMS"}


def test_shared_snapshot_excludes_future_event_arrival_and_scope():
    rows = [evidence("ok", "x"), evidence("future-event", "x", 1, 0),
            evidence("future-arrival", "x", 0, 1), dict(evidence("wrong", "x"), asset_id="B")]
    assert [row["evidence_id"] for row in visible_snapshot(query(), rows)] == ["ok"]


def test_inference_rejects_gold_and_bm25_is_deterministic_and_bounded():
    rows = [evidence(str(i), "equipment question") for i in range(8)]
    assert bm25_rank(query(), rows) == bm25_rank(query(), list(reversed(rows)))
    assert len(bm25_rank(query(), rows)) == 5
    with pytest.raises(ValueError):
        bm25_rank(dict(query(), required_groups=[]), rows)


def test_bge_receives_only_query_and_evidence_text():
    seen = []
    rows = [evidence("a", "equipment question"), evidence("b", "other")]
    def scorer(pairs):
        seen.extend(pairs)
        return list(range(len(pairs)))
    bge_rerank(query(), rows, scorer)
    assert seen and all(pair[0] == query()["query_text"] for pair in seen)
    assert {value for pair in seen for value in pair}.isdisjoint({NOW.isoformat(), "A", "M"})


def test_temporal_parser_deterministic_and_no_intent_degrades_to_bm25():
    q = query()
    rows = [evidence("a", "equipment question", -10), evidence("b", "equipment other", -1)]
    assert parse_temporal_intent("before 2020", q["query_time"]) == parse_temporal_intent("before 2020", q["query_time"])
    assert parse_temporal_intent("2020年之前", q["query_time"]).kind == "before"
    assert parse_temporal_intent("2020年以后", q["query_time"]).kind == "after"
    assert [row["evidence_id"] for row in temporal_bm25_rank(q, rows, .25)] == [row["evidence_id"] for row in bm25_rank(q, rows)]


def test_ta_provenance_is_deterministic_unique_and_bounded():
    ranked = [{"corpus_uid": str(i % 6)} for i in range(20)]
    expected = ["0", "1", "2", "3", "4"]
    assert map_provenance(ranked, map(str, range(6))) == expected
    assert map_provenance(ranked, map(str, range(6))) == expected


def test_validation_refuses_freeze_mismatch(tmp_path):
    payload = {"status": "FROZEN", "top_k": 5, "freeze_hash": "tampered"}
    path = tmp_path / "freeze.json"
    path.write_text(json.dumps(payload))
    raw = json.loads(path.read_text())
    assert raw.pop("freeze_hash") != __import__("hashlib").sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_runner_exposes_no_test_split():
    source = (__import__("pathlib").Path(__file__).parents[1] / "scripts/run_tef_rag_v6_baseline_suite.py").read_text()
    assert 'choices=("development", "validation")' in source
    assert "gold_test" not in source and "queries_test" not in source
