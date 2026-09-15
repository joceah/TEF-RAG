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
    "supersession_edges", "prerequisite_edges", "verification_edges",
}
REQUIRED_METADATA = {"scenario_family_id", "template_family_id", "asset_id", "chain_id", "intent_id"}
FLOW_EDGE_FIELDS = {"edge_id", "from_group", "to_group", "relation_type", "allowed_endpoint_pairs"}


def load_protocol(config_path=CONFIG, markdown_path=MARKDOWN):
    return json.loads(Path(config_path).read_text(encoding="utf-8")), Path(markdown_path).read_text(encoding="utf-8")


def validate(config, markdown):
    errors = []
    require = lambda condition, message: errors.append(message) if not condition else None
    require(config.get("status") == "DRAFT_FOR_REVIEW", "status must remain DRAFT_FOR_REVIEW")
    require(config.get("top_k") == 5, "top_k must be 5")
    require(DIFFICULTIES == set(config.get("difficulty_types", [])), "difficulty taxonomy mismatch")
    splits = config.get("split_rules", {})
    require(splits.get("chain_isolation") and splits.get("intent_isolation"), "chain/intent split isolation required")
    require(splits.get("paraphrases_share_split"), "paraphrases must share split")
    require(splits.get("scenario_family_isolation") is True, "scenario family test isolation required")
    require(splits.get("template_family_isolation") is True, "template family split isolation required")
    require(splits.get("challenge_test_asset_disjoint") is True, "Challenge test asset isolation required")
    require(splits.get("realistic_exact_asset_disjoint_required") is False, "Realistic exact asset isolation must not be required")
    require(REQUIRED_METADATA <= set(config.get("required_metadata", [])), "required split-audit metadata missing")
    latest = config.get("latest5_acceptance", {})
    structural = latest.get("structural_gate", {})
    performance = latest.get("performance_gate", {})
    major = latest.get("major_stratum_policy", {})
    require(structural.get("challenge_recency_solvable_at_5_max") == 0.4, "structural RECENCY_SOLVABLE_AT_5 threshold must be 0.40")
    require(performance.get("challenge_latest5_complete_at_5_max") == 0.4, "Latest-5 performance threshold must be 0.40")
    require(major.get("major_stratum_definition") == "DRAFT_FOR_REVIEW", "major stratum definition must remain draft")
    require(major.get("major_stratum_recency_solvable_ceiling") == "DRAFT_FOR_REVIEW", "major stratum ceiling must remain draft")
    require(latest.get("prohibits_method_outcome_based_item_selection"), "method-outcome filtering must be prohibited")
    flow = config.get("required_annotations", {}).get("canonical_task_support_flow", {})
    require(FLOW_FIELDS <= set(flow), "canonical flow fields missing")
    group_fields = set(flow.get("required_groups", {}).get("item_schema", {}).get("required_fields", []))
    require({"group_id", "acceptable_evidence_ids"} <= group_fields, "required group schema missing group_id/evidence IDs")
    edge_fields = set(flow.get("required_flow_edges", {}).get("item_schema", {}).get("required_fields", []))
    require(FLOW_EDGE_FIELDS <= edge_fields, "required flow edge schema missing fields")
    require(flow.get("baseline_graph_prediction_required") is False, "baselines must not predict graphs")
    require(flow.get("complete_can_be_one_while_flowcomplete_is_zero") is True, "FlowComplete must differ from Complete")
    require(set(config.get("primary_metrics", [])) == {"Recall@5", "nDCG@5", "Complete@5", "FlowComplete@5"}, "primary metrics mismatch")
    bitemporal = config.get("bitemporal_required", {})
    require(set(bitemporal.get("fields", [])) == {"event_time", "available_at"}, "bitemporal fields missing")
    versions = config.get("procedure_versioning_required", {})
    require(versions.get("versions") == ["V1", "V2", "V3"], "V1/V2/V3 required")
    telemetry = config.get("telemetry_constraints", {})
    require(telemetry.get("numerical_anomaly_not_device_fault") and telemetry.get("numerical_anomaly_not_temporal_hard_query"), "telemetry concepts must be separated")
    restrictions = config.get("diagnostic_only_restrictions", {})
    require(restrictions.get("old_196_subset_is_not_new_test"), "old 196 subset restriction missing")
    require(config.get("data_generation", {}).get("performed") is False, "protocol must not claim data generation")
    require(config.get("multi_step_policy", {}).get("implementation_in_this_protocol_round") is False, "multi-step retrieval must remain unimplemented")
    for phrase in ("DRAFT FOR USER REVIEW", "NOT YET FROZEN", "NO DATA GENERATED FROM THIS PROTOCOL YET", "RECENCY_SOLVABLE_AT_5", "Complete@5 = 1, FlowComplete@5 = 0", "required_flow_edges", "allowed_endpoint_pairs", "event_time", "available_at", "scenario_family_id", "template_family_id", "V1", "V2", "V3"):
        require(phrase in markdown, f"markdown missing: {phrase}")
    return errors


def main():
    config, markdown = load_protocol()
    errors = validate(config, markdown)
    if errors:
        raise SystemExit("protocol validation failed:\n- " + "\n- ".join(errors))
    print("protocol validation passed: DRAFT_FOR_REVIEW; no data generated")


if __name__ == "__main__":
    main()
