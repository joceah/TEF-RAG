import subprocess
import sys
from pathlib import Path

from tef_rag_v6 import TEFRAGV6, V6Config


def doc(identifier, day, event_type="state_observation", text=None, **extra):
    return {"evidence_id": identifier, "asset_id": "A1", "asset_model": "M2",
            "event_time": f"2026-05-{day:02d}T00:00:00+00:00",
            "available_at": f"2026-05-{day:02d}T00:00:00+00:00",
            "event_type": event_type, "source_type": "BMS", "chain_id": "C1",
            "episode_id": "P1", "text": text or identifier, **extra}


QUERY = {"query_text": "温升原因处置验证", "asset_id": "A1", "asset_model": "M2",
         "query_time": "2026-06-01T00:00:00+00:00", "chain_id": "MUST_NOT_BE_USED"}


def test_beam_is_deterministic_unique_and_bounded():
    r = TEFRAGV6([doc(f"E{i}", i, ("diagnosis", "work_order", "verification")[i % 3])
                  for i in range(1, 8)], V6Config(candidate_k=10, search_pool_k=7, final_k=5,
                                                  beam_width=4, expansion_top_k=7))
    first = r.retrieve(QUERY, search_mode="beam")
    second = r.retrieve(QUERY, search_mode="beam")
    assert first["selected_evidence_ids"] == second["selected_evidence_ids"]
    assert len(first["selected_evidence_ids"]) <= 5
    assert len(set(first["selected_evidence_ids"])) == len(first["selected_evidence_ids"])


def test_beam_width_one_sanity_and_hard_constraints():
    future = doc("F", 2, available_at="2026-06-02T00:00:00+00:00")
    expired = doc("P", 1, "procedure_applicability", source_type="procedure",
                  valid_to="2026-05-02T00:00:00+00:00", model_scope=["M2"])
    r = TEFRAGV6([doc("E", 1), future, expired], V6Config(candidate_k=10, beam_width=1))
    result = r.retrieve(QUERY, search_mode="beam")
    assert set(result["selected_evidence_ids"]) == {"E"}


def test_search_api_has_no_gold_and_test_split_is_unavailable():
    assert "gold" not in TEFRAGV6._select_flow_beam.__code__.co_varnames
    root = Path(__file__).resolve().parents[1]
    process = subprocess.run([sys.executable, str(root / "scripts/run_tef_rag_v6_stage2b.py"),
                              "--split", "test"], cwd=root, capture_output=True, text=True)
    assert process.returncode != 0 and "invalid choice" in process.stderr
