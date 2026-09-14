import unittest

from tef_rag_v4 import NeutralScopeEvidenceFlowRetrieverV4


class NeutralScopeEvidenceFlowV4Tests(unittest.TestCase):
    def test_visible_procedure_is_not_hidden_when_query_lacks_keyword(self):
        records = [
            {
                "id": "procedure",
                "asset_id": "A",
                "event_time": "2026-01-01T00:00:00Z",
                "available_at": "2026-01-01T00:00:00Z",
                "kind": "procedure",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_to": None,
                "text": "new threshold",
                "work_order_ids": [],
            },
            {
                "id": "event",
                "asset_id": "A",
                "event_time": "2026-01-02T00:00:00Z",
                "available_at": "2026-01-02T00:00:00Z",
                "kind": "maintenance_record",
                "text": "measured state",
                "work_order_ids": ["WO-1"],
            },
        ]
        engine = NeutralScopeEvidenceFlowRetrieverV4(
            records,
            [{"asset_id": "A", "model_scope": "M"}],
            [],
            top_k=2,
        )
        query = {"asset_id": "A", "query_time": "2026-01-03T00:00:00Z", "text": "截至当前确认了什么？"}
        result = engine.retrieve(query, {"procedure": 1.0, "event": 0.5})
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["evidence_ids"], ["procedure", "event"])
        self.assertEqual(result["candidate_policy"], "same_asset_and_event_available_by_query_time")


if __name__ == "__main__":
    unittest.main()
