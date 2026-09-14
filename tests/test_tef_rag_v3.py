import unittest

from tef_rag_v3 import ExplicitUpdateEvidenceFlowRetrieverV3


def record(identifier, event_day, available_day):
    return {
        "id": identifier,
        "asset_id": "A",
        "event_time": f"2026-03-{event_day:02d}T00:00:00Z",
        "available_at": f"2026-03-{available_day:02d}T00:00:00Z",
        "kind": "maintenance_record",
        "text": identifier,
        "work_order_ids": [],
    }


def query():
    return {"asset_id": "A", "query_time": "2026-03-12T00:00:00Z", "text": "哪些证据更新了原判断？"}


class ExplicitUpdateEvidenceFlowV3Tests(unittest.TestCase):
    def test_late_older_event_is_encoded_as_update_of_prior_claim(self):
        records = [record("hypothesis", 3, 3), record("late_report", 2, 8)]
        relations = [
            {
                "prior_id": "hypothesis",
                "update_id": "late_report",
                "update_relation": "refutes",
                "confidence": 1.0,
            }
        ]
        engine = ExplicitUpdateEvidenceFlowRetrieverV3(records, [{"asset_id": "A", "model_scope": "M"}], relations, top_k=2)
        result = engine.retrieve(query(), {"hypothesis": 0.2, "late_report": 0.1})
        self.assertEqual(result["evidence_ids"], ["hypothesis", "late_report"])
        self.assertEqual(result["rejected_edges"], [])
        edge = result["trace"][0]["relations"][0]
        self.assertEqual((edge["prior_id"], edge["update_id"], edge["update_relation"]), ("hypothesis", "late_report", "refutes"))
        self.assertEqual(edge["clock"], "available_at")
        self.assertEqual(result["selector"], "explicit_update_evidence_flow_beam_v3")

    def test_process_update_still_uses_event_time(self):
        records = [record("later", 8, 8), record("older", 2, 9)]
        relations = [{"prior_id": "later", "update_id": "older", "update_relation": "follows", "confidence": 1.0}]
        engine = ExplicitUpdateEvidenceFlowRetrieverV3(records, [{"asset_id": "A", "model_scope": "M"}], relations, top_k=2)
        result = engine.retrieve(query(), {"later": 1.0, "older": 0.0})
        self.assertEqual(result["rejected_edges"][0]["reason"], "backward_event_time")
        self.assertEqual(result["rejected_edges"][0]["clock"], "event_time")
        self.assertEqual(result["rejected_edges"][0]["prior_id"], "later")

    def test_legacy_schema_remains_readable(self):
        records = [record("old", 2, 2), record("new", 3, 3)]
        relations = [{"source_id": "old", "target_id": "new", "relation": "supports", "confidence": 1.0}]
        engine = ExplicitUpdateEvidenceFlowRetrieverV3(records, [{"asset_id": "A", "model_scope": "M"}], relations, top_k=2)
        result = engine.retrieve(query(), {"old": 0.2, "new": 0.1})
        self.assertEqual(result["evidence_ids"], ["old", "new"])
        self.assertEqual(result["relation_schema"], "prior_update_v3")


if __name__ == "__main__":
    unittest.main()
