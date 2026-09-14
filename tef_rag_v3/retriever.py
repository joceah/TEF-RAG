"""Unambiguous relation schema for bitemporal evidence-flow retrieval."""

from tef_rag_v2.retriever import (
    KNOWLEDGE_RELATIONS,
    PROCESS_RELATIONS,
    BitemporalEvidenceFlowRetrieverV2,
)


class ExplicitUpdateEvidenceFlowRetrieverV3(BitemporalEvidenceFlowRetrieverV2):
    """Traverse from a prior state to an update that qualifies that state.

    Preferred relation objects use ``prior_id``, ``update_id`` and
    ``update_relation``.  The relation label always describes what the update
    does to the prior state, so "late_report refutes hypothesis" is encoded as
    ``prior_id=hypothesis, update_id=late_report, update_relation=refutes``.

    The v1/v2 ``source_id``/``target_id``/``relation`` schema remains readable
    only so preserved experiments do not need to be rewritten.
    """

    def __init__(self, records, assets, relations, **kwargs):
        normalized = []
        for relation in relations:
            if any(key in relation for key in ("prior_id", "update_id", "update_relation")):
                prior = relation.get("prior_id")
                update = relation.get("update_id")
                kind = relation.get("update_relation")
                schema = "prior_update_v3"
            else:
                prior = relation.get("source_id")
                update = relation.get("target_id")
                kind = relation.get("relation")
                schema = "legacy_source_target"
            item = dict(relation)
            item.update(
                source_id=prior,
                target_id=update,
                relation=kind,
                prior_id=prior,
                update_id=update,
                update_relation=kind,
                relation_schema=schema,
            )
            normalized.append(item)
        super().__init__(records, assets, normalized, **kwargs)

    @staticmethod
    def _clock(kind):
        if kind in PROCESS_RELATIONS:
            return "event_time"
        if kind in KNOWLEDGE_RELATIONS:
            return "available_at"
        return None

    def retrieve(self, query, relevance, relation_scores=None):
        result = super().retrieve(query, relevance, relation_scores=relation_scores)
        if result.get("selector") == "bitemporal_evidence_flow_beam_v2":
            result["selector"] = "explicit_update_evidence_flow_beam_v3"
        for path in result.get("trace", []):
            for relation in path.get("relations", []):
                relation.update(
                    prior_id=relation["source_id"],
                    update_id=relation["target_id"],
                    update_relation=relation["relation"],
                    clock=self._clock(relation["relation"]),
                )
        for relation in result.get("rejected_edges", []):
            if "source_id" in relation:
                relation.update(
                    prior_id=relation["source_id"],
                    update_id=relation["target_id"],
                    update_relation=relation.get("relation"),
                )
        result["relation_schema"] = "prior_update_v3"
        result["relation_semantics"] = "update_relation describes update_id relative to prior_id; traversal is prior-to-update"
        return result
