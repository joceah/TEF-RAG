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
    "required_nodes", "required_groups", "support_edges", "update_edges",
    "supersession_edges", "prerequisite_edges", "verification_edges",
}


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
    latest = config.get("latest5_acceptance", {})
    require(latest.get("challenge_overall_complete_at_5_max") == 0.4, "Latest-5 threshold must be 0.40")
    require(latest.get("prohibits_method_outcome_based_item_selection"), "method-outcome filtering must be prohibited")
    flow = config.get("required_annotations", {}).get("canonical_task_support_flow", {})
    require(FLOW_FIELDS <= {key for key, value in flow.items() if value is True}, "canonical flow fields missing")
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
    for phrase in ("DRAFT FOR USER REVIEW", "NOT YET FROZEN", "NO DATA GENERATED FROM THIS PROTOCOL YET", "FlowComplete@5", "event_time", "available_at", "V1", "V2", "V3"):
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
