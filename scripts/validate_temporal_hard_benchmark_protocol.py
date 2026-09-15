"""Validate the draft Temporal-Hard benchmark protocol, not benchmark data."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/temporal_hard_benchmark_protocol_v1.json"
MARKDOWN = ROOT / "plans/TEF_RAG_v6_temporal_hard_benchmark_protocol_v1.md"

DIFFICULTIES = {
    "MULTI_EPISODE_DISAMBIGUATION", "CUTOFF_SENSITIVE", "LATE_ARRIVING_EVIDENCE",
    "SUPERSEDED_DIAGNOSIS", "PROCEDURE_VERSIONING", "CROSS_SOURCE_REQUIRED",
    "SIMILAR_SYMPTOM_DIFFERENT_CAUSE", "PERSISTENT_UNCERTAINTY",
}
FLOW_FIELDS = {
    "required_nodes", "required_groups", "required_flow_edges", "support_edges", "update_edges",
    "supersession_edges", "prerequisite_edges", "verification_edges", "flowcomplete_semantics",
}
REQUIRED_METADATA = {"scenario_family_id", "template_family_id", "asset_id", "chain_id", "intent_id"}
FLOW_EDGE_FIELDS = {"edge_id", "from_group", "to_group", "relation_type", "allowed_endpoint_pairs"}


def load_protocol(config_path=CONFIG, markdown_path=MARKDOWN):
    return json.loads(Path(config_path).read_text(encoding="utf-8")), Path(markdown_path).read_text(encoding="utf-8")


def validate(config, markdown):
    errors = []
    require = lambda condition, message: errors.append(message) if not condition else None

    require(config.get("status") == "DRAFT_FOR_REVIEW", "status must remain DRAFT_FOR_REVIEW until explicit freeze")
    require(config.get("top_k") == 5, "top_k must be 5")
    require(DIFFICULTIES == set(config.get("difficulty_types", [])), "difficulty taxonomy mismatch")

    scale = config.get("benchmark_scale", {})
    total = scale.get("total", {})
    require(total.get("authored_chains") == 400, "benchmark must contain 400 authored chains")
    require(total.get("primary_intents") == 1200, "benchmark must contain 1200 primary intents")
    require(total.get("query_rows") == 2400, "benchmark must contain 2400 query rows")
    require(total.get("target_assets") == 100, "benchmark must contain 100 target assets")
    require(scale.get("per_chain_primary_intents") == 3, "each chain must have 3 primary intents")
    require(scale.get("paraphrases_per_intent") == 2, "each intent must have 2 phrasings")
    require(scale.get("paraphrases_are_independent_samples") is False, "paraphrases must not be independent samples")
    for layer_name in ("realistic_distribution_set", "temporal_hard_challenge_set"):
        layer = scale.get(layer_name, {})
        require(layer.get("authored_chains") == 200, f"{layer_name} must have 200 chains")
        require(layer.get("primary_intents") == 600, f"{layer_name} must have 600 intents")
        require(layer.get("query_rows") == 1200, f"{layer_name} must have 1200 query rows")
        split = layer.get("split", {})
        require([split.get(x, {}).get("chains") for x in ("development", "validation", "test")] == [120, 40, 40], f"{layer_name} split must be 120/40/40 chains")

    composition = config.get("difficulty_composition", {})
    challenge_mix = composition.get("challenge", {})
    require(challenge_mix.get("single_primary_hard_chains") == 160, "Challenge must have 160 single-primary hard chains")
    require(challenge_mix.get("primary_chains_per_difficulty") == 20, "each primary difficulty must have 20 chains")
    require(challenge_mix.get("primary_difficulty_split_per_type") == {"development": 12, "validation": 4, "test": 4}, "primary difficulty split must be 12/4/4")
    require(challenge_mix.get("compositional_hard_chains") == 40, "Challenge must have 40 compositional-hard chains")
    realistic_mix = composition.get("realistic", {})
    require(realistic_mix.get("routine_or_mostly_recency_solvable", {}).get("chains") == 120, "Realistic routine mix must be 120")
    require(realistic_mix.get("single_temporal_complication", {}).get("chains") == 50, "Realistic single-temporal mix must be 50")
    require(realistic_mix.get("compound_temporal_hard", {}).get("chains") == 30, "Realistic compound-hard mix must be 30")

    splits = config.get("split_rules", {})
    require(splits.get("chain_isolation") and splits.get("intent_isolation"), "chain/intent split isolation required")
    require(splits.get("paraphrases_share_split"), "paraphrases must share split")
    require(splits.get("scenario_family_isolation") is True, "scenario family test isolation required")
    require(splits.get("template_family_isolation") is True, "template family split isolation required")
    require(splits.get("challenge_test_asset_disjoint") is True, "Challenge test asset isolation required")
    require(splits.get("challenge_assets_disjoint_across_all_splits") is True, "Challenge assets must be split-disjoint")
    require(splits.get("realistic_exact_asset_disjoint_required") is False, "Realistic exact asset isolation must not be required")
    require(splits.get("realistic_assets_disjoint_from_challenge_assets") is True, "Realistic and Challenge asset pools must differ")
    require(REQUIRED_METADATA <= set(config.get("required_metadata", [])), "required split-audit metadata missing")

    latest = config.get("latest5_acceptance", {})
    structural = latest.get("structural_gate", {})
    performance = latest.get("performance_gate", {})
    major = latest.get("major_stratum_policy", {})
    require(structural.get("challenge_recency_solvable_at_5_max") == 0.4, "structural RECENCY_SOLVABLE_AT_5 threshold must be 0.40")
    require(performance.get("challenge_latest5_complete_at_5_max") == 0.4, "Latest-5 performance threshold must be 0.40")
    require(major.get("minimum_primary_chains_overall") == 20, "major stratum must have >=20 primary chains")
    require(major.get("minimum_primary_intents_overall") == 60, "major stratum must have >=60 primary intents")
    require(major.get("minimum_validation_chains") == 4 and major.get("minimum_test_chains") == 4, "major stratum validation/test chain minima must be 4/4")
    require(major.get("minimum_validation_primary_intents") == 12 and major.get("minimum_test_primary_intents") == 12, "major stratum validation/test intent minima must be 12/12")
    require(major.get("major_stratum_recency_solvable_ceiling") == 0.5, "major stratum recency-solvable ceiling must be 0.50")
    require(latest.get("prohibits_method_outcome_based_item_selection"), "method-outcome filtering must be prohibited")

    flow = config.get("required_annotations", {}).get("canonical_task_support_flow", {})
    require(FLOW_FIELDS <= set(flow), "canonical flow fields missing")
    group_fields = set(flow.get("required_groups", {}).get("item_schema", {}).get("required_fields", []))
    require({"group_id", "acceptable_evidence_ids"} <= group_fields, "required group schema missing group_id/evidence IDs")
    edge_fields = set(flow.get("required_flow_edges", {}).get("item_schema", {}).get("required_fields", []))
    require(FLOW_EDGE_FIELDS <= edge_fields, "required flow edge schema missing fields")
    semantics = flow.get("flowcomplete_semantics", {})
    require(semantics.get("assignment_type") == "one_retrieved_acceptable_evidence_per_required_group", "FlowComplete assignment type mismatch")
    require(semantics.get("global_consistency_required") is True, "FlowComplete must require global consistency")
    require(semantics.get("same_group_assignment_reused_across_all_incident_edges") is True, "group assignment must be reused across incident edges")
    require(semantics.get("assignment_is_existential") is True, "FlowComplete assignment must be existential")
    require(semantics.get("assignment_must_satisfy_all_required_flow_edges") is True, "assignment must satisfy every required flow edge")
    require(semantics.get("assignment_injective") is False, "FlowComplete assignment must not require injectivity")
    require(semantics.get("same_evidence_can_fill_multiple_groups_only_if_acceptable_in_each") is True, "shared evidence must be acceptable in every assigned group")
    require(semantics.get("complete_primary_semantics") == "required_groups", "Complete primary semantics must be required_groups")
    require(semantics.get("required_nodes_role") == "optional_diagnostic_or_provenance", "required_nodes role must be diagnostic/provenance")
    required_nodes = flow.get("required_nodes", {})
    require(required_nodes.get("required") is False, "required_nodes must not be a primary Complete requirement")
    require(required_nodes.get("role") == "optional_diagnostic_or_provenance", "required_nodes annotation role mismatch")
    require(flow.get("baseline_graph_prediction_required") is False, "baselines must not predict graphs")
    require(flow.get("complete_can_be_one_while_flowcomplete_is_zero") is True, "FlowComplete must differ from Complete")
    require(set(config.get("primary_metrics", [])) == {"Recall@5", "nDCG@5", "Complete@5", "FlowComplete@5"}, "primary metrics mismatch")

    bitemporal = config.get("bitemporal_required", {})
    require(set(bitemporal.get("fields", [])) == {"event_time", "available_at"}, "bitemporal fields missing")
    versions = config.get("procedure_versioning_required", {})
    require(versions.get("versions") == ["V1", "V2", "V3"], "V1/V2/V3 required")

    telemetry = config.get("telemetry_constraints", {})
    reference = telemetry.get("reference_system", {})
    envelope = telemetry.get("source_backed_envelope", {})
    modeling = telemetry.get("benchmark_modeling_choices", {})
    sampling = telemetry.get("sampling", {})
    anomaly = telemetry.get("gross_data_quality_anomaly_policy", {})
    require(reference.get("chemistry") == "LFP" and reference.get("nominal_capacity_ah") == 280 and reference.get("nominal_voltage_v") == 3.2, "LFP 280Ah reference system mismatch")
    require(envelope.get("operating_voltage_v_t_gt_0c") == [2.5, 3.65], "T>0C voltage envelope mismatch")
    require(envelope.get("operating_voltage_v_t_lte_0c") == [2.0, 3.65], "T<=0C voltage envelope mismatch")
    require(envelope.get("ambient_charge_temperature_c") == [0, 60], "charge temperature envelope mismatch")
    require(envelope.get("ambient_discharge_temperature_c") == [-30, 60], "discharge temperature envelope mismatch")
    require(modeling.get("normal_soc_percent") == [10, 90], "normal SOC modeling window mismatch")
    require(modeling.get("normal_cell_temperature_c") == [15, 35], "normal temperature modeling band mismatch")
    require(modeling.get("elevated_cell_temperature_c") == [35, 45], "elevated temperature modeling band mismatch")
    require(modeling.get("fault_event_trend_temperature_c") == [45, 55], "fault trend temperature band mismatch")
    require(sampling.get("raw_telemetry_seconds") == 1 and sampling.get("rag_facing_evidence_seconds") == 60, "sampling cadence mismatch")
    require(sampling.get("trend_windows_minutes") == [5, 15, 60], "trend windows mismatch")
    require(anomaly.get("target_raw_point_ratio") == 0.0002, "gross anomaly target ratio must be 0.02%")
    require(anomaly.get("hard_cap_raw_point_ratio") == 0.0005, "gross anomaly hard cap must be 0.05%")
    require(anomaly.get("max_chain_ratio_with_gross_anomaly_segment") == 0.02, "gross anomaly chain cap must be 2%")
    require(telemetry.get("numerical_anomaly_not_device_fault") and telemetry.get("numerical_anomaly_not_temporal_hard_query"), "telemetry concepts must be separated")
    require(telemetry.get("source_backed_values_must_not_be_conflated_with_modeling_choices") is True, "source-backed and modeling-choice values must be separated")

    review = config.get("review_protocol", {})
    require(review.get("claim_expert_reviewed") is False and review.get("claim_field_certified") is False, "benchmark must not claim expert/field certification")
    require(review.get("all_chains_deterministic_validation") is True, "all chains need deterministic validation")
    require(review.get("all_chains_ai_semantic_review") is True, "all chains need AI-assisted semantic review")
    require(review.get("validation_and_test_second_independent_ai_review") is True, "validation/test need second review")
    require(review.get("unresolved_not_allowed_in_validation_or_test") is True, "unresolved review items cannot enter validation/test")

    access = config.get("evaluation_access_policy", {})
    require(access.get("test_gold_public_branch_before_primary_evaluation") is False, "test gold must stay off public development branch before primary evaluation")
    require(access.get("test_gold_sha256_required") is True, "test gold SHA256 freeze required")
    require(access.get("primary_test_only_after_v6_architecture_objective_weights_and_baselines_frozen") is True, "primary test must wait for method freeze")

    restrictions = config.get("diagnostic_only_restrictions", {})
    require(restrictions.get("old_196_subset_is_not_new_test"), "old 196 subset restriction missing")
    require(config.get("data_generation", {}).get("performed") is False, "protocol must not claim data generation")
    require(config.get("data_generation", {}).get("sample_counts_specified") is True, "sample counts must be specified")
    require(config.get("data_generation", {}).get("numeric_generation_policy_specified") is True, "numeric generation policy must be specified")
    require(config.get("multi_step_policy", {}).get("implementation_in_this_protocol_round") is False, "multi-step retrieval must remain unimplemented")
    require(len(config.get("public_sources", [])) >= 3, "public source registry must contain at least three entries")

    for phrase in (
        "DRAFT FOR USER REVIEW", "NOT YET FROZEN", "NO DATA GENERATED FROM THIS PROTOCOL YET",
        "400 authored chains", "1200 independent primary intents", "2400 query rows",
        "RECENCY_SOLVABLE_AT_5", "Complete@5 = 1, FlowComplete@5 = 0", "required_flow_edges",
        "allowed_endpoint_pairs", "全局一致", "同一个 group 在所有相连 edge 中必须复用同一个 evidence",
        "280 Ah-class", "0.02%", "public-source-grounded, AI-assisted reviewed synthetic benchmark",
        "event_time", "available_at", "scenario_family_id", "template_family_id", "V1", "V2", "V3"
    ):
        require(phrase in markdown, f"markdown missing: {phrase}")
    return errors


def main():
    config, markdown = load_protocol()
    errors = validate(config, markdown)
    if errors:
        raise SystemExit("protocol validation failed:\n- " + "\n- ".join(errors))
    print("protocol validation passed: DRAFT_FOR_REVIEW; parameters specified; no data generated")


if __name__ == "__main__":
    main()
