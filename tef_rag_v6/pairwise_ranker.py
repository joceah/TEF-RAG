"""Same-query linear pairwise ranking utilities for TEF-RAG v6 Stage 3C."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path


def deterministic_subsample(items, limit):
    """Keep an ordered, evenly spaced deterministic subset."""
    values = sorted(items, key=lambda item: item["ids"])
    if len(values) <= limit:
        return values
    if limit == 1:
        return [values[0]]
    indices = [(index * (len(values) - 1)) // (limit - 1) for index in range(limit)]
    return [values[index] for index in indices]


def select_round0_negatives(negatives, hard_limit=30, diverse_limit=10):
    hard = sorted(negatives, key=lambda item: (-item["hand_score"], item["ids"]))[:hard_limit]
    diverse = deterministic_subsample(negatives, diverse_limit)
    return list({item["ids"]: item for item in hard + diverse}.values())


def select_mined_negatives(negatives, scorer, type_aware, model_limit=20, hand_limit=10):
    ranked = sorted(
        negatives,
        key=lambda item: (-scorer.utility(item["aware" if type_aware else "agnostic"]), item["ids"]),
    )
    handcrafted = sorted(negatives, key=lambda item: (-item["hand_score"], item["ids"]))[:hand_limit]
    return list({item["ids"]: item for item in ranked[:model_limit] + handcrafted}.values())


def construct_pairs(query_id, positives, negatives, feature_key, max_negatives_per_positive=5,
                    max_pairs=150):
    """Return capped feature differences; all inputs must belong to one query."""
    if any(item["query_id"] != query_id for item in positives + negatives):
        raise ValueError("pairwise examples must be same-query")
    pairs = []
    negatives = sorted(negatives, key=lambda item: (-item["hardness"], item["ids"]))
    for positive_index, positive in enumerate(positives):
        if not negatives:
            break
        count = min(max_negatives_per_positive, len(negatives))
        for offset in range(count):
            negative = negatives[(positive_index + offset) % len(negatives)]
            keys = set(positive[feature_key]) | set(negative[feature_key])
            delta = {key: positive[feature_key].get(key, 0.0) - negative[feature_key].get(key, 0.0)
                     for key in keys}
            pairs.append({"query_id": query_id, "positive_ids": positive["ids"],
                          "negative_ids": negative["ids"], "delta": delta})
            if len(pairs) >= max_pairs:
                return pairs
    return pairs


def mirrored_examples(pairs):
    rows, labels = [], []
    for pair in pairs:
        rows.extend((pair["delta"], {key: -value for key, value in pair["delta"].items()}))
        labels.extend((1, 0))
    return rows, labels


@dataclass
class LinearPairwiseSetRanker:
    feature_names: list[str]
    coefficients: list[float]
    metadata: dict
    _weights: dict[str, float] = field(init=False, repr=False)

    def __post_init__(self):
        self._weights = dict(zip(self.feature_names, self.coefficients))

    def utility(self, features):
        return sum(self._weights.get(key, 0.0) * value for key, value in features.items())

    def save(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"feature_names": self.feature_names,
            "coefficients": self.coefficients, "intercept": 0.0, "metadata": self.metadata},
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path):
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if value.get("intercept", 0.0) != 0.0:
            raise ValueError("pairwise ranker must have zero intercept")
        return cls(value["feature_names"], value["coefficients"], value["metadata"])


def rank_items(items, scorer, feature_key):
    return sorted(items, key=lambda item: (-scorer.utility(item[feature_key]), item["ids"]))
