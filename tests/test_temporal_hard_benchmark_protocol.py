import unittest

from scripts.validate_temporal_hard_benchmark_protocol import FLOW_EDGE_FIELDS, FLOW_FIELDS, REQUIRED_METADATA, load_protocol, validate


class TemporalHardBenchmarkProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config, cls.markdown = load_protocol()

    def test_protocol_validator_accepts_draft(self):
        self.assertEqual(validate(self.config, self.markdown), [])

    def test_status_and_top_k(self):
        self.assertEqual(self.config["status"], "DRAFT_FOR_REVIEW")
        self.assertEqual(self.config["top_k"], 5)

    def test_structural_and_performance_latest5_gates_are_separate(self):
        latest = self.config["latest5_acceptance"]
        self.assertEqual(latest["structural_gate"]["challenge_recency_solvable_at_5_max"], 0.4)
        self.assertEqual(latest["performance_gate"]["challenge_latest5_complete_at_5_max"], 0.4)
        self.assertIsNot(latest["structural_gate"], latest["performance_gate"])
        self.assertEqual(latest["major_stratum_policy"]["major_stratum_definition"], "DRAFT_FOR_REVIEW")
        self.assertEqual(latest["major_stratum_policy"]["major_stratum_recency_solvable_ceiling"], "DRAFT_FOR_REVIEW")

    def test_canonical_flow_and_bitemporal_rules(self):
        flow = self.config["required_annotations"]["canonical_task_support_flow"]
        self.assertTrue(FLOW_FIELDS <= set(flow))
        self.assertEqual(set(self.config["bitemporal_required"]["fields"]), {"event_time", "available_at"})

    def test_flowcomplete_is_not_definitionally_equal_to_complete(self):
        flow = self.config["required_annotations"]["canonical_task_support_flow"]
        edge_fields = set(flow["required_flow_edges"]["item_schema"]["required_fields"])
        self.assertTrue(FLOW_EDGE_FIELDS <= edge_fields)
        groups = {"G1": {"A1", "A2"}, "G2": {"B1", "B2"}}
        selected = {"A1", "B1"}
        allowed_pairs = {("A1", "B2"), ("A2", "B1")}
        complete = all(selected & choices for choices in groups.values())
        flow_complete = complete and any(left in selected and right in selected for left, right in allowed_pairs)
        self.assertTrue(complete)
        self.assertFalse(flow_complete)
        self.assertFalse(flow["baseline_graph_prediction_required"])

    def test_versioning_and_split_isolation(self):
        self.assertEqual(self.config["procedure_versioning_required"]["versions"], ["V1", "V2", "V3"])
        splits = self.config["split_rules"]
        self.assertTrue(splits["chain_isolation"] and splits["intent_isolation"] and splits["paraphrases_share_split"])

    def test_family_and_asset_split_constraints(self):
        splits = self.config["split_rules"]
        self.assertTrue(splits["scenario_family_isolation"])
        self.assertTrue(splits["template_family_isolation"])
        self.assertTrue(splits["challenge_test_asset_disjoint"])
        self.assertFalse(splits["realistic_exact_asset_disjoint_required"])

    def test_required_metadata_for_split_audit(self):
        self.assertTrue(REQUIRED_METADATA <= set(self.config["required_metadata"]))

    def test_telemetry_is_separate_and_no_results_or_generation_exist(self):
        telemetry = self.config["telemetry_constraints"]
        self.assertTrue(telemetry["numerical_anomaly_not_device_fault"])
        self.assertTrue(telemetry["numerical_anomaly_not_temporal_hard_query"])
        self.assertFalse(self.config["data_generation"]["performed"])
        self.assertNotIn("observed_results", self.config)
        self.assertIn("NO DATA GENERATED FROM THIS PROTOCOL YET", self.markdown)


if __name__ == "__main__":
    unittest.main()
