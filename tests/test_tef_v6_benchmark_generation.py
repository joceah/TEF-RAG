import json
import tempfile
import unittest
from pathlib import Path

from scripts.generate_tef_v6_benchmark_v1 import CONFIG, generate, load, write_dataset
from scripts.validate_tef_v6_benchmark_v1 import validate_dataset


class TefV6BenchmarkGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load(CONFIG)

    def test_preregistered_counts_and_attempts(self):
        self.assertEqual(self.config["base_random_seed"], 20260915)
        self.assertEqual(self.config["attempt_seeds"], [20260915, 20260916, 20260917, 20260918, 20260919])
        self.assertEqual(self.config["target_counts"]["authored_chains"], 400)
        self.assertEqual(self.config["target_counts"]["query_rows"], 2400)

    def test_generation_is_deterministic(self):
        first = generate(self.config, self.config["base_random_seed"])
        second = generate(self.config, self.config["base_random_seed"])
        self.assertEqual(first, second)
        chains, evidence, queries, gold_public, gold_test = first
        self.assertEqual((len(chains), len(queries), len({q["intent_id"] for q in queries}), len({c["asset_id"] for c in chains})), (400, 2400, 1200, 100))
        self.assertEqual((len(gold_public), len(gold_test)), (1920, 480))
        self.assertGreater(len(evidence), 2400)

    def test_temporary_dataset_validates_and_has_no_public_test_gold(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output, sealed = root / "dataset", root / "sealed.jsonl"
            write_dataset(output, sealed, self.config, self.config["base_random_seed"], 0)
            errors, summary = validate_dataset(output, sealed, write_summary=False)
            self.assertEqual(errors, [])
            self.assertEqual(summary["status"], "PASSED")
            self.assertFalse((output / "public/gold_test.jsonl").exists())
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["sealed_test_artifact"]["committed"])


if __name__ == "__main__":
    unittest.main()
