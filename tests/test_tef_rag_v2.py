import unittest

from tef_rag_v2 import BitemporalEvidenceFlowRetrieverV2


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


def engine(records, relations):
    return BitemporalEvidenceFlowRetrieverV2(
        records,
        [{"asset_id": "A", "model_scope": "M"}],
        relations,
        top_k=2,
    )


def query():
    return {"asset_id": "A", "query_time": "2026-03-12T00:00:00Z", "text": "哪些证据排除了原判断？"}


class BitemporalEvidenceFlowV2Tests(unittest.TestCase):
    def test_late_arriving_older_evidence_can_refute_a_known_hypothesis(self):
        records = [record("hypothesis", 3, 3), record("late_report", 2, 8)]
        relations = [{"source_id": "hypothesis", "target_id": "late_report", "relation": "refutes", "confidence": 1.0}]
        result = engine(records, relations).retrieve(query(), {"hypothesis": 0.2, "late_report": 0.1})
        self.assertEqual(result["evidence_ids"], ["hypothesis", "late_report"])
        self.assertEqual(result["rejected_edges"], [])
        self.assertEqual(result["selector"], "bitemporal_evidence_flow_beam_v2")

    def test_process_edge_still_rejects_backward_event_time(self):
        records = [record("later_event", 8, 8), record("earlier_event", 2, 9)]
        relations = [{"source_id": "later_event", "target_id": "earlier_event", "relation": "follows", "confidence": 1.0}]
        result = engine(records, relations).retrieve(query(), {"later_event": 1.0, "earlier_event": 0.0})
        self.assertEqual(result["rejected_edges"][0]["reason"], "backward_event_time")
        self.assertEqual(result["rejected_edges"][0]["clock"], "event_time")

    def test_claim_edge_rejects_backward_knowledge_time(self):
        records = [record("known_late", 2, 9), record("known_early", 8, 8)]
        relations = [{"source_id": "known_late", "target_id": "known_early", "relation": "supports", "confidence": 1.0}]
        result = engine(records, relations).retrieve(query(), {"known_late": 1.0, "known_early": 0.0})
        self.assertEqual(result["rejected_edges"][0]["reason"], "backward_knowledge_time")
        self.assertEqual(result["rejected_edges"][0]["clock"], "available_at")


if __name__ == "__main__":
    unittest.main()
