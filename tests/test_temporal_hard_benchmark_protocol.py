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
        self.assertEqual(self.config["status"], "FROZEN_BEFORE_DATA_GENERATION")
        self.assertEqual(self.config["top_k"], 5)
        self.assertFalse(self.config["data_generation"]["performed"])

    def test_benchmark_scale_and_split(self):
        scale = self.config["benchmark_scale"]
        self.assertEqual(scale["total"], {
            "authored_chains": 400,
            "primary_intents": 1200,
            "query_rows": 2400,
            "target_assets": 100,
        })
        self.assertEqual(scale["per_chain_primary_intents"], 3)
        self.assertEqual(scale["paraphrases_per_intent"], 2)
        self.assertFalse(scale["paraphrases_are_independent_samples"])
        for layer_name in ("realistic_distribution_set", "temporal_hard_challenge_set"):
            layer = scale[layer_name]
            self.assertEqual(layer["authored_chains"], 200)
            self.assertEqual([layer["split"][x]["chains"] for x in ("development", "validation", "test")], [120, 40, 40])

    def test_difficulty_composition(self):
        composition = self.config["difficulty_composition"]
        challenge = composition["challenge"]
        self.assertEqual(challenge["single_primary_hard_chains"], 160)
        self.assertEqual(challenge["primary_chains_per_difficulty"], 20)
        self.assertEqual(challenge["primary_difficulty_split_per_type"], {"development": 12, "validation": 4, "test": 4})
        self.assertEqual(challenge["compositional_hard_chains"], 40)
        realistic = composition["realistic"]
        self.assertEqual(realistic["routine_or_mostly_recency_solvable"]["chains"], 120)
        self.assertEqual(realistic["single_temporal_complication"]["chains"], 50)
        self.assertEqual(realistic["compound_temporal_hard"]["chains"], 30)

    def test_structural_performance_and_major_stratum_gates(self):
        latest = self.config["latest5_acceptance"]
        self.assertEqual(latest["structural_gate"]["challenge_recency_solvable_at_5_max"], 0.4)
        self.assertEqual(latest["performance_gate"]["challenge_latest5_complete_at_5_max"], 0.4)
        self.assertIsNot(latest["structural_gate"], latest["performance_gate"])
        major = latest["major_stratum_policy"]
        self.assertEqual(major["minimum_primary_chains_overall"], 20)
        self.assertEqual(major["minimum_primary_intents_overall"], 60)
        self.assertEqual(major["minimum_validation_chains"], 4)
        self.assertEqual(major["minimum_validation_primary_intents"], 12)
        self.assertEqual(major["minimum_test_chains"], 4)
        self.assertEqual(major["minimum_test_primary_intents"], 12)
        self.assertEqual(major["major_stratum_recency_solvable_ceiling"], 0.5)

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
        self.assertTrue(splits["scenario_family_isolation"])
        self.assertTrue(splits["template_family_isolation"])
        self.assertTrue(splits["challenge_test_asset_disjoint"])
        self.assertTrue(splits["challenge_assets_disjoint_across_all_splits"])
        self.assertTrue(splits["realistic_assets_disjoint_from_challenge_assets"])
        self.assertFalse(splits["realistic_exact_asset_disjoint_required"])

    def test_required_metadata_for_split_audit(self):
        self.assertTrue(REQUIRED_METADATA <= set(self.config["required_metadata"]))

    def test_telemetry_reference_and_modeling_choices(self):
        telemetry = self.config["telemetry_constraints"]
        reference = telemetry["reference_system"]
        envelope = telemetry["source_backed_envelope"]
        modeling = telemetry["benchmark_modeling_choices"]
        sampling = telemetry["sampling"]
        anomaly = telemetry["gross_data_quality_anomaly_policy"]
        self.assertEqual((reference["chemistry"], reference["nominal_capacity_ah"], reference["nominal_voltage_v"]), ("LFP", 280, 3.2))
        self.assertEqual(envelope["operating_voltage_v_t_gt_0c"], [2.5, 3.65])
        self.assertEqual(envelope["operating_voltage_v_t_lte_0c"], [2.0, 3.65])
        self.assertEqual(envelope["ambient_charge_temperature_c"], [0, 60])
        self.assertEqual(envelope["ambient_discharge_temperature_c"], [-30, 60])
        self.assertEqual(modeling["normal_soc_percent"], [10, 90])
        self.assertEqual(modeling["normal_cell_temperature_c"], [15, 35])
        self.assertEqual(modeling["elevated_cell_temperature_c"], [35, 45])
        self.assertEqual(modeling["fault_event_trend_temperature_c"], [45, 55])
        self.assertEqual(sampling["raw_telemetry_seconds"], 1)
        self.assertEqual(sampling["rag_facing_evidence_seconds"], 60)
        self.assertEqual(sampling["trend_windows_minutes"], [5, 15, 60])
        self.assertEqual(anomaly["target_raw_point_ratio"], 0.0002)
        self.assertEqual(anomaly["hard_cap_raw_point_ratio"], 0.0005)
        self.assertEqual(anomaly["max_chain_ratio_with_gross_anomaly_segment"], 0.02)
        self.assertTrue(telemetry["numerical_anomaly_not_device_fault"])
        self.assertTrue(telemetry["numerical_anomaly_not_temporal_hard_query"])
        self.assertTrue(telemetry["source_backed_values_must_not_be_conflated_with_modeling_choices"])

    def test_ambient_and_cell_temperature_are_separate(self):
        telemetry = self.config["telemetry_constraints"]
        envelope = telemetry["source_backed_envelope"]
        scope = telemetry["temperature_variable_scope"]
        self.assertEqual(envelope["ambient_charge_temperature_c"], [0, 60])
        self.assertEqual(envelope["ambient_discharge_temperature_c"], [-30, 60])
        self.assertTrue(scope["source_backed_temperature_is_ambient"])
        self.assertTrue(scope["cell_temperature_is_separate_telemetry_variable"])
        self.assertTrue(scope["cell_temperature_must_not_be_validated_against_ambient_envelope_directly"])
        self.assertTrue(scope["cell_temperature_outside_modeling_band_is_not_automatically_data_quality_anomaly"])
        self.assertNotIn("cell_temperature_hard_max", str(telemetry))

    def test_normalized_p_rate_is_not_current(self):
        modeling = self.config["telemetry_constraints"]["benchmark_modeling_choices"]
        self.assertEqual(modeling["routine_normalized_p_rate_max"], 0.5)
        self.assertEqual(modeling["high_load_normalized_p_rate_range"], [0.5, 1.0])
        self.assertTrue(modeling["p_rate_must_not_be_numerically_mapped_to_amperes"])
        self.assertNotIn("routine_abs_rate_p_max", modeling)
        self.assertNotIn("high_load_abs_rate_p_range", modeling)
        self.assertNotIn("|I| <= 0.5P", self.markdown)
        self.assertNotIn("routine current", self.markdown)

    def test_review_policy_is_ai_assisted_not_expert_claim(self):
        review = self.config["review_protocol"]
        self.assertFalse(review["claim_expert_reviewed"])
        self.assertFalse(review["claim_field_certified"])
        self.assertTrue(review["all_chains_deterministic_validation"])
        self.assertTrue(review["all_chains_ai_semantic_review"])
        self.assertTrue(review["validation_and_test_second_blind_ai_review_pass"])
        self.assertTrue(review["second_pass_cannot_see_first_verdict_before_judgment"])
        self.assertTrue(review["second_pass_cannot_see_first_reasoning_before_judgment"])
        self.assertTrue(review["second_pass_must_produce_own_verdict_and_reasoning_before_comparison"])
        self.assertNotIn("validation_and_test_second_independent_ai_review", review)
        self.assertTrue(review["unresolved_not_allowed_in_validation_or_test"])
        self.assertIn("AI-assisted", review["paper_label"])

    def test_test_access_policy(self):
        policy = self.config["evaluation_access_policy"]
        self.assertFalse(policy["test_gold_public_branch_before_primary_evaluation"])
        self.assertTrue(policy["test_gold_sha256_required"])
        self.assertTrue(policy["primary_test_only_after_v6_architecture_objective_weights_and_baselines_frozen"])
        self.assertTrue(policy["test_rerun_after_bugfix_requires_audit_log"])

    def test_sealed_test_review_policy(self):
        sealed = self.config["sealed_test_review"]
        self.assertTrue(sealed["enabled"])
        self.assertTrue(sealed["gold_and_flow_visible_only_inside_sealed_review"])
        self.assertTrue(sealed["item_level_review_reasoning_hidden_from_algorithm_development"])
        self.assertTrue(sealed["algorithm_development_receives_aggregate_qc_only"])
        self.assertTrue(sealed["unresolved_items_repaired_before_final_hash"])
        self.assertTrue(sealed["final_test_artifact_rehashed_after_repairs"])
        self.assertTrue(sealed["target_method_not_evaluated_before_final_seal"])

    def test_public_source_registry_is_versioned_and_strict(self):
        sources = self.config["public_sources"]
        self.assertGreaterEqual(len(sources), 5)
        required_fields = {"name", "vendor_or_institution", "version_or_date", "access_date", "supports", "url"}
        self.assertTrue(all(required_fields <= set(source) for source in sources))
        names = " ".join(source["name"] for source in sources)
        for identity in ("V1.1", "V3.3", "REPT", "RWTH"):
            self.assertIn(identity, names)
        rwth = next(source for source in sources if "RWTH" in source["name"])
        self.assertEqual(rwth["supports"], ["one_second_resolution_BESS_field_data"])
        self.assertFalse(any("lfp" in support.lower() for support in rwth["supports"]))

    def test_no_results_or_generation_exist(self):
        self.assertFalse(self.config["data_generation"]["performed"])
        self.assertTrue(self.config["data_generation"]["sample_counts_specified"])
        self.assertTrue(self.config["data_generation"]["numeric_generation_policy_specified"])
        self.assertNotIn("observed_results", self.config)
        self.assertIn("NO DATA GENERATED FROM THIS PROTOCOL YET", self.markdown)


if __name__ == "__main__":
    unittest.main()
