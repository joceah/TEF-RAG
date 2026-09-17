import inspect

import pytest

from baseline_adapters.mrag_v6 import MRAGV6Adapter, visible_snapshot
from baseline_adapters.ta_rag_v6 import TARAGV6Adapter, to_ta_corpus


QUERY = {"query_text": "What changed before 2025?", "query_time": "2025-01-10T00:00:00Z", "asset_id": "A"}
EVIDENCE = [
    {"id": "E2", "asset_id": "A", "text": "visible two", "event_time": "2025-01-02T00:00:00Z", "available_at": "2025-01-03T00:00:00Z"},
    {"id": "E1", "asset_id": "A", "text": "visible one", "event_time": "2025-01-01T00:00:00Z", "available_at": "2025-01-02T00:00:00Z"},
    {"id": "F1", "asset_id": "A", "text": "future event", "event_time": "2025-02-01T00:00:00Z", "available_at": "2025-01-03T00:00:00Z"},
    {"id": "F2", "asset_id": "A", "text": "future arrival", "event_time": "2025-01-01T00:00:00Z", "available_at": "2025-02-03T00:00:00Z"},
]


def test_future_and_gold_cannot_enter_baseline_input():
    assert [item["id"] for item in visible_snapshot(QUERY, EVIDENCE)] == ["E1", "E2"]
    with pytest.raises(ValueError): visible_snapshot({**QUERY, "required_groups": []}, EVIDENCE)
    with pytest.raises(ValueError): visible_snapshot(QUERY, [{**EVIDENCE[0], "chain_id": "hidden"}])


def test_mrag_provenance_is_deterministic_deduplicated_and_bounded():
    seen = {}
    def backend(**kwargs):
        seen.update(kwargs); return [{"provenance_id": "E2"}, {"provenance_id": "E2"},
                                     {"provenance_id": "F1"}, {"provenance_id": "E1"}]
    result = MRAGV6Adapter(backend).retrieve(QUERY, EVIDENCE, top_k=5)
    assert result == ["E2", "E1"] and [item["id"] for item in seen["contexts"]] == ["E1", "E2"]


def test_ta_point_interval_and_provenance_smoke():
    corpus = to_ta_corpus(QUERY, EVIDENCE)
    assert [item["corpus_uid"] for item in corpus] == ["E1", "E2"]
    assert corpus[0]["chunk_time_info"][0]["event_time_interval"]["end"] == "2025-01-01T00:00:01Z"
    result = TARAGV6Adapter(lambda **kwargs: [{"corpus_uid": "E1"}, {"corpus_uid": "E1"},
                                              {"corpus_uid": "E2"}]).retrieve(QUERY, EVIDENCE, 1)
    assert result == ["E1"]


def test_inference_has_no_gold_and_test_split_is_not_referenced():
    assert "gold" not in inspect.signature(MRAGV6Adapter.retrieve).parameters
    assert "gold" not in inspect.signature(TARAGV6Adapter.retrieve).parameters
