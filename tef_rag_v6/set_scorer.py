"""Deterministic full-set bank and deployment-visible Stage 3B features."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
import json
import math
from pathlib import Path


FORBIDDEN = ("gold", "required_", "allowed_", "query_id", "chain_id", "difficulty", "split")
BANK_VERSION = "stage3b-full5-top15-swap-v1"


def candidate_bank(pool_ids, node_scores, greedy_ids, raw_beam_ids=(), top_m=15, final_k=5):
    ranked = sorted(pool_ids, key=lambda x: (-node_scores[x]["total"], x))
    bank = {tuple(sorted(value)) for value in combinations(ranked[:top_m], final_k)}
    greedy = tuple(sorted(greedy_ids))
    if len(greedy) == final_k:
        bank.add(greedy)
        for old in greedy:
            for new in ranked:
                proposal = tuple(sorted((set(greedy) - {old}) | {new}))
                if len(proposal) == final_k:
                    bank.add(proposal)
    raw = tuple(sorted(raw_beam_ids))
    if len(raw) == final_k:
        bank.add(raw)
    return sorted(bank)


def _seconds(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def set_features(query, ids, by_id, node_scores, edges, role_demands, set_score, type_aware):
    documents = [by_id[x] for x in ids]
    chosen = set(ids)
    active = [e for e in edges if e["source_id"] in chosen and e["target_id"] in chosen]
    values = {}
    for field in ("total", "relevance", "recency", "role_compatibility"):
        numbers = [node_scores[x][field] for x in ids]
        for name, value in (("sum", sum(numbers)), ("mean", sum(numbers) / len(numbers)),
                            ("min", min(numbers)), ("max", max(numbers))):
            values[f"node_{field}_{name}"] = value
    for name in ("node_sum", "edge_sum", "role_coverage", "connectivity",
                 "uncertainty_consistency", "redundancy_penalty", "disconnected_penalty"):
        values[f"hand_{name}"] = float(set_score[name])
    event_types = [d.get("event_type", "") for d in documents]
    source_types = [d.get("source_type", "") for d in documents]
    for event in ("state_observation", "inspection", "diagnosis", "work_order", "repair",
                  "verification", "uncertainty", "correction", "procedure_applicability", "alarm"):
        values[f"event_count={event}"] = float(event_types.count(event))
    covered = set(event_types) & set(role_demands)
    values.update(query_demand_count=float(len(role_demands)), covered_role_count=float(len(covered)),
                  missing_demand_count=float(len(set(role_demands) - covered)),
                  role_coverage_ratio=len(covered) / max(len(role_demands), 1),
                  query_uncertainty=float("uncertainty" in role_demands),
                  set_uncertainty=float("uncertainty" in event_types))
    confidence_of = lambda e: float(e.get("confidence", e.get("score", 0.0)))
    confidences = [confidence_of(e) for e in active]
    connected = {e["source_id"] for e in active} | {e["target_id"] for e in active}
    indegree = {x: 0 for x in ids}; outdegree = {x: 0 for x in ids}
    adjacency = {x: [] for x in ids}; undirected = {x: set() for x in ids}
    for edge in active:
        s, t = edge["source_id"], edge["target_id"]
        outdegree[s] += 1; indegree[t] += 1; adjacency[s].append(t)
        undirected[s].add(t); undirected[t].add(s)
    values.update(active_edge_count=float(len(active)), edge_conf_sum=sum(confidences),
                  edge_conf_mean=sum(confidences) / max(len(confidences), 1),
                  edge_conf_max=max(confidences, default=0.0), edge_conf_min=min(confidences, default=0.0),
                  connected_node_count=float(len(connected)), disconnected_node_count=float(len(ids)-len(connected)),
                  edge_density=len(active) / max(len(ids)*(len(ids)-1), 1),
                  indegree_max=float(max(indegree.values())), outdegree_max=float(max(outdegree.values())),
                  indegree_mean=sum(indegree.values()) / len(ids), outdegree_mean=sum(outdegree.values()) / len(ids))
    if type_aware:
        relation_types = sorted({e["relation_type"] for e in edges})
        for relation in relation_types:
            selected = [confidence_of(e) for e in active if e["relation_type"] == relation]
            values[f"relation={relation}:count"] = float(len(selected))
            values[f"relation={relation}:conf_sum"] = sum(selected)
            values[f"relation={relation}:conf_max"] = max(selected, default=0.0)
    longest = {x: 1 for x in ids}
    ordered = sorted(ids, key=lambda x: (by_id[x]["event_time"], by_id[x]["available_at"], x))
    for source in ordered:
        for target in adjacency[source]:
            longest[target] = max(longest[target], longest[source] + 1)
    length2 = sum(len(adjacency[mid]) for source in ids for mid in adjacency[source])
    unseen, components = set(ids), []
    while unseen:
        stack = [min(unseen)]; component = set()
        while stack:
            node = stack.pop()
            if node in component: continue
            component.add(node); unseen.discard(node); stack.extend(undirected[node] - component)
        components.append(component)
    values.update(longest_directed_path=float(max(longest.values())), length2_path_count=float(length2),
                  weak_component_count=float(len(components)), largest_component_size=float(max(map(len, components))))
    event_times = sorted(_seconds(d["event_time"]) for d in documents)
    available = sorted(_seconds(d["available_at"]) for d in documents)
    values.update(event_span_days=(event_times[-1]-event_times[0])/86400,
                  available_span_days=(available[-1]-available[0])/86400,
                  mean_event_gap_days=sum(b-a for a,b in zip(event_times,event_times[1:]))/4/86400,
                  unique_event_types=float(len(set(event_types))), unique_source_types=float(len(set(source_types))))
    similarities = []
    for left, right in combinations(ids, 2):
        a, b = set(by_id[left].get("text", "").lower().split()), set(by_id[right].get("text", "").lower().split())
        similarities.append(len(a & b) / max(len(a | b), 1))
    values["pair_lexical_mean"] = sum(similarities) / len(similarities)
    values["pair_lexical_max"] = max(similarities)
    assert not any(fragment in key for key in values for fragment in FORBIDDEN)
    return values


@dataclass
class LinearSetScorer:
    feature_names: list[str]
    coefficients: list[float]
    intercept: float
    metadata: dict
    _weights: dict[str, float] = field(init=False, repr=False)

    def __post_init__(self): self._weights = dict(zip(self.feature_names, self.coefficients))
    def score(self, features):
        z = self.intercept + sum(self._weights.get(k, 0.0)*v for k,v in features.items())
        return 1/(1+math.exp(-max(-40,min(40,z))))
    def save(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"feature_names": self.feature_names, "coefficients": self.coefficients,
            "intercept": self.intercept, "metadata": self.metadata}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    @classmethod
    def load(cls, path):
        value=json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(value["feature_names"],value["coefficients"],value["intercept"],value["metadata"])
