"""Official-protocol adapter for public development and validation gold only."""
from __future__ import annotations

from itertools import product
import math


def group_coverage(ids: list[str], gold: dict) -> tuple[int, int]:
    selected = set(ids)
    groups = gold["required_groups"]
    return sum(bool(selected & set(group["acceptable_evidence_ids"])) for group in groups), len(groups)


def flow_complete(ids: list[str], gold: dict) -> bool:
    """Apply the frozen existential, globally consistent group assignment."""
    selected = set(ids)
    groups = {group["group_id"]: sorted(selected & set(group["acceptable_evidence_ids"])) for group in gold["required_groups"]}
    if any(not options for options in groups.values()):
        return False
    group_ids = sorted(groups)
    for values in product(*(groups[group_id] for group_id in group_ids)):
        assignment = dict(zip(group_ids, values))
        valid = True
        for edge in gold["required_flow_edges"]:
            pair = [assignment[edge["from_group"]], assignment[edge["to_group"]]]
            if pair not in edge["allowed_endpoint_pairs"]:
                valid = False
                break
        if valid:
            return True
    return False


def evaluate_prediction(prediction: dict, gold: dict, k: int = 5) -> dict[str, float]:
    ids = prediction["selected_evidence_ids"][:k]
    covered, total = group_coverage(ids, gold)
    relevant = {identifier for group in gold["required_groups"] for identifier in group["acceptable_evidence_ids"]}
    dcg = sum((1.0 / math.log2(rank + 1)) for rank, identifier in enumerate(ids, 1) if identifier in relevant)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1))
    predicted_edges = {
        (edge["source_id"], edge["target_id"], edge["relation_type"])
        for edge in prediction.get("relations", [])
    }
    matched_edges = 0
    for edge in gold["required_flow_edges"]:
        if any((pair[0], pair[1], edge["relation_type"]) in predicted_edges for pair in edge["allowed_endpoint_pairs"]):
            matched_edges += 1
    uncertainty_predicted = prediction.get("uncertainty", {}).get("status") == "persistent"
    return {
        "recall_at_5": covered / total if total else 0.0,
        "hit_at_5": float(covered > 0),
        "ndcg_at_5": dcg / ideal if ideal else 0.0,
        "complete_at_5": float(covered == total),
        "flow_complete_at_5": float(flow_complete(ids, gold)),
        "edge_recall": matched_edges / len(gold["required_flow_edges"]) if gold["required_flow_edges"] else 1.0,
        "uncertainty_accuracy": float(uncertainty_predicted == bool(gold.get("persistent_uncertainty"))),
    }


def average(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    return {key: sum(row[key] for row in rows) / len(rows) for key in rows[0]}
