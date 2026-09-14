"""Relation-specific temporal clocks for evidence-flow path selection."""

from collections import defaultdict

from tef_rag_v1.retriever import OBJECTIVE_WEIGHTS, RELATIONS, TemporalEvidenceFlowRetrieverV1
from tmc_rag_v3.retriever import dt


PROCESS_RELATIONS = {"follows", "verifies", "resolves"}
KNOWLEDGE_RELATIONS = {"supports", "refutes", "supersedes", "same_process"}


def knowledge_time(record):
    return dt(record.get("available_at") or record["event_time"])


class BitemporalEvidenceFlowRetrieverV2(TemporalEvidenceFlowRetrieverV1):
    """Use event time for process edges and availability for belief updates."""

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
            source_record = self.by_id[source]
            target_record = self.by_id[target]
            if kind in PROCESS_RELATIONS and dt(source_record["event_time"]) > dt(target_record["event_time"]):
                rejected.append(
                    {
                        "source_id": source,
                        "target_id": target,
                        "relation": kind,
                        "clock": "event_time",
                        "reason": "backward_event_time",
                    }
                )
                continue
            if kind in KNOWLEDGE_RELATIONS and knowledge_time(source_record) > knowledge_time(target_record):
                rejected.append(
                    {
                        "source_id": source,
                        "target_id": target,
                        "relation": kind,
                        "clock": "available_at",
                        "reason": "backward_knowledge_time",
                    }
                )
                continue
            raw_score = max(0.0, min(1.0, self._external_edge_score(relation, relation_scores)))
            outgoing[source].append((target, raw_score * weights.get(kind, 0.0), kind))
        for source in outgoing:
            outgoing[source].sort(key=lambda item: (-item[1], item[0], item[2]))
        return outgoing, rejected

    def retrieve(self, query, relevance, relation_scores=None):
        result = super().retrieve(query, relevance, relation_scores=relation_scores)
        if result.get("selector") == "temporal_evidence_flow_beam_v1":
            result["selector"] = "bitemporal_evidence_flow_beam_v2"
        result["edge_clock_policy"] = {"process": "event_time", "knowledge_update": "available_at"}
        return result
