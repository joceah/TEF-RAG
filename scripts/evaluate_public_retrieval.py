"""Evaluate the published retrieval predictions against the released test evaluator."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from tef_rag.evaluation import average, evaluate_prediction

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data/retrieval/benchmark"
PREDICTIONS = ROOT / "data/retrieval/predictions"
TEST_EVALUATOR_SHA256 = "477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3"
METHODS = ("bm25", "bge_reranker", "fine_tuned_bge", "temporal_bm25", "ta_rag", "tef_rag")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, raw in enumerate(path.read_bytes().splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: row must be an object")
        rows.append(value)
    return rows


def parse_time(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def visible(evidence: dict[str, Any], query: dict[str, Any]) -> bool:
    cutoff = parse_time(query["query_time"])
    return (
        evidence.get("asset_id") == query.get("asset_id")
        and parse_time(evidence["event_time"]) <= cutoff
        and parse_time(evidence["available_at"]) <= cutoff
    )


def load_reference():
    evaluator = BENCHMARK / "test_evaluator.jsonl"
    if sha256(evaluator) != TEST_EVALUATOR_SHA256:
        raise ValueError("test evaluator SHA-256 mismatch")
    queries = jsonl(BENCHMARK / "queries_test.jsonl")
    evaluator_rows = jsonl(evaluator)
    expected_ids = [row["query_id"] for row in queries]
    if len(expected_ids) != 480 or len(set(expected_ids)) != 480:
        raise ValueError("test query set must contain exactly 480 unique query IDs")
    gold_by_query = {}
    actual_ids = []
    for row in evaluator_rows:
        query_id = row["query"]["query_id"]
        actual_ids.append(query_id)
        gold_by_query[query_id] = row["gold"]
    if actual_ids != expected_ids:
        raise ValueError("test evaluator query coverage/order mismatch")
    return queries, expected_ids, gold_by_query


def main() -> None:
    queries, expected_ids, gold_by_query = load_reference()
    query_by_id = {row["query_id"]: row for row in queries}
    evidence_rows = jsonl(BENCHMARK / "evidence.jsonl")
    evidence_by_id = {row["evidence_id"]: row for row in evidence_rows}
    if len(evidence_by_id) != len(evidence_rows):
        raise ValueError("evidence IDs must be unique")

    manifest = json.loads((PREDICTIONS / "manifest.json").read_text(encoding="utf-8"))
    metrics = {}
    for method in METHODS:
        entry = manifest["predictions"][method]
        path = PREDICTIONS / entry["file"]
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"{method}: prediction SHA-256 mismatch")
        rows = json.loads(path.read_text(encoding="utf-8"))
        if len(rows) != 480 or [row.get("query_id") for row in rows] != expected_ids:
            raise ValueError(f"{method}: prediction query coverage/order mismatch")
        scores = []
        for row in rows:
            selected = row.get("selected_evidence_ids", [])
            if len(selected) > 5 or len(selected) != len(set(selected)):
                raise ValueError(f"{method}/{row['query_id']}: invalid selected evidence")
            query = query_by_id[row["query_id"]]
            for evidence_id in selected:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None or not visible(evidence, query):
                    raise ValueError(f"{method}/{row['query_id']}: invalid or unavailable evidence {evidence_id}")
            scores.append(evaluate_prediction(row, gold_by_query[row["query_id"]], 5))
        aggregate = average(scores)
        if method != "tef_rag":
            aggregate["edge_recall"] = None
        metrics[method] = aggregate

    print(json.dumps({"metrics": metrics}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
