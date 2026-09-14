"""Query-conditioned, set-level temporal evidence selection.

The selector keeps v4's neutral same-asset/bitemporal candidate scope and v3's
explicit prior-to-update relation semantics.  It does not read gold labels and
does not infer intent from task-specific query keywords.  A query-only evidence
profile is an explicit input to the set objective.
"""

from collections import defaultdict
import math
import re

from tef_rag_v1.retriever import RELATIONS
from tef_rag_v2.retriever import KNOWLEDGE_RELATIONS, PROCESS_RELATIONS, knowledge_time
from tef_rag_v4 import NeutralScopeEvidenceFlowRetrieverV4
from tmc_rag_v3.retriever import dt


SET_WEIGHTS = {
    "semantic": 0.45,
    "chain": 0.25,
    "role": 0.20,
    "redundancy": 0.10,
}
EDGE_RELEVANCE_FLOOR = 0.20
DEFAULT_BEAM_WIDTH = 64


def _clamp(value):
    return max(0.0, min(1.0, float(value)))


def _normalise_demands(values, *, allowed=None):
    if values is None:
        return {}
    if not isinstance(values, dict):
        raise ValueError("evidence-profile demands must be objects")
    cleaned = {}
    for key, value in values.items():
        name = str(key)
        if allowed is not None and name not in allowed:
            raise ValueError(f"unknown relation demand: {name}")
        number = float(value)
        if not math.isfinite(number) or number < 0.0:
            raise ValueError("evidence-profile demands must be finite and non-negative")
        if number:
            cleaned[name] = number
    total = sum(cleaned.values())
    if not total:
        return {}
    return {key: cleaned[key] / total for key in sorted(cleaned)}


def _query_profile(query, supplied):
    if supplied is not None:
        raw = supplied
        source = "argument"
    elif query.get("evidence_profile") is not None:
        raw = query["evidence_profile"]
        source = "query_metadata"
    else:
        raw = {
            "selection_mode": "set",
            "role_demands": {},
            "relation_demands": {kind: 1.0 for kind in sorted(RELATIONS)},
        }
        source = "neutral_default"
    if not isinstance(raw, dict):
        raise ValueError("query_profile must be an object")
    unknown = set(raw) - {"selection_mode", "role_demands", "relation_demands"}
    if unknown:
        raise ValueError(f"unknown query_profile fields: {sorted(unknown)}")
    mode = raw.get("selection_mode", "set")
    if mode not in ("set", "latest"):
        raise ValueError("selection_mode must be 'set' or 'latest'")
    return (
        {
            "selection_mode": mode,
            "role_demands": _normalise_demands(raw.get("role_demands")),
            "relation_demands": _normalise_demands(raw.get("relation_demands"), allowed=RELATIONS),
        },
        source,
    )


