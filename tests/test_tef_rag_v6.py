from tef_rag_v6 import TEFRAGV6, V6Config
from tef_rag_v6.evaluation import flow_complete


def document(identifier, event, available, **extra):
    return {
        "evidence_id": identifier,
        "asset_id": "A1",
        "asset_model": "M2",
        "event_time": event,
        "available_at": available,
        "event_type": "state_observation",
        "source_type": "BMS",
        "chain_id": "C1",
        "episode_id": "P1",
        "text": identifier + " 温升检查",
        **extra,
    }


QUERY = {
    "query_id": "Q1",
    "query_text": "A1 温升应依据什么处置并验证？",
    "asset_id": "A1",
    "asset_model": "M2",
    "query_time": "2026-06-01T00:00:00+00:00",
    "chain_id": "MUST_NOT_BE_USED",
}


def test_temporal_and_procedure_constraints_are_hard():
    base = document("E1", "2026-05-01T00:00:00+00:00", "2026-05-01T00:00:00+00:00")
    future = document("E2", "2026-05-02T00:00:00+00:00", "2026-06-02T00:00:00+00:00")
    old_procedure = document(
        "E3", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
        event_type="procedure_applicability", source_type="procedure", valid_from="2026-01-01T00:00:00+00:00",
        valid_to="2026-05-01T00:00:00+00:00", model_scope=["M2"],
    )
    wrong_model = document(
        "E4", "2026-05-01T00:00:00+00:00", "2026-05-01T00:00:00+00:00",
        event_type="procedure_applicability", source_type="procedure", valid_from="2026-05-01T00:00:00+00:00",
        valid_to=None, model_scope=["M9"],
    )
    retriever = TEFRAGV6([base, future, old_procedure, wrong_model], V6Config(candidate_k=10))
    assert retriever.temporal_eligibility(base, QUERY) == (True, "eligible")
    assert retriever.temporal_eligibility(future, QUERY)[1] == "not_yet_available"
    assert retriever.temporal_eligibility(old_procedure, QUERY)[1] == "procedure_expired"
    assert retriever.temporal_eligibility(wrong_model, QUERY)[1] == "procedure_model_scope_mismatch"


def test_supersession_edge_and_uncertainty_are_serialized():
    old = document("E1", "2026-05-01T00:00:00+00:00", "2026-05-01T00:00:00+00:00", event_type="diagnosis")
    new = document(
        "E2", "2026-05-02T00:00:00+00:00", "2026-05-02T00:00:00+00:00",
        event_type="diagnosis", supersedes="E1",
    )
    uncertainty = document(
        "E3", "2026-05-03T00:00:00+00:00", "2026-05-03T00:00:00+00:00",
        event_type="uncertainty", text="两条原因分支仍需保留，不确定",
    )
    retriever = TEFRAGV6([old, new, uncertainty], V6Config(candidate_k=10, final_k=3, search_pool_k=3))
    result = retriever.retrieve({**QUERY, "query_text": "两条原因分支仍不确定"})
    assert any(edge["relation_type"] == "supersession" for edge in result["relations"])
    assert result["uncertainty"]["status"] == "persistent"


def test_flow_complete_requires_one_globally_consistent_assignment():
    gold = {
        "required_groups": [
            {"group_id": "G1", "acceptable_evidence_ids": ["A", "B"]},
            {"group_id": "G2", "acceptable_evidence_ids": ["C"]},
            {"group_id": "G3", "acceptable_evidence_ids": ["D"]},
        ],
        "required_flow_edges": [
            {"from_group": "G1", "to_group": "G2", "allowed_endpoint_pairs": [["A", "C"]]},
            {"from_group": "G1", "to_group": "G3", "allowed_endpoint_pairs": [["B", "D"]]},
        ],
    }
    assert not flow_complete(["A", "B", "C", "D"], gold)


def test_query_chain_id_does_not_scope_candidates():
    first = document("E1", "2026-05-01T00:00:00+00:00", "2026-05-01T00:00:00+00:00")
    second = {**document("E2", "2026-05-02T00:00:00+00:00", "2026-05-02T00:00:00+00:00"), "chain_id": "C2"}
    retriever = TEFRAGV6([first, second], V6Config(candidate_k=10))
    assert {item["document"]["evidence_id"] for item in retriever.candidate_retrieval(QUERY)} == {"E1", "E2"}
