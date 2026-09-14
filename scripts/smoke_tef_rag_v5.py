"""Gold-free, deterministic mechanism smoke test for TEF-RAG v5."""

import json

from tef_rag_v5 import QueryConditionedSetEvidenceRetrieverV5


def main():
    records = [
        {
            "id": "observation",
            "asset_id": "A",
            "event_time": "2026-03-01T00:00:00Z",
            "available_at": "2026-03-01T00:00:00Z",
            "kind": "maintenance_record",
            "text": "controller reported an intermittent alarm",
            "work_order_ids": [],
        },
        {
            "id": "action",
            "asset_id": "A",
            "event_time": "2026-03-02T00:00:00Z",
            "available_at": "2026-03-02T00:00:00Z",
            "kind": "maintenance_record",
            "text": "technician reseated the signal connector",
            "work_order_ids": [],
        },
        {
            "id": "verification",
            "asset_id": "A",
            "event_time": "2026-03-03T00:00:00Z",
            "available_at": "2026-03-03T00:00:00Z",
            "kind": "maintenance_record",
            "text": "retest confirmed stable operation",
            "work_order_ids": [],
        },
        {
            "id": "duplicate_observation",
            "asset_id": "A",
            "event_time": "2026-03-04T00:00:00Z",
            "available_at": "2026-03-04T00:00:00Z",
            "kind": "maintenance_record",
            "text": "controller reported an intermittent alarm",
            "work_order_ids": [],
        },
    ]
    roles = {
        "observation": {"role": "observation"},
        "action": {"role": "action"},
        "verification": {"role": "verification"},
        "duplicate_observation": {"role": "observation"},
    }
    relations = [
        {"prior_id": "observation", "update_id": "action", "update_relation": "follows", "confidence": 0.9},
        {"prior_id": "action", "update_id": "verification", "update_relation": "verifies", "confidence": 1.0},
    ]
    retriever = QueryConditionedSetEvidenceRetrieverV5(
        records,
        [{"asset_id": "A", "model_scope": "M"}],
        relations,
        roles=roles,
        top_k=3,
    )
    result = retriever.retrieve(
        {"asset_id": "A", "query_time": "2026-03-10T00:00:00Z", "text": "query-only smoke input"},
        {"observation": 0.8, "action": 0.75, "verification": 0.85, "duplicate_observation": 0.8},
        query_profile={
            "selection_mode": "set",
            "role_demands": {"observation": 0.6, "action": 1.0, "verification": 1.0},
            "relation_demands": {"follows": 0.4, "verifies": 1.0},
        },
    )

    assert len(result["evidence_ids"]) == len(result["trace"]) == 3
    assert "verification" in result["evidence_ids"]
    assert result["trace"][-1]["set_after"] == result["evidence_ids"]
    assert all(
        edge["prior_id"] in step["set_after"] and edge["update_id"] in step["set_after"]
        for step in result["trace"]
        for edge in step["activated_relations"]
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
