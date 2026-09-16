import inspect
import subprocess
import sys
from pathlib import Path

from scripts.run_tef_rag_v6_stage2b1 import flow_oracle, group_oracle, relation_graph_feasibility
from tef_rag_v6 import TEFRAGV6, V6Config
from tef_rag_v6.evaluation import flow_complete


def doc(identifier, day, event_type="state_observation", **extra):
    return {"evidence_id": identifier, "asset_id": "A1", "asset_model": "M2",
            "event_time": f"2026-05-{day:02d}T00:00:00+00:00",
            "available_at": f"2026-05-{day:02d}T00:00:00+00:00",
            "event_type": event_type, "source_type": "BMS", "chain_id": "C1",
            "episode_id": "P1", "text": identifier, **extra}


QUERY = {"query_text": "原因处置验证", "asset_id": "A1", "asset_model": "M2",
         "query_time": "2026-06-01T00:00:00+00:00", "chain_id": "IGNORED"}


def retriever():
    return TEFRAGV6([doc(f"E{i}", i, ("diagnosis", "work_order", "verification")[i % 3])
                     for i in range(1, 9)],
                    V6Config(candidate_k=10, search_pool_k=8, expansion_top_k=8,
                             beam_width=4, final_k=5, connectivity_weight=.1))


def test_beam_pool_parity_raw_and_fallback_modes():
    r = retriever()
    greedy = r.retrieve(QUERY, search_mode="greedy")
    raw = r.retrieve(QUERY, search_mode="raw_beam")
    fallback = r.retrieve(QUERY, search_mode="beam_with_fallback")
    assert raw["search_diagnostics"]["search_pool_ids"] == greedy["search_diagnostics"]["search_pool_ids"]
    assert fallback["search_diagnostics"]["search_pool_ids"] == greedy["search_diagnostics"]["search_pool_ids"]
    assert raw["search_diagnostics"]["fallback_used"] is False
    assert len(raw["selected_evidence_ids"]) <= 5 == len(set(raw["selected_evidence_ids"]))
    assert raw["selected_evidence_ids"] == r.retrieve(QUERY, search_mode="raw_beam")["selected_evidence_ids"]


def test_hard_invalid_never_enters_raw_beam():
    r = TEFRAGV6([doc("E", 1), doc("F", 2, available_at="2026-06-02T00:00:00+00:00")],
                 V6Config(candidate_k=10, search_pool_k=2, expansion_top_k=2))
    assert r.retrieve(QUERY, search_mode="raw_beam")["selected_evidence_ids"] == ["E"]


def test_official_flow_oracle_does_not_require_predicted_relation():
    gold = {"required_groups": [
        {"group_id": "A", "acceptable_evidence_ids": ["E1"]},
        {"group_id": "B", "acceptable_evidence_ids": ["E2"]}],
        "required_flow_edges": [{"from_group": "A", "to_group": "B",
                                 "relation_type": "verifies",
                                 "allowed_endpoint_pairs": [["E1", "E2"]]}]}
    pool = {"E1", "E2"}
    assert group_oracle(pool, gold)
    assert flow_oracle(pool, gold)
    assert flow_complete(["E1", "E2"], gold)
    assert not relation_graph_feasibility(pool, [], gold)


def test_oracle_is_evaluation_only_and_test_split_unavailable():
    for method in (TEFRAGV6.retrieve, TEFRAGV6._select_flow, TEFRAGV6._select_flow_beam):
        assert "gold" not in inspect.signature(method).parameters
    root = Path(__file__).resolve().parents[1]
    process = subprocess.run([sys.executable, str(root / "scripts/run_tef_rag_v6_stage2b1.py"),
                              "--split", "test"], cwd=root, capture_output=True, text=True)
    assert process.returncode != 0 and "invalid choice" in process.stderr
