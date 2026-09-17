import inspect
import subprocess
import sys
from pathlib import Path

from scripts.run_tef_rag_v6_stage3a import group_split
from tef_rag_v6.pair_proposal import (
    FORBIDDEN_FEATURE_FRAGMENTS, LinearPairProposer, chronological_pairs, pair_features,
)


def _document(evidence_id, day, event_type="observation", supersedes=None):
    return {"evidence_id": evidence_id, "text": f"pump {evidence_id}",
            "event_time": f"2025-01-{day:02d}T00:00:00Z",
            "available_at": f"2025-01-{day:02d}T01:00:00Z", "event_type": event_type,
            "source_type": "procedure" if event_type == "procedure_applicability" else "log",
            "chain_id": "must-not-be-used", "supersedes": supersedes}


def _inputs():
    docs = [_document("A", 1, "procedure_applicability"), _document("B", 2, "repair"),
            _document("C", 3, "correction", "B"), _document("D", 4, "verification")]
    candidates = [{"document": d} for d in docs]
    scores = {d["evidence_id"]: {"total": 0.5, "relevance": 0.4, "recency": 0.3,
                                 "role_compatibility": 0.2} for d in docs}
    return {"query_text": "pump repair", "query_id": "leak-pattern"}, candidates, scores


def test_group_split_is_deterministic_and_disjoint():
    queries = [{"chain_id": f"C{i}", "query_id": f"q{i}-{j}"} for i in range(10) for j in range(2)]
    train, tune = group_split(queries, 20260916)
    assert train.isdisjoint(tune)
    assert train | tune == {f"C{i}" for i in range(10)}
    assert (train, tune) == group_split(queries, 20260916)


def test_feature_schema_excludes_gold_and_construction_identifiers():
    query, candidates, scores = _inputs()
    source, target = chronological_pairs(candidates)[0]
    features = pair_features(query, source, target, scores, {"action", "verification"})
    assert not any(fragment in key for key in features for fragment in FORBIDDEN_FEATURE_FRAGMENTS)
    assert not any("chain" in key or "query_id" in key for key in features)


def test_learned_ranking_is_deterministic_chronological_unique_and_bounded():
    query, candidates, scores = _inputs()
    model = LinearPairProposer(["target_verification"], [2.0], 0.0, {})
    first = model.rank(query, candidates, scores, {"action"}, 3)
    second = model.rank(query, candidates, scores, {"action"}, 3)
    ids = [(p["source"]["evidence_id"], p["target"]["evidence_id"]) for p in first]
    assert ids == [(p["source"]["evidence_id"], p["target"]["evidence_id"]) for p in second]
    assert len(ids) == len(set(ids)) == 3
    assert all(p["source"]["event_time"] < p["target"]["event_time"] for p in first)


def test_inference_needs_no_gold_and_hybrid_preserves_strong_pairs_within_budget():
    query, candidates, scores = _inputs()
    model = LinearPairProposer([], [], 0.0, {})
    result = model.rank(query, candidates, scores, set(), 3, mode="hybrid")
    ids = {(p["source"]["evidence_id"], p["target"]["evidence_id"]) for p in result}
    assert len(result) == 3
    assert ("A", "B") in ids  # hard procedure relationship


def test_runner_has_no_test_split_and_retrieve_is_gold_free():
    from tef_rag_v6 import TEFRAGV6
    assert "gold" not in inspect.signature(TEFRAGV6.retrieve).parameters
    root = Path(__file__).resolve().parents[1]
    process = subprocess.run([sys.executable, str(root / "scripts/run_tef_rag_v6_stage3a.py"),
                              "--split", "test"], cwd=root, capture_output=True, text=True)
    assert process.returncode != 0 and "invalid choice" in process.stderr


def test_single_pair_verbose_response_accepts_direct_judgment(tmp_path):
    from tef_rag_v6.llm_relation import LLMRelationClient, LLMRelationConfig, NO_EDGE, RELATION_CODES
    taxonomy = {value: {} for value in RELATION_CODES.values() if value != NO_EDGE}
    config = LLMRelationConfig(cache_dir=str(tmp_path), max_retries=0)
    response = {"choices": [{"message": {"content":
        '{"has_edge":true,"relation_type":"supports","confidence":0.9,"reason_code":"direct"}'}}]}
    client = LLMRelationClient(config, taxonomy, transport=lambda payload, timeout: response)
    query, candidates, _ = _inputs()
    query.update(query_time="2025-01-05T00:00:00Z")
    judged, _ = client._request_batch(query, [{"source": candidates[0]["document"],
                                                "target": candidates[1]["document"]}])
    assert judged[("A", "B")]["has_edge"] is True


def test_single_pair_verbose_response_accepts_compact_case(tmp_path):
    from tef_rag_v6.llm_relation import LLMRelationClient, LLMRelationConfig, NO_EDGE, RELATION_CODES
    taxonomy = {value: {} for value in RELATION_CODES.values() if value != NO_EDGE}
    response = {"choices": [{"message": {"content": '{"cases":[["case",[["G",85,2]]]]}'}}]}
    client = LLMRelationClient(LLMRelationConfig(cache_dir=str(tmp_path), max_retries=0), taxonomy,
                               transport=lambda payload, timeout: response)
    query, candidates, _ = _inputs()
    query.update(query_time="2025-01-05T00:00:00Z")
    judged, _ = client._request_batch(query, [{"source": candidates[0]["document"],
                                                "target": candidates[1]["document"]}])
    assert judged[("A", "B")]["relation_type"] == "governs"
