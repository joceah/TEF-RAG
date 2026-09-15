import unittest
from itertools import product

from scripts.validate_temporal_hard_benchmark_protocol import FLOW_EDGE_FIELDS, FLOW_FIELDS, REQUIRED_METADATA, load_protocol, validate


def global_flow_assignment_exists(selected_ids, required_groups, required_flow_edges):
    """Minimal exhaustive checker for protocol semantics; not a benchmark evaluator."""
    selected = set(selected_ids)
    group_ids = list(required_groups)
    domains = [sorted(selected.intersection(required_groups[group_id])) for group_id in group_ids]
    if any(not domain for domain in domains):
        return False
    for values in product(*domains):
        assignment = dict(zip(group_ids, values))
        if all(
            (assignment[edge["from_group"]], assignment[edge["to_group"]])
            in {tuple(pair) for pair in edge["allowed_endpoint_pairs"]}
            for edge in required_flow_edges
        ):
            return True
    return False


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

    def test_local_edges_pass_but_global_assignment_fails(self):
        groups = {"G1": {"A1"}, "G2": {"B1", "B2"}, "G3": {"C1"}}
        edges = [
            {"from_group": "G1", "to_group": "G2", "allowed_endpoint_pairs": [["A1", "B1"]]},
            {"from_group": "G2", "to_group": "G3", "allowed_endpoint_pairs": [["B2", "C1"]]},
        ]
        selected = {"A1", "B1", "B2", "C1"}
        complete = all(selected & acceptable for acceptable in groups.values())
        local_edges_pass = all(
            any(left in selected and right in selected for left, right in edge["allowed_endpoint_pairs"])
            for edge in edges
        )
        self.assertTrue(complete)
        self.assertTrue(local_edges_pass)
        self.assertFalse(global_flow_assignment_exists(selected, groups, edges))

    def test_global_assignment_succeeds(self):
        groups = {"G1": {"A1"}, "G2": {"B1", "B2"}, "G3": {"C1"}}
        edges = [
            {"from_group": "G1", "to_group": "G2", "allowed_endpoint_pairs": [["A1", "B1"]]},
            {"from_group": "G2", "to_group": "G3", "allowed_endpoint_pairs": [["B1", "C1"]]},
        ]
        selected = {"A1", "B1", "B2", "C1"}
        self.assertTrue(all(selected & acceptable for acceptable in groups.values()))
        self.assertTrue(global_flow_assignment_exists(selected, groups, edges))

    def test_flowcomplete_global_semantics_are_machine_readable(self):
        flow = self.config["required_annotations"]["canonical_task_support_flow"]
        semantics = flow["flowcomplete_semantics"]
        self.assertTrue(semantics["global_consistency_required"])
        self.assertTrue(semantics["same_group_assignment_reused_across_all_incident_edges"])
        self.assertTrue(semantics["assignment_is_existential"])
        self.assertTrue(semantics["assignment_must_satisfy_all_required_flow_edges"])
        self.assertFalse(semantics["assignment_injective"])
        self.assertEqual(semantics["complete_primary_semantics"], "required_groups")
        self.assertEqual(semantics["required_nodes_role"], "optional_diagnostic_or_provenance")

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
