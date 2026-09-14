"""TEF-RAG with a shared asset-and-visibility candidate pool."""

from tef_rag_v3 import ExplicitUpdateEvidenceFlowRetrieverV3
from tmc_rag_v3.retriever import TMCRetrieverV3, parse_query, visible


class VisibilityOnlyRetriever(TMCRetrieverV3):
    """Keep query parsing for objectives, never use it to shrink candidates."""

    def scope(self, query):
        parsed = parse_query(query)
        candidates = [
            record
            for record in self.records
            if record["asset_id"] == query["asset_id"] and visible(record, query)
        ]
        return parsed, candidates


class NeutralScopeEvidenceFlowRetrieverV4(ExplicitUpdateEvidenceFlowRetrieverV3):
    """Use only shared asset and bitemporal visibility before path selection."""

    def __init__(self, records, assets, relations, **kwargs):
        super().__init__(records, assets, relations, **kwargs)
        self.base = VisibilityOnlyRetriever(
            self.records,
            assets,
            {},
            top_k=self.top_k,
            budget=self.budget,
        )

    def retrieve(self, query, relevance, relation_scores=None):
        result = super().retrieve(query, relevance, relation_scores=relation_scores)
        if result.get("selector") == "explicit_update_evidence_flow_beam_v3":
            result["selector"] = "neutral_scope_evidence_flow_beam_v4"
        result["candidate_policy"] = "same_asset_and_event_available_by_query_time"
        return result
