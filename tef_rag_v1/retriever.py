"""Query-conditioned temporal evidence-flow retrieval prototype.

The retriever deliberately keeps visibility and explicit scope separate from
evidence-flow selection.  It consumes public relation projections; it never
reads gold labels and it does not call an LLM internally.
"""

from collections import defaultdict

from tmc_rag_v3 import TMCRetrieverV3
from tmc_rag_v3.retriever import dt


RELATIONS = {
    "follows",
    "same_process",
    "supports",
    "verifies",
    "refutes",
    "supersedes",
    "resolves",
}

OBJECTIVE_WEIGHTS = {
    "resolution": {
        "verifies": 1.00,
        "resolves": 1.00,
        "refutes": 0.95,
        "supports": 0.75,
        "supersedes": 0.65,
        "follows": 0.25,
        "same_process": 0.20,
    },
    "evolution": {
        "supersedes": 1.00,
        "refutes": 0.90,
        "verifies": 0.75,
        "supports": 0.65,
        "follows": 0.50,
        "resolves": 0.50,
        "same_process": 0.25,
    },
    "comparison": {
        "same_process": 0.80,
        "supersedes": 0.80,
        "refutes": 0.75,
        "verifies": 0.70,
        "supports": 0.65,
        "follows": 0.35,
        "resolves": 0.60,
    },
    "point_state": {name: 0.50 for name in RELATIONS},
}


def _objective(query, parsed):
    explicit = query.get("evidence_objective")
    if explicit in OBJECTIVE_WEIGHTS:
        return explicit
    text = query["text"]
    if parsed["compare"] or any(word in text for word in ("演变", "变化", "前后")):
        return "evolution"
    if any(word in text for word in ("原因", "解决", "恢复", "完成依据", "确认", "排除")):
        return "resolution"
    if any(word in text for word in ("分别", "比较", "对比")):
        return "comparison"
    return "point_state"


