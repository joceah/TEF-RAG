import unittest

from scripts.validate_temporal_hard_benchmark_protocol import FLOW_FIELDS, load_protocol, validate


class TemporalHardBenchmarkProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config, cls.markdown = load_protocol()

    def test_protocol_validator_accepts_draft(self):
        self.assertEqual(validate(self.config, self.markdown), [])

    def test_status_top_k_and_latest5_gate(self):
        self.assertEqual(self.config["status"], "DRAFT_FOR_REVIEW")
        self.assertEqual(self.config["top_k"], 5)
        self.assertEqual(self.config["latest5_acceptance"]["challenge_overall_complete_at_5_max"], 0.4)

    def test_canonical_flow_and_bitemporal_rules(self):
        flow = self.config["required_annotations"]["canonical_task_support_flow"]
        self.assertTrue(all(flow[field] for field in FLOW_FIELDS))
        self.assertEqual(set(self.config["bitemporal_required"]["fields"]), {"event_time", "available_at"})

    def test_versioning_and_split_isolation(self):
        self.assertEqual(self.config["procedure_versioning_required"]["versions"], ["V1", "V2", "V3"])
        splits = self.config["split_rules"]
        self.assertTrue(splits["chain_isolation"] and splits["intent_isolation"] and splits["paraphrases_share_split"])

    def test_telemetry_is_separate_and_no_results_or_generation_exist(self):
        telemetry = self.config["telemetry_constraints"]
        self.assertTrue(telemetry["numerical_anomaly_not_device_fault"])
        self.assertTrue(telemetry["numerical_anomaly_not_temporal_hard_query"])
        self.assertFalse(self.config["data_generation"]["performed"])
        self.assertNotIn("observed_results", self.config)
        self.assertIn("NO DATA GENERATED FROM THIS PROTOCOL YET", self.markdown)


if __name__ == "__main__":
    unittest.main()
