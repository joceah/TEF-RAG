"""Frozen temporal-maintenance v2 evaluation metric used by offline audits."""
import math

from scripts.temporal_maintenance_dataset_v2_lib import visible


def score(ids, q, g, docs, chain, assets, k):
    ids = ids[:k]
    groups = g["required_evidence_groups"]
    required = {item for group in groups for item in group}
    hit = sum(bool(set(ids) & set(group)) for group in groups)
    canonical = lambda identifier: docs[identifier].get("origin_record_id", identifier)
    grades = {}
    for judgment in g["relevance_judgments"]:
        key = canonical(judgment["evidence_id"])
        grades[key] = max(grades.get(key, 0), judgment["grade"])
    seen = set()
    dcg = 0.0
    for rank, identifier in enumerate(ids, 1):
        key = canonical(identifier)
        grade = grades.get(key, 0) if key not in seen else 0
        dcg += (2**grade - 1) / math.log2(rank + 1)
        seen.add(key)
    ideal = sum(
        (2**grade - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(sorted(grades.values(), reverse=True)[:k], 1)
    )
    procedures = [identifier for identifier in ids if docs[identifier]["kind"] == "procedure"]
    necessary_proc = [
        group for group in groups
        if any(docs[identifier]["kind"] == "procedure" for identifier in group)
    ]

    def applicable(identifier):
        doc = docs[identifier]
        cutoff = q["query_time"]
        return (
            doc.get("model_scope") == assets[q["asset_id"]]["model_scope"]
            and doc.get("valid_from", "") <= cutoff
            and (not doc.get("valid_to") or cutoff < doc["valid_to"])
        )

    business = [identifier for identifier in ids if docs[identifier]["kind"] == "maintenance_record"]
    event = float(business[0] in chain["record_ids"]) if business and g["task"] == "temporal" else None
    return {
        "recall": hit / len(groups), "ndcg": dcg / ideal if ideal else 0,
        "mrr": next((1 / rank for rank, identifier in enumerate(ids, 1) if identifier in required), 0),
        "complete": float(hit == len(groups)),
        "future_rate": sum(not visible(docs[identifier], q["query_time"]) for identifier in ids) / len(ids) if ids else 0,
        "wrong_asset_rate": sum(docs[identifier]["asset_id"] != q["asset_id"] and identifier not in required for identifier in ids) / len(ids) if ids else 0,
        "event_match": event,
        "procedure_recall": sum(bool(set(ids) & set(group)) for group in necessary_proc) / len(necessary_proc) if necessary_proc else None,
        "procedure_valid_precision": sum(applicable(identifier) for identifier in procedures) / len(procedures) if procedures else None,
    }