class TemporalEvidenceFlowRetrieverV1:
    """Select temporally coherent evidence paths after shared scope filtering.

    `relations` are public projections with source_id, target_id, relation and
    confidence.  Optional `relation_scores` supplied at retrieval time are the
    intended hook for a trained pair scorer.  The built-in confidence path is a
    deterministic reference implementation, not a claim of learned novelty.
    """

    def __init__(
        self,
        records,
        assets,
        relations,
        roles=None,
        top_k=5,
        beam_width=32,
        max_path_nodes=4,
        budget=16000,
    ):
        self.records = list(records)
        self.by_id = {record["id"]: record for record in self.records}
        self.relations = list(relations)
        self.top_k = top_k
        self.beam_width = beam_width
        self.max_path_nodes = max_path_nodes
        self.budget = budget
        self.base = TMCRetrieverV3(
            self.records,
            assets,
            roles or {},
            top_k=top_k,
            budget=budget,
        )

    @staticmethod
    def _normalise_relevance(candidates, relevance):
        values = [float(relevance.get(record["id"], 0.0)) for record in candidates]
        lo = min(values, default=0.0)
        hi = max(values, default=0.0)
        if hi == lo:
            return {record["id"]: 0.5 for record in candidates}
        return {
            record["id"]: (float(relevance.get(record["id"], 0.0)) - lo) / (hi - lo)
            for record in candidates
        }

    @staticmethod
    def _external_edge_score(relation, relation_scores):
        source = relation["source_id"]
        target = relation["target_id"]
        if relation_scores:
            if (source, target) in relation_scores:
                return float(relation_scores[(source, target)])
            key = source + "->" + target
            if key in relation_scores:
                return float(relation_scores[key])
        return float(relation.get("confidence", 0.5))

    def _admissible_edges(self, candidates, objective, relation_scores):
        candidate_ids = {record["id"] for record in candidates}
        weights = OBJECTIVE_WEIGHTS[objective]
        outgoing = defaultdict(list)
        rejected = []
        for relation in self.relations:
            source = relation.get("source_id")
            target = relation.get("target_id")
            kind = relation.get("relation")
            if source not in candidate_ids or target not in candidate_ids or source == target:
                continue
            if kind not in RELATIONS:
                rejected.append({"source_id": source, "target_id": target, "reason": "unknown_relation"})
                continue
            # Evidence flow is directed from an earlier assertion/action to a
            # later observation/correction.  Backward projections are rejected
            # instead of silently turning them into undirected graph edges.
            if dt(self.by_id[source]["event_time"]) > dt(self.by_id[target]["event_time"]):
                rejected.append({"source_id": source, "target_id": target, "reason": "backward_time"})
                continue
            raw_score = max(0.0, min(1.0, self._external_edge_score(relation, relation_scores)))
            score = raw_score * weights.get(kind, 0.0)
            outgoing[source].append((target, score, kind))
        for source in outgoing:
            outgoing[source].sort(key=lambda item: (-item[1], item[0], item[2]))
        return outgoing, rejected

    @staticmethod
    def _path_score(nodes, edges, node_scores):
        node_mean = sum(node_scores[node] for node in nodes) / len(nodes)
        if not edges:
            return 0.45 * node_mean
        edge_mean = sum(edge[1] for edge in edges) / len(edges)
        relation_coverage = min(len({edge[2] for edge in edges}) / 2.0, 1.0)
        return 0.45 * node_mean + 0.45 * edge_mean + 0.10 * relation_coverage

    def _rank_paths(self, candidates, node_scores, outgoing):
        frontier = [((record["id"],), tuple()) for record in candidates]
        paths = list(frontier)
        for _ in range(1, self.max_path_nodes):
            expanded = []
            for nodes, edges in frontier:
                for target, score, kind in outgoing.get(nodes[-1], []):
                    if target in nodes:
                        continue
                    expanded.append((nodes + (target,), edges + ((nodes[-1], score, kind),)))
            if not expanded:
                break
            expanded.sort(
                key=lambda item: (
                    -self._path_score(item[0], item[1], node_scores),
                    -len(item[0]),
                    item[0],
                )
            )
            frontier = expanded[: self.beam_width]
            paths.extend(frontier)
        paths.sort(
            key=lambda item: (
                -self._path_score(item[0], item[1], node_scores),
                -len(item[0]),
                item[0],
            )
        )
        return paths

    def retrieve(self, query, relevance, relation_scores=None):
        parsed, candidates = self.base.scope(query)
        if not candidates:
            return {
                "evidence_ids": [],
                "trace": [],
                "query_scope": parsed,
                "candidate_count": 0,
                "status": "no_visible_match",
                "objective": _objective(query, parsed),
            }
        if parsed["latest"]:
            result = self.base.retrieve(query, relevance, mode="scoped_latest")
            result.update(objective="latest", selector="shared_recency_control")
            return result

        objective = _objective(query, parsed)
        node_scores = self._normalise_relevance(candidates, relevance)
        outgoing, rejected = self._admissible_edges(candidates, objective, relation_scores)
        if not outgoing:
            result = self.base.retrieve(query, relevance, mode="scoped_hybrid")
            result.update(
                objective=objective,
                selector="scoped_hybrid_fallback",
                rejected_edges=rejected,
            )
            return result

        paths = self._rank_paths(candidates, node_scores, outgoing)
        selected = []
        selected_paths = []
        used = 0
        for nodes, edges in paths:
            novel = [node for node in nodes if node not in selected]
            if not novel:
                continue
            if not selected or edges:
                novel = novel[: self.top_k - len(selected)]
                if used + sum(len(self.by_id[node]["text"]) for node in novel) > self.budget:
                    continue
                for node in novel:
                    selected.append(node)
                    used += len(self.by_id[node]["text"])
                selected_paths.append(
                    {
                        "nodes": list(nodes),
                        "relations": [
                            {"source_id": source, "target_id": nodes[index + 1], "relation": kind, "score": score}
                            for index, (source, score, kind) in enumerate(edges)
                        ],
                        "score": self._path_score(nodes, edges, node_scores),
                    }
                )
            if len(selected) >= self.top_k:
                break

        for record in sorted(candidates, key=lambda item: (-node_scores[item["id"]], item["id"])):
            if len(selected) >= self.top_k:
                break
            if record["id"] not in selected and used + len(record["text"]) <= self.budget:
                selected.append(record["id"])
                used += len(record["text"])

        return {
            "evidence_ids": selected,
            "trace": selected_paths,
            "query_scope": parsed,
            "candidate_count": len(candidates),
            "status": "ok",
            "objective": objective,
            "selector": "temporal_evidence_flow_beam_v1",
            "rejected_edges": rejected,
            "characters": used,
        }
