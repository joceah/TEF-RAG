"""Frozen, gold-free retrieval baselines for the TEF-RAG v6 benchmark."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import re
from typing import Callable, Iterable

from .pipeline import BM25Index, V6Config


FORBIDDEN_FIELDS = {
    "required_groups", "required_flow_edges", "allowed_endpoint_pairs",
    "flow_complete", "chain_id", "difficulty", "difficulty_labels",
    "primary_difficulty", "answer", "answer_summary",
}


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def assert_public(record: dict) -> None:
    bad = FORBIDDEN_FIELDS.intersection(record)
    if bad:
        raise ValueError(f"forbidden gold/construction fields: {sorted(bad)}")


def visible_snapshot(query: dict, evidence: Iterable[dict]) -> list[dict]:
    """Return the deterministic deployment-visible corpus for one query."""
    assert_public(query)
    cutoff = _time(query["query_time"])
    output = []
    for item in evidence:
        assert_public(item)
        if item.get("asset_id") != query.get("asset_id"):
            continue
        if _time(item["event_time"]) > cutoff or _time(item["available_at"]) > cutoff:
            continue
        if item.get("event_type") == "procedure_applicability" or item.get("source_type") == "procedure":
            if item.get("valid_from") and _time(item["valid_from"]) > cutoff:
                continue
            if item.get("valid_to") and cutoff >= _time(item["valid_to"]):
                continue
            if item.get("withdrawn_at") and cutoff >= _time(item["withdrawn_at"]):
                continue
            scope = item.get("model_scope") or []
            scope = [scope] if isinstance(scope, str) else scope
            if scope and query.get("asset_model") not in scope:
                continue
        output.append(item)
    return sorted(output, key=lambda item: item["evidence_id"])


def _ranking_text(query: dict) -> str:
    text = str(query.get("query_text", query.get("text", "")))
    if query.get("asset_context"):
        text = text.replace(str(query["asset_context"]), "")
    return text.replace(str(query.get("asset_id", "")), "")


def bm25_rank(query: dict, evidence: Iterable[dict], top_k: int = 5) -> list[dict]:
    """Reuse the v6 BM25 implementation, but build it on the safe snapshot."""
    rows = visible_snapshot(query, evidence)
    if not rows:
        return []
    index = BM25Index(rows, V6Config())
    scores = index.score(_ranking_text(query), range(len(rows)))
    order = sorted(range(len(rows)), key=lambda i: (-scores[i], rows[i]["evidence_id"]))
    return [{"evidence_id": rows[i]["evidence_id"], "text": rows[i]["text"],
             "event_time": rows[i]["event_time"], "bm25_score": scores[i]}
            for i in order[:top_k]]


@dataclass(frozen=True)
class TemporalIntent:
    kind: str
    begin: datetime | None = None
    end: datetime | None = None


_CURRENT = re.compile(r"\b(?:current|latest|recent|now|today)\b|最近|当前|最新|近期|这次", re.I)
_RANGE = re.compile(r"((?:19|20)\d{2})(?:[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?)?\s*(?:to|through|until|至|到|—|–|~)\s*((?:19|20)\d{2})", re.I)
_BEFORE = re.compile(
    r"(?:(?:before|prior to|截至|之前|以前)\s*((?:19|20)\d{2})|"
    r"((?:19|20)\d{2})(?:年)?\s*(?:之前|以前))",
    re.I,
)
_AFTER = re.compile(
    r"(?:(?:after|since|之后|以后|自)\s*((?:19|20)\d{2})|"
    r"((?:19|20)\d{2})(?:年)?\s*(?:之后|以后))",
    re.I,
)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?:年)?(?!\d)")


def parse_temporal_intent(text: str, query_time: str) -> TemporalIntent:
    """Small deterministic parser; it never consumes labels or evidence."""
    cutoff = _time(query_time)
    match = _RANGE.search(text)
    if match:
        lo, hi = sorted(map(int, match.groups()))
        return TemporalIntent("range", datetime(lo, 1, 1, tzinfo=cutoff.tzinfo),
                              datetime(hi + 1, 1, 1, tzinfo=cutoff.tzinfo))
    match = _BEFORE.search(text)
    if match:
        year = next(group for group in match.groups() if group is not None)
        return TemporalIntent("before", end=datetime(int(year), 1, 1, tzinfo=cutoff.tzinfo))
    match = _AFTER.search(text)
    if match:
        year = next(group for group in match.groups() if group is not None)
        return TemporalIntent("after", begin=datetime(int(year) + 1, 1, 1, tzinfo=cutoff.tzinfo))
    years = _YEAR.findall(text)
    if years:
        year = int(years[0])
        return TemporalIntent("range", datetime(year, 1, 1, tzinfo=cutoff.tzinfo),
                              datetime(year + 1, 1, 1, tzinfo=cutoff.tzinfo))
    if _CURRENT.search(text):
        return TemporalIntent("current", begin=cutoff, end=cutoff)
    return TemporalIntent("none")


def temporal_score(intent: TemporalIntent, event_time: str) -> float:
    event = _time(event_time)
    scale = 365.0
    if intent.kind == "none":
        return 0.5
    if intent.kind == "current":
        distance = abs((event - intent.begin).total_seconds()) / 86400.0
    elif intent.kind == "before":
        distance = 0.0 if event < intent.end else (event - intent.end).total_seconds() / 86400.0
    elif intent.kind == "after":
        distance = 0.0 if event >= intent.begin else (intent.begin - event).total_seconds() / 86400.0
    else:
        if intent.begin <= event < intent.end:
            distance = 0.0
        else:
            distance = min(abs((event - intent.begin).total_seconds()),
                           abs((event - intent.end).total_seconds())) / 86400.0
    return math.exp(-max(distance, 0.0) / scale)


def temporal_bm25_rank(query: dict, evidence: Iterable[dict], lambda_: float, top_k: int = 5) -> list[dict]:
    rows = bm25_rank(query, evidence, top_k=10_000)
    if not rows:
        return []
    values = [row["bm25_score"] for row in rows]
    low, high = min(values), max(values)
    norm = (lambda value: 0.5) if high <= low else (lambda value: (value - low) / (high - low))
    intent = parse_temporal_intent(str(query.get("query_text", "")), query["query_time"])
    for row in rows:
        row["score"] = lambda_ * norm(row["bm25_score"]) + (1.0 - lambda_) * temporal_score(intent, row["event_time"])
    return sorted(rows, key=lambda row: (-row["score"], -row["bm25_score"], row["evidence_id"]))[:top_k]


def bge_rerank(query: dict, evidence: Iterable[dict], scorer: Callable[[list[list[str]]], list[float]],
               top_k: int = 5) -> list[dict]:
    candidates = bm25_rank(query, evidence, top_k=30)
    query_text = str(query.get("query_text", query.get("text", "")))
    pairs = [[query_text, row["text"]] for row in candidates]
    scores = list(scorer(pairs)) if pairs else []
    ranked = sorted(zip(candidates, scores), key=lambda pair: (-float(pair[1]), -pair[0]["bm25_score"], pair[0]["evidence_id"]))
    return [dict(row, bge_score=float(score)) for row, score in ranked[:top_k]]


def map_provenance(ranked: Iterable[dict], visible_ids: Iterable[str], top_k: int = 5) -> list[str]:
    allowed, output = set(visible_ids), []
    for row in ranked:
        identifier = row.get("provenance_id", row.get("corpus_uid", row.get("evidence_id", row.get("id"))))
        if identifier in allowed and identifier not in output:
            output.append(identifier)
        if len(output) >= top_k:
            break
    return output


def point_interval(value: str) -> tuple[int, int]:
    start = int(_time(value).timestamp())
    return start, start + int(timedelta(seconds=1).total_seconds())