class QueryConditionedSetEvidenceRetrieverV5(NeutralScopeEvidenceFlowRetrieverV4):
    """Optimise the returned evidence set instead of greedily filling paths."""

    def __init__(self, records, assets, relations, roles=None, **kwargs):
        self.evidence_roles = dict(roles or {})
        kwargs.setdefault("beam_width", DEFAULT_BEAM_WIDTH)
        super().__init__(records, assets, relations, roles=roles, **kwargs)
        self._text_features = {
            identifier: self._lexical_features(record.get("text", ""))
            for identifier, record in self.by_id.items()
        }

    @staticmethod
    def _lexical_features(text):
        lowered = str(text).lower()
        features = {f"word:{word}" for word in re.findall(r"[a-z0-9]+", lowered)}
        han = "".join(re.findall(r"[\u3400-\u9fff]", lowered))
        if len(han) == 1:
            features.add("han:" + han)
        else:
            features.update("han2:" + han[index : index + 2] for index in range(len(han) - 1))
        return features

    def _role_affinities(self, identifier):
        raw = self.evidence_roles.get(identifier, {})
        if isinstance(raw, str):
            return {raw: 1.0}
        if not isinstance(raw, dict):
            return {}
        if isinstance(raw.get("role_scores"), dict):
            return {
                str(role): _clamp(score)
                for role, score in raw["role_scores"].items()
                if _clamp(score) > 0.0
            }
        if isinstance(raw.get("roles"), list):
            return {str(role): 1.0 for role in raw["roles"]}
        if raw.get("role"):
            return {str(raw["role"]): _clamp(raw.get("confidence", 1.0))}
        return {}

    @staticmethod
    def _clock(kind):
        if kind in PROCESS_RELATIONS:
            return "event_time"
        if kind in KNOWLEDGE_RELATIONS:
            return "available_at"
        return None

    def _admissible_edges_v5(self, candidates, relation_scores):
        candidate_ids = {record["id"] for record in candidates}
        admitted = []
        rejected = []
        for relation in self.relations:
            prior = relation.get("prior_id") or relation.get("source_id")
            update = relation.get("update_id") or relation.get("target_id")
            kind = relation.get("update_relation") or relation.get("relation")
            if prior not in candidate_ids or update not in candidate_ids or prior == update:
                continue
            common = {
                "source_id": prior,
                "target_id": update,
                "prior_id": prior,
                "update_id": update,
                "relation": kind,
                "update_relation": kind,
            }
            if kind not in RELATIONS:
                rejected.append({**common, "reason": "unknown_relation"})
                continue
            clock = self._clock(kind)
            if kind in PROCESS_RELATIONS and dt(self.by_id[prior]["event_time"]) > dt(self.by_id[update]["event_time"]):
                rejected.append({**common, "clock": clock, "reason": "backward_event_time"})
                continue
            if kind in KNOWLEDGE_RELATIONS and knowledge_time(self.by_id[prior]) > knowledge_time(self.by_id[update]):
                rejected.append({**common, "clock": clock, "reason": "backward_knowledge_time"})
                continue
            admitted.append(
                {
                    **common,
                    "clock": clock,
                    "confidence": _clamp(self._external_edge_score(relation, relation_scores)),
                }
            )
        admitted.sort(key=lambda edge: (edge["prior_id"], edge["update_id"], edge["update_relation"]))
        rejected.sort(
            key=lambda edge: (
                edge.get("prior_id", ""),
                edge.get("update_id", ""),
                edge.get("update_relation") or "",
                edge["reason"],
            )
        )
        return admitted, rejected

    def _pair_redundancy(self, left, right, supplied):
        if supplied:
            keys = (
                (left, right),
                (right, left),
                left + "<->" + right,
                right + "<->" + left,
                left + "->" + right,
                right + "->" + left,
            )
            for key in keys:
                if key in supplied:
                    return _clamp(supplied[key])
        left_features = self._text_features[left]
        right_features = self._text_features[right]
        union = left_features | right_features
        return len(left_features & right_features) / len(union) if union else 0.0

    def _raw_components(self, selected, node_scores, edges, profile, redundancy_scores):
        identifiers = frozenset(selected)
        semantic = sum(node_scores[identifier] for identifier in identifiers) / max(self.top_k, 1)

        role = 0.0
        for demanded_role, demand in profile["role_demands"].items():
            uncovered = 1.0
            for identifier in identifiers:
                uncovered *= 1.0 - self._role_affinities(identifier).get(demanded_role, 0.0)
            role += demand * (1.0 - uncovered)

        by_relation = defaultdict(float)
        for edge in edges:
            if edge["prior_id"] not in identifiers or edge["update_id"] not in identifiers:
                continue
            prior_gate = EDGE_RELEVANCE_FLOOR + (1.0 - EDGE_RELEVANCE_FLOOR) * node_scores[edge["prior_id"]]
            update_gate = EDGE_RELEVANCE_FLOOR + (1.0 - EDGE_RELEVANCE_FLOOR) * node_scores[edge["update_id"]]
            endpoint_gate = math.sqrt(prior_gate * update_gate)
            by_relation[edge["update_relation"]] += edge["confidence"] * endpoint_gate
        chain = sum(
            demand * (1.0 - math.exp(-by_relation.get(kind, 0.0)))
            for kind, demand in profile["relation_demands"].items()
        )

        redundancy_sum = 0.0
        ordered = sorted(identifiers)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                redundancy_sum += self._pair_redundancy(left, right, redundancy_scores)
        maximum_pairs = max(self.top_k * (self.top_k - 1) / 2.0, 1.0)
        redundancy = redundancy_sum / maximum_pairs
        return {
            "semantic": semantic,
            "chain": chain,
            "role": role,
            "redundancy": redundancy,
        }

    @staticmethod
    def _weighted_components(raw):
        components = {
            "semantic": SET_WEIGHTS["semantic"] * raw["semantic"],
            "chain": SET_WEIGHTS["chain"] * raw["chain"],
            "role": SET_WEIGHTS["role"] * raw["role"],
            "redundancy": -SET_WEIGHTS["redundancy"] * raw["redundancy"],
        }
        components["total"] = sum(components.values())
        return components

    @staticmethod
    def _state_better(candidate, incumbent):
        if candidate["prefix_scores"] != incumbent["prefix_scores"]:
            return candidate["prefix_scores"] > incumbent["prefix_scores"]
        return candidate["sequence"] < incumbent["sequence"]

    def _search(self, candidates, evaluate):
        ordered_ids = sorted(record["id"] for record in candidates)
        states = [
            {
                "sequence": tuple(),
                "used": 0,
                "score": 0.0,
                "prefix_scores": tuple(),
            }
        ]
        deepest = states
        for _ in range(min(self.top_k, len(ordered_ids))):
            unique = {}
            for state in states:
                present = frozenset(state["sequence"])
                for identifier in ordered_ids:
                    if identifier in present:
                        continue
                    new_used = state["used"] + len(self.by_id[identifier].get("text", ""))
                    if new_used > self.budget:
                        continue
                    sequence = state["sequence"] + (identifier,)
                    score = evaluate(sequence)["total"]
                    candidate = {
                        "sequence": sequence,
                        "used": new_used,
                        "score": score,
                        "prefix_scores": state["prefix_scores"] + (score,),
                    }
                    key = frozenset(sequence)
                    if key not in unique or self._state_better(candidate, unique[key]):
                        unique[key] = candidate
            if not unique:
                break
            states = sorted(
                unique.values(),
                key=lambda state: (
                    -state["score"],
                    tuple(-score for score in state["prefix_scores"]),
                    state["sequence"],
                ),
            )[: self.beam_width]
            deepest = states
        return sorted(
            deepest,
            key=lambda state: (
                -state["score"],
                tuple(-score for score in state["prefix_scores"]),
                state["sequence"],
            ),
        )[0]

    def _serialise_edge(self, edge, node_scores, relation_demands):
        prior_gate = EDGE_RELEVANCE_FLOOR + (1.0 - EDGE_RELEVANCE_FLOOR) * node_scores[edge["prior_id"]]
        update_gate = EDGE_RELEVANCE_FLOOR + (1.0 - EDGE_RELEVANCE_FLOOR) * node_scores[edge["update_id"]]
        endpoint_gate = math.sqrt(prior_gate * update_gate)
        query_demand = relation_demands.get(edge["update_relation"], 0.0)
        return {
            **edge,
            "endpoint_relevance_gate": endpoint_gate,
            "query_demand": query_demand,
            "effective_edge_utility": edge["confidence"] * endpoint_gate * query_demand,
        }

    def _trace(self, sequence, evaluate, edges, node_scores, profile):
        trace = []
        before = self._weighted_components({"semantic": 0.0, "chain": 0.0, "role": 0.0, "redundancy": 0.0})
        prefix = []
        for rank, identifier in enumerate(sequence, start=1):
            prefix.append(identifier)
            after = evaluate(tuple(prefix))
            activated = [
                self._serialise_edge(edge, node_scores, profile["relation_demands"])
                for edge in edges
                if identifier in (edge["prior_id"], edge["update_id"])
                and edge["prior_id"] in prefix
                and edge["update_id"] in prefix
            ]
            trace.append(
                {
                    "rank": rank,
                    "selected_id": identifier,
                    "set_after": list(prefix),
                    "marginal_components": {
                        key: after[key] - before[key]
                        for key in ("semantic", "chain", "role", "redundancy", "total")
                    },
                    "set_score_after": after["total"],
                    "activated_relations": activated,
                }
            )
            before = after
        return trace

    def _latest_result(self, query, parsed, candidates, profile, profile_source):
        selected = []
        trace = []
        used = 0
        for record in sorted(candidates, key=lambda item: (-dt(item["event_time"]).timestamp(), item["id"])):
            if len(selected) >= self.top_k:
                break
            size = len(record.get("text", ""))
            if used + size > self.budget:
                continue
            selected.append(record["id"])
            used += size
            trace.append(
                {
                    "rank": len(selected),
                    "selected_id": record["id"],
                    "set_after": list(selected),
                    "reason": "query_profile_latest_recency",
                    "activated_relations": [],
                }
            )
        return {
            "evidence_ids": selected,
            "trace": trace,
            "query_scope": parsed,
            "query_profile": profile,
            "profile_source": profile_source,
            "candidate_count": len(candidates),
            "candidate_policy": "same_asset_and_event_available_by_query_time",
            "status": "ok" if candidates else "no_visible_match",
            "objective": "latest",
            "selector": "query_profile_recency_control_v5",
            "selected_edges": [],
            "rejected_edges": [],
            "characters": used,
            "relation_schema": "prior_update_v3",
        }

    def retrieve(
        self,
        query,
        relevance,
        relation_scores=None,
        query_profile=None,
        redundancy_scores=None,
    ):
        profile, profile_source = _query_profile(query, query_profile)
        parsed, candidates = self.base.scope(query)
        if profile["selection_mode"] == "latest":
            return self._latest_result(query, parsed, candidates, profile, profile_source)

        if not candidates:
            zero = self._weighted_components(
                {"semantic": 0.0, "chain": 0.0, "role": 0.0, "redundancy": 0.0}
            )
            return {
                "evidence_ids": [],
                "trace": [],
                "query_scope": parsed,
                "query_profile": profile,
                "profile_source": profile_source,
                "candidate_count": 0,
                "candidate_policy": "same_asset_and_event_available_by_query_time",
                "status": "no_visible_match",
                "objective": "query_conditioned_set",
                "selector": "query_conditioned_set_beam_v5",
                "selected_edges": [],
                "rejected_edges": [],
                "characters": 0,
                "score_components": zero,
                "raw_score_components": {key: 0.0 for key in ("semantic", "chain", "role", "redundancy")},
                "relation_schema": "prior_update_v3",
                "edge_clock_policy": {"process": "event_time", "knowledge_update": "available_at"},
            }

        node_scores = self._normalise_relevance(candidates, relevance)
        edges, rejected = self._admissible_edges_v5(candidates, relation_scores)
        cache = {}

        def evaluate(sequence):
            key = frozenset(sequence)
            if key not in cache:
                raw = self._raw_components(
                    key,
                    node_scores,
                    edges,
                    profile,
                    redundancy_scores,
                )
                cache[key] = {
                    **self._weighted_components(raw),
                    "raw": raw,
                }
            return cache[key]

        best = self._search(candidates, evaluate)
        sequence = list(best["sequence"])
        final = evaluate(tuple(sequence))
        selected_set = frozenset(sequence)
        selected_edges = [
            self._serialise_edge(edge, node_scores, profile["relation_demands"])
            for edge in edges
            if edge["prior_id"] in selected_set and edge["update_id"] in selected_set
        ]
        return {
            "evidence_ids": sequence,
            "trace": self._trace(sequence, evaluate, edges, node_scores, profile),
            "query_scope": parsed,
            "query_profile": profile,
            "profile_source": profile_source,
            "candidate_count": len(candidates),
            "candidate_policy": "same_asset_and_event_available_by_query_time",
            "status": "ok",
            "objective": "query_conditioned_set",
            "selector": "query_conditioned_set_beam_v5",
            "selected_edges": selected_edges,
            "rejected_edges": rejected,
            "characters": best["used"],
            "score_components": {
                key: final[key]
                for key in ("semantic", "chain", "role", "redundancy", "total")
            },
            "raw_score_components": final["raw"],
            "set_weights": dict(SET_WEIGHTS),
            "edge_relevance_floor": EDGE_RELEVANCE_FLOOR,
            "relation_schema": "prior_update_v3",
            "relation_semantics": "update_relation describes update_id relative to prior_id; traversal is prior-to-update",
            "edge_clock_policy": {"process": "event_time", "knowledge_update": "available_at"},
        }
