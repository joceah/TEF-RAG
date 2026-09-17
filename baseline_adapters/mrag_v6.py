"""Visibility-safe MRAG v6 boundary; delegates all scoring to official MRAG."""
from __future__ import annotations

from datetime import datetime
import inspect

FORBIDDEN = {"required_groups", "required_flow_edges", "allowed_endpoint_pairs", "flow_complete",
             "chain_id", "difficulty", "gold", "answer"}


def _time(value): return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _check_public(value):
    if set(value) & FORBIDDEN: raise ValueError("gold/authoring fields are forbidden")


def visible_snapshot(query, evidence):
    _check_public(query); cutoff = _time(query["query_time"]); asset = query.get("asset_id")
    rows = []
    for item in evidence:
        _check_public(item)
        if asset is not None and item.get("asset_id") != asset: continue
        if _time(item["event_time"]) <= cutoff and _time(item["available_at"]) <= cutoff:
            rows.append(item)
    return sorted(rows, key=lambda item: item["id"])


def map_provenance(ranked, visible_ids, top_k=5):
    allowed, output = set(visible_ids), []
    for item in ranked:
        identifier = item.get("provenance_id", item.get("evidence_id", item.get("corpus_uid", item.get("id"))))
        if identifier in allowed and identifier not in output:
            output.append(identifier)
        if len(output) == top_k: break
    return output


class MRAGV6Adapter:
    """The injected backend must run official query processing, summarization, and hybrid ranking."""
    def __init__(self, official_backend): self.official_backend = official_backend

    def retrieve(self, query, visible_evidence, top_k=5):
        _check_public(query)
        rows = visible_snapshot(query, visible_evidence)
        contexts = [{"id": item["id"], "provenance_id": item["id"], "title": item.get("source_type", ""),
                     "text": item["text"], "event_time": item["event_time"],
                     "available_at": item["available_at"]} for item in rows]
        ranked = self.official_backend(question=query.get("query_text", query.get("text", "")),
                                       query_time=query["query_time"], contexts=contexts)
        return map_provenance(ranked, [item["id"] for item in rows], top_k)


assert "gold" not in inspect.signature(MRAGV6Adapter.retrieve).parameters
