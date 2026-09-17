"""Deployment-visible query-conditioned pair features and deterministic ranker."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import math
from pathlib import Path

from .pipeline import tokenize


FEATURE_SCHEMA_VERSION = "stage3a-pair-features-v1"
FORBIDDEN_FEATURE_FRAGMENTS = ("chain_id", "query_id", "gold", "required_", "difficulty", "split")


def _jaccard(left: str, right: str) -> float:
    a, b = set(tokenize(left)), set(tokenize(right))
    return len(a & b) / max(len(a | b), 1)


def _days(left: str, right: str) -> float:
    a = datetime.fromisoformat(left.replace("Z", "+00:00"))
    b = datetime.fromisoformat(right.replace("Z", "+00:00"))
    return max(0.0, (b - a).total_seconds() / 86400.0)


def pair_features(query: dict, source: dict, target: dict,
                  node_scores: dict[str, dict], role_demands: set[str]) -> dict[str, float]:
    sid, tid = source["evidence_id"], target["evidence_id"]
    query_text = query["query_text"]
    source_event, target_event = source.get("event_type", ""), target.get("event_type", "")
    source_type, target_type = source.get("source_type", ""), target.get("source_type", "")
    values = {
        "bias": 1.0,
        "q_source_jaccard": _jaccard(query_text, source.get("text", "")),
        "q_target_jaccard": _jaccard(query_text, target.get("text", "")),
        "pair_jaccard": _jaccard(source.get("text", ""), target.get("text", "")),
        "source_node_total": node_scores[sid]["total"],
        "target_node_total": node_scores[tid]["total"],
        "source_relevance": node_scores[sid]["relevance"],
        "target_relevance": node_scores[tid]["relevance"],
        "source_recency": node_scores[sid]["recency"],
        "target_recency": node_scores[tid]["recency"],
        "source_role_compatibility": node_scores[sid]["role_compatibility"],
        "target_role_compatibility": node_scores[tid]["role_compatibility"],
        "event_gap_log_days": math.log1p(_days(source["event_time"], target["event_time"])),
        "available_gap_log_days": math.log1p(_days(source["available_at"], target["available_at"])),
        "same_source_type": float(source_type == target_type),
        "explicit_supersession": float(target.get("supersedes") == sid),
        "source_procedure": float(source_event == "procedure_applicability" or source_type == "procedure"),
        "target_procedure": float(target_event == "procedure_applicability" or target_type == "procedure"),
        "source_uncertainty": float(source_event == "uncertainty"),
        "target_uncertainty": float(target_event == "uncertainty"),
        "source_correction": float(source_event == "correction"),
        "target_correction": float(target_event == "correction"),
        "source_verification": float(source_event == "verification"),
        "target_verification": float(target_event == "verification"),
        f"source_event={source_event}": 1.0,
        f"target_event={target_event}": 1.0,
        f"transition={source_event}->{target_event}": 1.0,
        f"source_type={source_type}": 1.0,
        f"target_type={target_type}": 1.0,
    }
    for role in sorted(role_demands):
        values[f"query_role={role}"] = 1.0
    assert not any(fragment in key for key in values for fragment in FORBIDDEN_FEATURE_FRAGMENTS)
    return values


def chronological_pairs(candidates: list[dict]):
    documents = [item["document"] for item in candidates]
    clock = lambda d: (d["event_time"], d["available_at"], d["evidence_id"])
    return [(source, target) for source in documents for target in documents if clock(source) < clock(target)]


@dataclass
class LinearPairProposer:
    feature_names: list[str]
    coefficients: list[float]
    intercept: float
    metadata: dict
    _weights: dict[str, float] = field(init=False, repr=False)

    def __post_init__(self):
        self._weights = dict(zip(self.feature_names, self.coefficients))

    @classmethod
    def load(cls, path: str | Path):
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(value["feature_names"], value["coefficients"], value["intercept"], value["metadata"])

    def save(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"feature_names": self.feature_names,
            "coefficients": self.coefficients, "intercept": self.intercept,
            "metadata": self.metadata}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def score_features(self, features: dict[str, float]) -> float:
        logit = self.intercept + sum(self._weights.get(key, 0.0) * value for key, value in features.items())
        return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, logit))))

    def rank(self, query, candidates, node_scores, role_demands, budget, mode="learned"):
        ranked = []
        for source, target in chronological_pairs(candidates):
            score = self.score_features(pair_features(query, source, target, node_scores, role_demands))
            protected = target.get("supersedes") == source["evidence_id"] or (
                (source.get("event_type") == "procedure_applicability" or source.get("source_type") == "procedure")
                and target.get("event_type") in {"diagnosis", "work_order", "repair", "verification"})
            ranked.append({"source": source, "target": target, "proposal_score": score,
                           "priority": score, "explicit_supersession": target.get("supersedes") == source["evidence_id"],
                           "protected": protected, "same_chain": False,
                           "same_episode": source.get("episode_id") == target.get("episode_id"),
                           "heuristic_confidence": 0.0, "heuristic_type": "supports"})
        key = lambda p: (-p["proposal_score"], p["source"]["evidence_id"], p["target"]["evidence_id"])
        if mode == "learned":
            return sorted(ranked, key=key)[:budget]
        if mode != "hybrid":
            raise ValueError("proposal mode must be learned or hybrid")
        protected = sorted((p for p in ranked if p["protected"]), key=key)
        protected_keys = {(p["source"]["evidence_id"], p["target"]["evidence_id"]) for p in protected[:budget]}
        rest = [p for p in sorted(ranked, key=key)
                if (p["source"]["evidence_id"], p["target"]["evidence_id"]) not in protected_keys]
        return (protected[:budget] + rest)[:budget]
