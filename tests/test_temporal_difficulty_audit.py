import hashlib
import json
import unittest

from scripts.audit_temporal_maintenance_difficulty_v1 import DATA, MANIFEST_OUT, OUT, main


class TemporalDifficultyAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = {path: hashlib.sha256((DATA / path).read_bytes()).hexdigest()
                      for path in json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))["output_hashes"]}
        main()
        cls.rows = [json.loads(line) for line in MANIFEST_OUT.read_text(encoding="utf-8").splitlines() if line]

    def test_hard_manifest_has_exactly_196_temporal_non_recency_queries(self):
        self.assertEqual(len(self.rows), 196)
        self.assertEqual(len({row["query_id"] for row in self.rows}), 196)
        for row in self.rows:
            self.assertEqual(row["task"], "temporal")
            self.assertFalse(row["recency_solvable_at_5"])
            self.assertNotIn("RECENCY_ONLY", row["difficulty_labels"])
            self.assertEqual(row["diagnostic_status"], "seen development diagnostic subset")
            self.assertFalse(row["independent_validation_or_test"])

    def test_original_dataset_outputs_are_not_modified(self):
        after = {path: hashlib.sha256((DATA / path).read_bytes()).hexdigest() for path in self.before}
        self.assertEqual(self.before, after)

    def test_report_has_rendered_count_and_unambiguous_method_name(self):
        report = (OUT / "report.md").read_text(encoding="utf-8")
        self.assertNotIn("{len(operational_hard)}", report)
        self.assertIn("196 个（25.52%）", report)
        self.assertIn("TMC-RAG-v2 (frozen)", report)
        self.assertNotIn("TEF*", report)
        self.assertNotIn("TEF (frozen TMC-RAG-v2 run)", report)


if __name__ == "__main__":
    unittest.main()
