"""Visibility-safe TA-RAG v6 boundary; delegates parsing/retrieval to official TA-RAG."""
from __future__ import annotations

from datetime import datetime, timedelta
import inspect

from baseline_adapters.mrag_v6 import FORBIDDEN, _check_public, visible_snapshot, map_provenance


def _plus_second(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) + timedelta(seconds=1)
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def to_ta_corpus(query, evidence):
    rows = visible_snapshot(query, evidence)
    return [{"corpus_uid": item["id"], "provenance_id": item["id"], "chunk_number": 0,
             "chunk_text": item["text"],
             "chunk_time_info": [{"event_time_interval": {"begin": item["event_time"],
                                                              "end": _plus_second(item["event_time"])}}],
             "new_background": {"begin": item["event_time"], "end": _plus_second(item["event_time"]),
                                "estimate_doc_create_date": item["event_time"]}}
            for item in rows]


class TARAGV6Adapter:
    """Backend builds a per-snapshot FAISS/NCLS index and invokes the official LLM parser."""
    def __init__(self, official_backend): self.official_backend = official_backend

    def retrieve(self, query, visible_evidence, top_k=5):
        _check_public(query)
        corpus = to_ta_corpus(query, visible_evidence)
        ranked = self.official_backend(question=query.get("query_text", query.get("text", "")),
                                       query_time=query["query_time"], corpus=corpus, top_k=top_k)
        return map_provenance(ranked, [item["corpus_uid"] for item in corpus], top_k)


assert "gold" not in inspect.signature(TARAGV6Adapter.retrieve).parameters
