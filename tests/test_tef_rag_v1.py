import unittest

from tef_rag_v1 import TemporalEvidenceFlowRetrieverV1


def doc(identifier, day, available_at=None):
    when = f"2026-03-{day:02d}T00:00:00Z"
    return {
        "id": identifier,
        "asset_id": "A",
        "event_time": when,
        "available_at": available_at or when,
        "kind": "maintenance_record",
        "text": identifier,
        "work_order_ids": [],
    }


def query(text="哪项操作真正解决了异常？"):
    return {
        "asset_id": "A",
        "query_time": "2026-03-10T00:00:00Z",
        "text": "资料截止2026-03-10T00:00:00Z；" + text,
    }


def engine(records, relations, top_k=2):
    return TemporalEvidenceFlowRetrieverV1(
        records,
        [{"asset_id": "A", "model_scope": "M"}],
        relations,
        top_k=top_k,
    )


class TemporalEvidenceFlowContractTests(unittest.TestCase):
    def test_verification_path_beats_high_similarity_singleton(self):
        records = [doc("fan_guess", 1), doc("connector_fix", 2), doc("normal_retest", 3), doc("keyword_distractor", 4)]
        relations = [{"source_id": "connector_fix", "target_id": "normal_retest", "relation": "verifies", "confidence": 1.0}]
        scores = {"fan_guess": 0.5, "connector_fix": 0.3, "normal_retest": 0.3, "keyword_distractor": 1.0}
        result = engine(records, relations).retrieve(query(), scores)
        self.assertEqual(result["evidence_ids"], ["connector_fix", "normal_retest"])
        self.assertEqual(result["selector"], "temporal_evidence_flow_beam_v1")

    def test_future_available_endpoint_never_enters_graph(self):
        records = [
            doc("visible_action", 2),
            doc("late_result", 3, available_at="2026-03-11T00:00:00Z"),
            doc("visible_other", 4),
        ]
        relations = [{"source_id": "visible_action", "target_id": "late_result", "relation": "verifies", "confidence": 1.0}]
        result = engine(records, relations).retrieve(query(), {"late_result": 100.0})
        self.assertNotIn("late_result", result["evidence_ids"])
        self.assertEqual(result["selector"], "scoped_hybrid_fallback")

    def test_backward_relation_is_rejected(self):
        records = [doc("earlier", 2), doc("later", 4)]
        relations = [{"source_id": "later", "target_id": "earlier", "relation": "supports", "confidence": 1.0}]
        result = engine(records, relations).retrieve(query(), {"later": 1.0, "earlier": 0.0})
        self.assertEqual(result["selector"], "scoped_hybrid_fallback")
        self.assertEqual(result["rejected_edges"][0]["reason"], "backward_time")

    def test_no_relation_uses_shared_scoped_hybrid(self):
        records = [doc("low", 1), doc("high", 2)]
        result = engine(records, []).retrieve(query("记录说明了什么？"), {"low": 0.0, "high": 1.0})
        self.assertEqual(result["evidence_ids"], ["high", "low"])
        self.assertEqual(result["selector"], "scoped_hybrid_fallback")

    def test_latest_query_stays_a_simple_control(self):
        records = [doc("old", 1), doc("new", 5)]
        result = engine(records, []).retrieve(query("最新业务记录是什么？"), {"old": 100.0})
        self.assertEqual(result["evidence_ids"], ["new", "old"])
        self.assertEqual(result["selector"], "shared_recency_control")


if __name__ == "__main__":
    unittest.main()
