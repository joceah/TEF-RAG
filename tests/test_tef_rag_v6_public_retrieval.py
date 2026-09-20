from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.evaluate_tef_rag_v6_public_retrieval import (
    DEFAULT_EVIDENCE,
    DEFAULT_EVALUATOR,
    DEFAULT_PREDICTIONS,
    DEFAULT_QUERIES,
    METHODS,
    _load_public_inputs,
    evaluate_all,
    load_prediction_rows,
    load_test_evaluator,
    validate_prediction_rows,
)


ROOT = Path(__file__).parents[1]


EXPECTED_METRICS = {
    "bm25": {
        "recall_at_5": 0.3791319444444444,
        "hit_at_5": 0.8645833333333334,
        "ndcg_at_5": 0.3914646196013589,
        "complete_at_5": 0.05625,
        "flow_complete_at_5": 0.05625,
        "edge_recall": None,
        "uncertainty_accuracy": 0.8875,
    },
    "bge_reranker": {
        "recall_at_5": 0.29159722222222223,
        "hit_at_5": 0.75625,
        "ndcg_at_5": 0.30697538565037147,
        "complete_at_5": 0.041666666666666664,
        "flow_complete_at_5": 0.041666666666666664,
        "edge_recall": None,
        "uncertainty_accuracy": 0.8875,
    },
    "temporal_bm25": {
        "recall_at_5": 0.4590625,
        "hit_at_5": 0.9125,
        "ndcg_at_5": 0.49550049524081685,
        "complete_at_5": 0.07916666666666666,
        "flow_complete_at_5": 0.07916666666666666,
        "edge_recall": None,
        "uncertainty_accuracy": 0.8875,
    },
    "ta_rag": {
        "recall_at_5": 0.27694444444444444,
        "hit_at_5": 0.70625,
        "ndcg_at_5": 0.29068467204336146,
        "complete_at_5": 0.0375,
        "flow_complete_at_5": 0.0375,
        "edge_recall": None,
        "uncertainty_accuracy": 0.8875,
    },
    "tef_rag_stage3d": {
        "recall_at_5": 0.7228125,
        "hit_at_5": 0.9875,
        "ndcg_at_5": 0.6231480206091232,
        "complete_at_5": 0.31875,
        "flow_complete_at_5": 0.3145833333333333,
        "edge_recall": 0.43645833333333334,
        "uncertainty_accuracy": 0.9666666666666667,
    },
}


EXPECTED_FINGERPRINTS = {
    "bm25": "107f1c3a8cd6f2449a4f3083815920885b45528186a309375179d69547701204",
    "bge_reranker": "2df10d38e6a5bd4e89f132feb829ad447e343a0af406d1409fdd1e6fcae87f41",
    "temporal_bm25": "59fdb492354bff63e6ccd7548bec6ee8c682ffb503ea3f6112025177eaff88fc",
    "ta_rag": "3fbf924109596f58678f0443f2bd048a3ae2af5e3a2473a40ab9d42043824e45",
    "tef_rag_stage3d": "c3c90317978985b465ee475b686198395f1970260823f9e6d73411e92322fa62",
}


def test_public_retrieval_metrics_and_fingerprints_match_historical_seal():
    result = evaluate_all()
    assert result["test_evaluator_sha256"] == "477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3"
    assert result["prediction_manifest_sha256"] == "995b9f739ad85f77f54977f357714438d9b425e76a5fea07b9022b767185ab7f"
    assert result["metrics"] == EXPECTED_METRICS
    assert result["score_fingerprints"] == EXPECTED_FINGERPRINTS


def test_public_retrieval_evaluator_has_exact_test_coverage():
    gold, expected_ids, digest = load_test_evaluator(DEFAULT_EVALUATOR, DEFAULT_QUERIES)
    assert digest == "477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3"
    assert len(gold) == len(expected_ids) == 480
    assert list(gold) == expected_ids


def test_public_retrieval_rejects_duplicate_evidence_ids():
    rows, _ = load_prediction_rows(DEFAULT_PREDICTIONS / "bm25.json")
    query_by_id, evidence_by_id = _load_public_inputs(DEFAULT_QUERIES, DEFAULT_EVIDENCE)
    expected_ids = list(query_by_id)
    rows[0]["selected_evidence_ids"] = [rows[0]["selected_evidence_ids"][0]] * 2
    with pytest.raises(ValueError, match="duplicate evidence"):
        validate_prediction_rows("bm25", rows, expected_ids, query_by_id, evidence_by_id)


def test_public_retrieval_rejects_unknown_evidence_id():
    rows, _ = load_prediction_rows(DEFAULT_PREDICTIONS / "bm25.json")
    query_by_id, evidence_by_id = _load_public_inputs(DEFAULT_QUERIES, DEFAULT_EVIDENCE)
    rows[0]["selected_evidence_ids"] = ["UNKNOWN-EVIDENCE"]
    with pytest.raises(ValueError, match="unknown evidence"):
        validate_prediction_rows("bm25", rows, list(query_by_id), query_by_id, evidence_by_id)


def test_public_retrieval_rejects_non_visible_evidence():
    rows, _ = load_prediction_rows(DEFAULT_PREDICTIONS / "bm25.json")
    query_by_id, evidence_by_id = _load_public_inputs(DEFAULT_QUERIES, DEFAULT_EVIDENCE)
    query = query_by_id[rows[0]["query_id"]]
    foreign = next(eid for eid, row in evidence_by_id.items() if row.get("asset_id") != query["asset_id"])
    rows[0]["selected_evidence_ids"] = [foreign]
    with pytest.raises(ValueError, match="not visible"):
        validate_prediction_rows("bm25", rows, list(query_by_id), query_by_id, evidence_by_id)


def test_public_retrieval_rejects_more_than_top_five():
    rows, _ = load_prediction_rows(DEFAULT_PREDICTIONS / "bm25.json")
    query_by_id, evidence_by_id = _load_public_inputs(DEFAULT_QUERIES, DEFAULT_EVIDENCE)
    rows[0]["selected_evidence_ids"] = list(evidence_by_id)[:6]
    with pytest.raises(ValueError, match="exceeds 5"):
        validate_prediction_rows("bm25", rows, list(query_by_id), query_by_id, evidence_by_id)


def test_public_retrieval_rejects_query_order_mismatch():
    rows, _ = load_prediction_rows(DEFAULT_PREDICTIONS / "bm25.json")
    query_by_id, evidence_by_id = _load_public_inputs(DEFAULT_QUERIES, DEFAULT_EVIDENCE)
    rows[0], rows[1] = rows[1], rows[0]
    with pytest.raises(ValueError, match="coverage/order"):
        validate_prediction_rows("bm25", rows, list(query_by_id), query_by_id, evidence_by_id)
