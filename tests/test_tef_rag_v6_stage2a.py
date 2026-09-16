import json
from pathlib import Path
import subprocess
import sys

from tef_rag_v6 import (
    LLMRelationClient,
    LLMRelationConfig,
    QueryConditionedRelationScorer,
    TEFRAGV6,
    V6Config,
)


TAXONOMY = {name: name for name in (
    "contrasts", "governs", "prerequisite", "preserves_uncertainty", "qualifies",
    "resolves", "supersession", "supports", "updates", "verifies",
)}
QUERY = {
    "query_id": "Q1", "query_text": "当前处置及验证依据是什么？", "query_time": "2026-06-01T00:00:00+00:00",
    "asset_id": "A1", "asset_model": "M2", "asset_context": "A1设备", "chain_id": "DO_NOT_USE",
}


def doc(identifier, day, **extra):
    return {
        "evidence_id": identifier, "asset_id": "A1", "asset_model": "M2",
        "event_time": f"2026-05-{day:02d}T00:00:00+00:00",
        "available_at": f"2026-05-{day:02d}T00:00:00+00:00",
        "event_type": "state_observation", "source_type": "BMS", "chain_id": "C1",
        "episode_id": "P1", "text": f"{identifier} 当前温升处置", **extra,
    }


def response_for(payload, relation="supports", malformed_wrapper=False):
    user = json.loads(payload["messages"][1]["content"])
    rows = [{
        "source_id": pair["source_id"], "target_id": pair["target_id"],
        "has_edge": relation != "NO_EDGE", "relation_type": relation,
        "confidence": 0.9, "reason_code": "test_relation",
    } for pair in user["pairs"]]
    content = json.dumps({"judgments": rows})
    if malformed_wrapper:
        content = "result follows\n```json\n" + content + "\n```"
    return {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def make_client(tmp_path, transport, **overrides):
    values = {
        "cache_dir": str(tmp_path), "max_retries": 2,
        "retry_backoff_seconds": 0.0, "busy_retry_backoff_seconds": 0.0,
        "request_interval_seconds": 0.0, **overrides,
    }
    return LLMRelationClient(LLMRelationConfig(**values), TAXONOMY, transport=transport, sleep=lambda _: None)


def one_pair():
    return [{"source": doc("E1", 1), "target": doc("E2", 2)}]


def test_heuristic_mode_is_stage1_compatible():
    documents = [doc("E1", 1), doc("E2", 2, event_type="diagnosis"), doc("E3", 3, event_type="work_order")]
    frozen = TEFRAGV6(documents, V6Config(candidate_k=10, search_pool_k=3, final_k=3))
    stage2 = TEFRAGV6(documents, V6Config(candidate_k=10, search_pool_k=3, final_k=3), relation_scorer=object())
    left = frozen.retrieve(QUERY)
    right = stage2.retrieve(QUERY, relation_mode="heuristic")
    assert left["selected_evidence_ids"] == right["selected_evidence_ids"]
    assert left["relations"] == right["relations"]


def test_malformed_wrapper_recovery_and_cache_hit(tmp_path):
    calls = []

    def transport(payload, timeout):
        calls.append(timeout)
        return response_for(payload, malformed_wrapper=True)

    client = make_client(tmp_path, transport)
    first, first_diag = client.judge(QUERY, one_pair())
    second, second_diag = client.judge(QUERY, one_pair())
    assert first == second
    assert len(calls) == 1
    assert first_diag["llm_called_pair_count"] == 1
    assert second_diag["cache_hit_count"] == 1


def test_timeout_retries_then_succeeds(tmp_path):
    calls = 0

    def transport(payload, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary")
        return response_for(payload)

    client = make_client(tmp_path, transport)
    _, diagnostics = client.judge(QUERY, one_pair())
    assert calls == 2
    assert diagnostics["retry_count"] == 1


def test_invalid_relation_type_and_no_edge_are_rejected(tmp_path):
    invalid = make_client(tmp_path / "invalid", lambda payload, timeout: response_for(payload, relation="invented"))
    judgments, diagnostics = invalid.judge(QUERY, one_pair())
    assert not next(iter(judgments.values()))["has_edge"]
    assert diagnostics["invalid_type_count"] == 1
    no_edge = make_client(tmp_path / "none", lambda payload, timeout: response_for(payload, relation="NO_EDGE"))
    judgments, _ = no_edge.judge(QUERY, one_pair())
    assert next(iter(judgments.values()))["relation_type"] == "NO_EDGE"


def test_prefilter_is_deterministic(tmp_path):
    client = make_client(tmp_path, lambda payload, timeout: response_for(payload))
    scorer = QueryConditionedRelationScorer(client, 0.58)
    retriever = TEFRAGV6([doc("E1", 1), doc("E2", 2), doc("E3", 3)], V6Config(candidate_k=10))
    candidates = retriever.candidate_retrieval(QUERY)
    scores = retriever._node_scores(retriever._public_query(QUERY), candidates)
    first, raw_first = scorer.prefilter(candidates, scores, retriever._relation_kind, retriever._similarity)
    second, raw_second = scorer.prefilter(candidates, scores, retriever._relation_kind, retriever._similarity)
    ids = lambda rows: [(row["source"]["evidence_id"], row["target"]["evidence_id"]) for row in rows]
    assert ids(first) == ids(second)
    assert raw_first == raw_second == 3


def test_temporal_and_procedure_invalid_evidence_never_calls_llm(tmp_path):
    calls = 0

    def transport(payload, timeout):
        nonlocal calls
        calls += 1
        return response_for(payload)

    legal = doc("E1", 1)
    future = {**doc("E2", 2), "available_at": "2026-06-02T00:00:00+00:00"}
    invalid_proc = doc(
        "E3", 3, event_type="procedure_applicability", source_type="procedure",
        valid_from="2026-01-01T00:00:00+00:00", valid_to="2026-05-15T00:00:00+00:00", model_scope=["M2"],
    )
    client = make_client(tmp_path, transport)
    scorer = QueryConditionedRelationScorer(client, 0.58)
    retriever = TEFRAGV6([legal, future, invalid_proc], V6Config(candidate_k=10), relation_scorer=scorer)
    result = retriever.retrieve(QUERY, relation_mode="llm")
    assert calls == 0
    assert result["relation_graph"] == []
    assert {item["reason"] for item in result["rejections"]} == {"not_yet_available", "procedure_expired"}


def test_llm_edge_enters_frozen_flow_score(tmp_path):
    client = make_client(tmp_path, lambda payload, timeout: response_for(payload))
    scorer = QueryConditionedRelationScorer(client, 0.58)
    retriever = TEFRAGV6(
        [doc("E1", 1), doc("E2", 2, event_type="diagnosis"), doc("E3", 3, event_type="work_order")],
        V6Config(candidate_k=10, search_pool_k=3, final_k=3), relation_scorer=scorer,
    )
    result = retriever.retrieve(QUERY, relation_mode="llm")
    assert result["relation_graph"]
    assert result["score_components"]["edge_sum"] > 0
    assert all(edge["relation_type"] in TAXONOMY for edge in result["relation_graph"])


def test_multi_query_cache_warm_is_one_serial_request(tmp_path):
    calls = []

    def transport(payload, timeout):
        calls.append(payload)
        user = json.loads(payload["messages"][1]["content"])
        rows = []
        for case in user["cases"]:
            rows.append([case["case_id"], [["S", 90, 1] for _ in case["pairs"]]])
        return {"choices": [{"message": {"content": json.dumps({"cases": rows})}}]}

    client = make_client(tmp_path, transport, cases_per_request=8)
    cases = [
        {"case_id": "c1", "query": QUERY, "pairs": one_pair()},
        {"case_id": "c2", "query": {**QUERY, "query_text": "另一个问题"}, "pairs": one_pair()},
    ]
    diagnostics = client.warm_cases(cases)
    assert len(calls) == 1
    assert diagnostics["saved_pair_count"] == 2
    _, first = client.judge(QUERY, one_pair())
    _, second = client.judge({**QUERY, "query_text": "另一个问题"}, one_pair())
    assert first["cache_hit_count"] == second["cache_hit_count"] == 1
    assert len(calls) == 1


def test_multi_query_cache_warm_stops_after_failed_batch(tmp_path):
    calls = 0

    def transport(payload, timeout):
        nonlocal calls
        calls += 1
        return {"choices": [{"message": {"content": ""}}]}

    client = make_client(tmp_path, transport, cases_per_request=1, max_retries=0)
    diagnostics = client.warm_cases([
        {"case_id": "c1", "query": QUERY, "pairs": one_pair()},
        {"case_id": "c2", "query": {**QUERY, "query_text": "另一个问题"}, "pairs": one_pair()},
    ])
    assert calls == 1
    assert diagnostics["failed_batch_count"] == 1
    assert diagnostics["saved_pair_count"] == 0


def test_one_case_cache_warm_accepts_strict_verbose_fallback(tmp_path):
    def transport(payload, timeout):
        user = json.loads(payload["messages"][1]["content"])
        rows = [{
            "source_id": source_id, "target_id": target_id, "has_edge": True,
            "relation_type": "supports", "confidence": 0.9, "reason_code": "semantic_support",
        } for source_id, target_id in user["cases"][0]["pairs"]]
        return {"choices": [{"message": {"content": json.dumps({"judgments": rows})}}]}

    client = make_client(tmp_path, transport, cases_per_request=1)
    diagnostics = client.warm_cases([{"case_id": "c1", "query": QUERY, "pairs": one_pair()}])
    assert diagnostics["saved_pair_count"] == 1
    assert diagnostics["failed_batch_count"] == 0


def test_one_case_cache_warm_accepts_extra_cases_wrapper(tmp_path):
    def transport(payload, timeout):
        user = json.loads(payload["messages"][1]["content"])
        case = user["cases"][0]
        results = [["S", 90, 1] for _ in case["pairs"]]
        return {"choices": [{"message": {"content": json.dumps({"cases": [[[case["case_id"], results]]]})}}]}

    client = make_client(tmp_path, transport, cases_per_request=1)
    diagnostics = client.warm_cases([{"case_id": "c1", "query": QUERY, "pairs": one_pair()}])
    assert diagnostics["saved_pair_count"] == 1
    assert diagnostics["failed_batch_count"] == 0


def test_one_case_cache_warm_maps_matching_numeric_reason_code(tmp_path):
    def transport(payload, timeout):
        user = json.loads(payload["messages"][1]["content"])
        case = user["cases"][0]
        results = [[4, 85, 4] for _ in case["pairs"]]
        return {"choices": [{"message": {"content": json.dumps({"cases": [[case["case_id"], results]]})}}]}

    client = make_client(tmp_path, transport, cases_per_request=1)
    diagnostics = client.warm_cases([{"case_id": "c1", "query": QUERY, "pairs": one_pair()}])
    judgments, _ = client.judge(QUERY, one_pair())
    assert diagnostics["saved_pair_count"] == 1
    assert next(iter(judgments.values()))["relation_type"] == "verifies"


def test_one_case_cache_warm_trims_only_trailing_no_edge(tmp_path):
    def transport(payload, timeout):
        user = json.loads(payload["messages"][1]["content"])
        case = user["cases"][0]
        results = [["S", 90, 1] for _ in case["pairs"]] + [["N", 0, 0]]
        return {"choices": [{"message": {"content": json.dumps({"cases": [[[case["case_id"], results]]]})}}]}

    client = make_client(tmp_path, transport, cases_per_request=1)
    diagnostics = client.warm_cases([{"case_id": "c1", "query": QUERY, "pairs": one_pair()}])
    assert diagnostics["saved_pair_count"] == 1
    assert diagnostics["failed_batch_count"] == 0


def test_one_case_cache_warm_pads_missing_suffix_as_no_edge(tmp_path):
    pairs = one_pair() + [{"source": doc("E2", 2), "target": doc("E3", 3)}]

    def transport(payload, timeout):
        user = json.loads(payload["messages"][1]["content"])
        case = user["cases"][0]
        return {"choices": [{"message": {"content": json.dumps({
            "cases": [[[case["case_id"], [["S", 90, 1]]]]]
        })}}]}

    client = make_client(tmp_path, transport, cases_per_request=1)
    diagnostics = client.warm_cases([{"case_id": "c1", "query": QUERY, "pairs": pairs}])
    assert diagnostics["saved_pair_count"] == 2
    assert diagnostics["padded_missing_count"] == 1


def test_query_chain_id_not_forwarded_and_test_split_not_runnable(tmp_path):
    captured = []

    def transport(payload, timeout):
        captured.append(payload["messages"][1]["content"])
        return response_for(payload)

    client = make_client(tmp_path, transport)
    client.judge(QUERY, one_pair())
    request_query = json.loads(captured[0])["query"]
    assert "chain_id" not in request_query
    root = Path(__file__).resolve().parents[1]
    process = subprocess.run(
        [sys.executable, str(root / "scripts/run_tef_rag_v6_stage2a.py"), "--split", "test"],
        cwd=root, text=True, capture_output=True,
    )
    assert process.returncode != 0
    assert "invalid choice" in process.stderr
