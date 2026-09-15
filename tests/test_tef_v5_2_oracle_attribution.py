import hashlib
import inspect
import json
import unittest
from pathlib import Path

from scripts.analyze_tef_v5_2_oracle_projection import (
    CONFIGURATIONS,
    ROOT,
    oracle_profile,
    oracle_relations,
    oracle_roles,
    run,
)
from tef_rag_v5 import QueryConditionedSetEvidenceRetrieverV5


class OracleAttributionV52Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = json.loads(
            (ROOT / "experiments/analyses/tef_v5_2_oracle_projection_attribution_v1/results.json")
            .read_text(encoding="utf-8")
        )

    def test_ccc_reproduces_v51_exact_selections_and_metrics(self):
        prior = json.loads((ROOT / "experiments/analyses/tef_v5_1_failure_attribution_v1/results.json").read_text(encoding="utf-8"))
        v51 = {row["query_id"]: row for row in prior["per_query"] if row["included_in_search_attribution"]}
        ccc = {row["query_id"]: row for row in self.results["per_query"] if row["configuration"] == "CCC"}
        self.assertEqual(set(ccc), set(v51))
        for query_id, row in ccc.items():
            self.assertEqual(set(row["selected_ids"]), set(v51[query_id]["exact_selected_ids"]))
            self.assertAlmostEqual(row["recall_at_5"], v51[query_id]["exact_recall_at_5"])
            self.assertAlmostEqual(row["ndcg_at_5"], v51[query_id]["exact_ndcg_at_5"])
            self.assertEqual(row["complete_at_5"], v51[query_id]["exact_complete_at_5"])

    def test_all_eight_configurations_are_present_and_deterministic(self):
        self.assertEqual(set(CONFIGURATIONS), {"CCC", "CCO", "COC", "COO", "OCC", "OCO", "OOC", "OOO"})
        by_query = {}
        for row in self.results["per_query"]:
            by_query.setdefault(row["query_id"], set()).add(row["configuration"])
        self.assertTrue(by_query)
        self.assertTrue(all(value == set(CONFIGURATIONS) for value in by_query.values()))
        self.assertEqual(self.results, run())

    def test_frozen_retriever_and_exact_search_sources_are_unchanged(self):
        expected = {
            "tef_rag_v5/retriever.py": "28c0724544a4ccc661de1b7573a70ddac93b6d327d67a281b3cdd68241a2238f",
            "tef_rag_v5/exact_search.py": "51a97e55cdff3266bd5d0ab31b525e38cfd2ec70ebd64e73bc67a6a948acf623",
        }
        for relative, digest in expected.items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), digest)

    def test_oracle_helpers_are_offline_and_normal_api_rejects_gold(self):
        source = inspect.getsource(QueryConditionedSetEvidenceRetrieverV5.retrieve)
        for forbidden in ("gold", "authoring", "required_evidence_groups"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("gold", inspect.signature(QueryConditionedSetEvidenceRetrieverV5.retrieve).parameters)
        records = [{"id": "a", "asset_id": "A", "event_time": "2026-01-01T00:00:00Z",
                    "available_at": "2026-01-01T00:00:00Z", "kind": "maintenance_record", "text": "a"}]
        retriever = QueryConditionedSetEvidenceRetrieverV5(records, [{"asset_id": "A", "model_scope": "M"}], [])
        query = {"asset_id": "A", "query_time": "2026-01-02T00:00:00Z", "text": "q"}
        with self.assertRaises(ValueError):
            retriever.retrieve(query, {"a": 1.0}, query_profile={"gold": ["a"]})

    def test_oracle_mapping_and_relation_scope_are_deterministic(self):
        authoring = {"case": {"author_roles": {"b": "verification", "a": "action"},
                              "author_edges": [
                                  {"prior_id": "a", "update_id": "b", "update_relation": "verifies"},
                                  {"prior_id": "b", "update_id": "future", "update_relation": "follows"},
                              ]}}
        self.assertEqual(oracle_roles(authoring), oracle_roles(authoring))
        self.assertEqual(oracle_roles(authoring)["a"], {"role_scores": {"action": 1.0}})
        self.assertEqual(oracle_relations(authoring["case"], ["a", "b"]), [
            {"prior_id": "a", "update_id": "b", "update_relation": "verifies", "confidence": 1.0}
        ])
        current = {"selection_mode": "set", "role_demands": {}, "relation_demands": {"supports": 1.0}}
        first = oracle_profile(current, authoring["case"], ["a", "b"])
        self.assertEqual(first, oracle_profile(current, authoring["case"], ["a", "b"]))


if __name__ == "__main__":
    unittest.main()
