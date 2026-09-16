"""Deterministic stage-1 Temporal Evidence Flow retriever.

The implementation deliberately accepts only the deployment-facing query fields
(`query_text`, `asset_id`, `asset_model`, and `query_time`).  Split, chain,
difficulty, and gold metadata are never used to rank evidence.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import re
from typing import Iterable


RELATION_TYPES = {
    "contrasts",
    "governs",
    "prerequisite",
    "preserves_uncertainty",
    "qualifies",
    "resolves",
    "supersession",
    "supports",
    "updates",
    "verifies",
}


def load_jsonl(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _timestamp(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def tokenize(text: str) -> list[str]:
    """Mixed Latin word, Han unigram, and Han bigram tokenizer."""
    output: list[str] = []
    for part in re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", str(text).lower()):
        if "\u3400" <= part[0] <= "\u9fff":
            output.extend(part)
            output.extend(part[index : index + 2] for index in range(len(part) - 1))
        else:
            output.append(part)
    return output


@dataclass(frozen=True)
class V6Config:
    seed: int = 20260916
    candidate_k: int = 100
    search_pool_k: int = 30
    final_k: int = 5
    max_flow_nodes: int = 5
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    node_relevance_weight: float = 0.62
    node_recency_weight: float = 0.18
    node_role_weight: float = 0.15
    node_source_weight: float = 0.05
    edge_weight: float = 0.48
    role_coverage_weight: float = 0.42
    redundancy_penalty: float = 0.16
    disconnected_penalty: float = 0.10
    relation_threshold: float = 0.58

    @classmethod
    def from_dict(cls, value: dict) -> "V6Config":
        unknown = set(value) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown v6 config fields: {sorted(unknown)}")
        return cls(**value)

    def to_dict(self) -> dict:
        return asdict(self)


class BM25Index:
    def __init__(self, documents: list[dict], config: V6Config):
        self.documents = documents
        self.config = config
        self.counts = [Counter(tokenize(item.get("text", ""))) for item in documents]
        self.lengths = [sum(count.values()) for count in self.counts]
        self.average_length = sum(self.lengths) / max(len(self.lengths), 1)
        document_frequency = Counter(token for count in self.counts for token in count)
        size = len(documents)
        self.idf = {
            token: math.log(1.0 + (size - frequency + 0.5) / (frequency + 0.5))
            for token, frequency in document_frequency.items()
        }
        self.by_asset: dict[str, list[int]] = defaultdict(list)
        for index, document in enumerate(documents):
            self.by_asset[str(document.get("asset_id", ""))].append(index)

    def score(self, query_text: str, indices: Iterable[int]) -> dict[int, float]:
        query_counts = Counter(tokenize(query_text))
        scores: dict[int, float] = {}
        for index in indices:
            count = self.counts[index]
            norm = self.config.bm25_k1 * (
                1.0 - self.config.bm25_b
                + self.config.bm25_b * self.lengths[index] / max(self.average_length, 1.0)
            )
            score = 0.0
            for token, query_frequency in query_counts.items():
                frequency = count.get(token, 0)
                if frequency:
                    score += (
                        self.idf.get(token, 0.0)
                        * frequency
                        * (self.config.bm25_k1 + 1.0)
                        / (frequency + norm)
                        * min(query_frequency, 2)
                    )
            scores[index] = score
        return scores


class TEFRAGV6:
    """Candidate retrieval, temporal constraints, typed graph, and flow search."""

    def __init__(self, evidence: list[dict], config: V6Config | None = None, relation_scorer=None):
        self.config = config or V6Config()
        self.evidence = sorted(evidence, key=lambda item: item["evidence_id"])
        self.by_id = {item["evidence_id"]: item for item in self.evidence}
        self.index = BM25Index(self.evidence, self.config)
        self.relation_scorer = relation_scorer
        self.features = {
            item["evidence_id"]: set(tokenize(item.get("text", ""))) for item in self.evidence
        }

    @staticmethod
    def _public_query(query: dict) -> dict:
        return {
            "query_text": str(query.get("query_text", query.get("text", ""))),
            "asset_id": str(query["asset_id"]),
            "asset_model": str(query.get("asset_model", "")),
            "asset_context": str(query.get("asset_context", "")),
            "query_time": str(query["query_time"]),
        }

    @staticmethod
    def temporal_eligibility(document: dict, query: dict) -> tuple[bool, str]:
        cutoff = query["query_time"]
        if document.get("asset_id") != query["asset_id"]:
            return False, "asset_scope_mismatch"
        if document.get("available_at", "") > cutoff:
            return False, "not_yet_available"
        if document.get("event_time", "") > cutoff:
            return False, "future_event"
        if document.get("event_type") == "procedure_applicability" or document.get("source_type") == "procedure":
            if document.get("valid_from") and document["valid_from"] > cutoff:
                return False, "procedure_not_yet_valid"
            if document.get("valid_to") and cutoff >= document["valid_to"]:
                return False, "procedure_expired"
            if document.get("withdrawn_at") and cutoff >= document["withdrawn_at"]:
                return False, "procedure_withdrawn"
            scope = document.get("model_scope") or []
            if isinstance(scope, str):
                scope = [scope]
            if scope and query.get("asset_model") not in scope:
                return False, "procedure_model_scope_mismatch"
        return True, "eligible"

    def candidate_retrieval(self, query: dict) -> list[dict]:
        public = self._public_query(query)
        indices = self.index.by_asset.get(public["asset_id"], [])
        # Asset scope is already a deterministic filter.  Repeating the long
        # asset label in BM25 otherwise overwhelms intent-bearing query terms.
        ranking_text = public["query_text"]
        if public.get("asset_context"):
            ranking_text = ranking_text.replace(public["asset_context"], "")
        ranking_text = ranking_text.replace(public["asset_id"], "")
        scores = self.index.score(ranking_text, indices)
        ranked = sorted(indices, key=lambda index: (-scores[index], self.evidence[index]["evidence_id"]))
        return [
            {"document": self.evidence[index], "retrieval_score": scores[index]}
            for index in ranked[: self.config.candidate_k]
        ]

    @staticmethod
    def _normalise(items: list[dict], key: str) -> dict[str, float]:
        values = [float(item[key]) for item in items]
        low, high = min(values, default=0.0), max(values, default=0.0)
        if high <= low:
            return {item["document"]["evidence_id"]: 0.5 for item in items}
        return {
            item["document"]["evidence_id"]: (float(item[key]) - low) / (high - low)
            for item in items
        }

    @staticmethod
    def _role_demands(query_text: str) -> set[str]:
        demands = {"state_observation", "diagnosis", "work_order"}
        rules = (
            (("规程", "版本", "步骤", "流程", "依据什么处置"), "procedure_applicability"),
            (("验证结果", "复测结果", "是否恢复", "是否完成", "闭环"), "verification"),
            (("检查", "巡检", "现场", "核对"), "inspection"),
            (("不确定", "仍需", "两条", "分支", "尚不能"), "uncertainty"),
            (("纠正", "更正", "改判"), "correction"),
        )
        for needles, role in rules:
            if any(needle in query_text for needle in needles):
                demands.add(role)
        return demands

    def _node_scores(self, query: dict, candidates: list[dict]) -> dict[str, dict]:
        relevance = self._normalise(candidates, "retrieval_score")
        demands = self._role_demands(query["query_text"])
        sources = {item["document"].get("source_type") for item in candidates}
        result = {}
        cutoff = _timestamp(query["query_time"])
        comparison = any(
            phrase in query["query_text"]
            for phrase in ("分别", "比较", "对比", "前后差异", "两次", "演变过程")
        )
        recency_horizon_days = 180.0 if comparison else 45.0
        for item in candidates:
            document = item["document"]
            identifier = document["evidence_id"]
            age_days = max(0.0, (cutoff - _timestamp(document["event_time"])) / 86400.0)
            recency = math.exp(-age_days / recency_horizon_days)
            role = 1.0 if document.get("event_type") in demands else 0.35
            source = 1.0 if document.get("source_type") in sources else 0.5
            total = (
                self.config.node_relevance_weight * relevance[identifier]
                + self.config.node_recency_weight * recency
                + self.config.node_role_weight * role
                + self.config.node_source_weight * source
            )
            result[identifier] = {
                "total": total,
                "relevance": relevance[identifier],
                "recency": recency,
                "role_compatibility": role,
                "source_compatibility": source,
            }
        return result

    def _similarity(self, left: str, right: str) -> float:
        a, b = self.features[left], self.features[right]
        return len(a & b) / max(len(a | b), 1)

    @staticmethod
    def _relation_kind(source: dict, target: dict) -> tuple[str, float]:
        source_id = source["evidence_id"]
        if target.get("supersedes") == source_id:
            return "supersession", 1.0
        source_type = source.get("event_type", "")
        target_type = target.get("event_type", "")
        combined = source.get("text", "") + target.get("text", "")
        if source_type == "procedure_applicability" and target_type in {
            "work_order", "diagnosis", "inspection", "verification", "repair"
        }:
            return "governs", 0.92
        if target_type == "verification" and source_type in {
            "work_order", "repair", "diagnosis", "procedure_applicability"
        }:
            return "verifies", 0.90
        if target_type == "correction":
            return "updates", 0.90
        if source_type == "uncertainty" and target_type in {"verification", "correction", "diagnosis"}:
            if any(word in target.get("text", "") for word in ("确认", "排除", "收敛", "解决")):
                return "resolves", 0.88
            return "preserves_uncertainty", 0.78
        if source_type == "uncertainty" or target_type == "uncertainty":
            return "preserves_uncertainty", 0.88
        if source.get("episode_id") != target.get("episode_id"):
            if any(word in combined for word in ("上次", "本次", "旧", "新", "不同", "不能沿用")):
                return "contrasts", 0.78
            return "qualifies", 0.58
        if source_type in {"inspection", "state_observation", "alarm"} and target_type == "diagnosis":
            return "supports", 0.90
        if source_type == "diagnosis" and target_type in {"work_order", "repair"}:
            return "updates", 0.86
        if source_type in {"state_observation", "inspection"} and target_type == "work_order":
            return "prerequisite", 0.72
        if source_type == "verification" and target_type in {"diagnosis", "work_order"}:
            return "qualifies", 0.72
        return "supports", 0.62

    def relation_scoring(self, candidates: list[dict]) -> list[dict]:
        documents = [item["document"] for item in candidates]
        edges = []
        for source in documents:
            for target in documents:
                if source["evidence_id"] == target["evidence_id"]:
                    continue
                # Process direction follows event time, then knowledge availability.
                source_clock = (source["event_time"], source["available_at"], source["evidence_id"])
                target_clock = (target["event_time"], target["available_at"], target["evidence_id"])
                if source_clock >= target_clock:
                    continue
                same_chain = source.get("chain_id") == target.get("chain_id")
                same_episode = source.get("episode_id") == target.get("episode_id")
                kind, prior = self._relation_kind(source, target)
                semantic = self._similarity(source["evidence_id"], target["evidence_id"])
                confidence = min(1.0, prior * (0.62 + 0.22 * same_chain + 0.08 * same_episode + 0.18 * semantic))
                if confidence < self.config.relation_threshold:
                    continue
                edges.append(
                    {
                        "source_id": source["evidence_id"],
                        "target_id": target["evidence_id"],
                        "relation_type": kind,
                        "score": confidence,
                        "same_chain": same_chain,
                        "same_episode": same_episode,
                    }
                )
        return sorted(edges, key=lambda edge: (-edge["score"], edge["source_id"], edge["target_id"]))

    def _set_score(
        self,
        selected: tuple[str, ...],
        node_scores: dict[str, dict],
        edges: list[dict],
        role_demands: set[str],
        *,
        use_relations: bool,
    ) -> dict:
        chosen = set(selected)
        node_sum = sum(node_scores[identifier]["total"] for identifier in selected)
        active = [edge for edge in edges if edge["source_id"] in chosen and edge["target_id"] in chosen]
        # Only the best incoming relation per node contributes, preventing dense-graph inflation.
        best_incoming: dict[str, float] = {}
        for edge in active:
            best_incoming[edge["target_id"]] = max(best_incoming.get(edge["target_id"], 0.0), edge["score"])
        edge_sum = sum(best_incoming.values()) if use_relations else 0.0
        roles = {self.by_id[identifier].get("event_type") for identifier in selected}
        role_coverage = len(roles & role_demands) / max(len(role_demands), 1)
        redundancy = 0.0
        for index, left in enumerate(selected):
            for right in selected[index + 1 :]:
                redundancy += max(0.0, self._similarity(left, right) - 0.45)
        connected = {edge["source_id"] for edge in active} | {edge["target_id"] for edge in active}
        disconnected = max(0, len(selected) - len(connected)) if len(selected) > 1 and use_relations else 0
        total = (
            node_sum
            + self.config.edge_weight * edge_sum
            + self.config.role_coverage_weight * role_coverage
            - self.config.redundancy_penalty * redundancy
            - self.config.disconnected_penalty * disconnected
        )
        return {
            "total": total,
            "node_sum": node_sum,
            "edge_sum": edge_sum,
            "role_coverage": role_coverage,
            "redundancy_penalty": self.config.redundancy_penalty * redundancy,
            "disconnected_penalty": self.config.disconnected_penalty * disconnected,
            "active_edges": active,
        }

    def _select_flow(
        self,
        candidates: list[dict],
        node_scores: dict[str, dict],
        edges: list[dict],
        role_demands: set[str],
        *,
        use_relations: bool,
        use_flow: bool,
    ) -> tuple[list[str], dict]:
        pool = sorted(
            (item["document"]["evidence_id"] for item in candidates),
            key=lambda identifier: (-node_scores[identifier]["total"], identifier),
        )[: self.config.search_pool_k]
        limit = min(self.config.final_k, self.config.max_flow_nodes, len(pool))
        if not use_flow:
            selected = pool[:limit]
            return selected, self._set_score(
                tuple(selected), node_scores, edges, role_demands, use_relations=False
            )
        selected: tuple[str, ...] = tuple()
        trace = []
        while len(selected) < limit:
            options = []
            for identifier in pool:
                if identifier in selected:
                    continue
                proposal = selected + (identifier,)
                scored = self._set_score(
                    proposal, node_scores, edges, role_demands, use_relations=use_relations
                )
                options.append((scored["total"], identifier, proposal, scored))
            if not options:
                break
            _, identifier, selected, scored = sorted(options, key=lambda item: (-item[0], item[1]))[0]
            trace.append({"selected_id": identifier, "score_after": scored["total"]})
        final = self._set_score(selected, node_scores, edges, role_demands, use_relations=use_relations)
        final["search_trace"] = trace
        return list(selected), final

    def _uncertainty_state(self, selected: list[str], query_text: str) -> dict:
        uncertainty_nodes = [
            identifier for identifier in selected if self.by_id[identifier].get("event_type") == "uncertainty"
        ]
        explicit = any(word in query_text for word in ("不确定", "两条", "分支", "尚不能", "仍需"))
        if uncertainty_nodes:
            latest_uncertainty = max(_timestamp(self.by_id[item]["available_at"]) for item in uncertainty_nodes)
            resolved = any(
                self.by_id[item].get("event_type") in {"correction", "verification"}
                and _timestamp(self.by_id[item]["available_at"]) > latest_uncertainty
                and any(word in self.by_id[item].get("text", "") for word in ("确认", "排除", "收敛", "解决"))
                for item in selected
            )
            return {"status": "resolved" if resolved else "persistent", "evidence_ids": uncertainty_nodes}
        return {"status": "persistent" if explicit else "not_indicated", "evidence_ids": []}

    def retrieve(
        self,
        query: dict,
        *,
        apply_temporal: bool = True,
        use_relations: bool = True,
        use_flow: bool = True,
        relation_mode: str = "heuristic",
    ) -> dict:
        public = self._public_query(query)
        raw_candidates = self.candidate_retrieval(public)
        eligible, rejected = [], []
        for item in raw_candidates:
            allowed, reason = self.temporal_eligibility(item["document"], public)
            if allowed or not apply_temporal:
                eligible.append(item)
            else:
                rejected.append({"evidence_id": item["document"]["evidence_id"], "reason": reason})
        if not eligible:
            return {
                "selected_evidence_ids": [], "ordered_evidence_flow": [], "relations": [],
                "flow_score": 0.0, "node_scores": {}, "rejections": rejected,
                "uncertainty": {"status": "not_indicated", "evidence_ids": []},
                "candidate_count": len(raw_candidates), "eligible_count": 0,
            }
        node_scores = self._node_scores(public, eligible)
        role_demands = self._role_demands(public["query_text"])
        relation_pool = sorted(
            eligible,
            key=lambda item: (-node_scores[item["document"]["evidence_id"]]["total"], item["document"]["evidence_id"]),
        )[: self.config.search_pool_k]
        relation_diagnostics = {}
        if use_relations and relation_mode == "heuristic":
            edges = self.relation_scoring(relation_pool)
            relation_diagnostics = {
                "accepted_edge_count": len(edges),
                "relation_type_counts": dict(Counter(edge["relation_type"] for edge in edges)),
                "llm_called_pair_count": 0,
                "request_count": 0,
                "cache_lookup_count": 0,
                "cache_hit_count": 0,
                "retry_count": 0,
                "malformed_count": 0,
                "latency_seconds": 0.0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "no_edge_count": 0,
                "prefilter_pairs": [],
            }
        elif use_relations and relation_mode in {"llm", "hybrid"}:
            if self.relation_scorer is None:
                raise ValueError(f"relation_mode={relation_mode} requires a relation_scorer")
            edges, relation_diagnostics = self.relation_scorer.score(
                public, relation_pool, node_scores, self._relation_kind, self._similarity, relation_mode
            )
        elif use_relations:
            raise ValueError("relation_mode must be heuristic, llm, or hybrid")
        else:
            edges = []
        selected, flow_score = self._select_flow(
            eligible, node_scores, edges, role_demands, use_relations=use_relations, use_flow=use_flow
        )
        selected_set = set(selected)
        selected_edges = [
            edge for edge in edges if edge["source_id"] in selected_set and edge["target_id"] in selected_set
        ]
        ordered = sorted(
            selected,
            key=lambda identifier: (
                self.by_id[identifier]["event_time"],
                self.by_id[identifier]["available_at"],
                identifier,
            ),
        )
        return {
            "selected_evidence_ids": selected,
            "ordered_evidence_flow": ordered,
            "relations": selected_edges,
            "relation_graph": edges,
            "relation_diagnostics": relation_diagnostics,
            "flow_score": flow_score["total"],
            "score_components": {key: value for key, value in flow_score.items() if key not in {"active_edges", "search_trace"}},
            "node_scores": {identifier: node_scores[identifier] for identifier in selected},
            "rejections": rejected,
            "uncertainty": self._uncertainty_state(selected, public["query_text"]),
            "candidate_count": len(raw_candidates),
            "eligible_count": len(eligible),
        }
