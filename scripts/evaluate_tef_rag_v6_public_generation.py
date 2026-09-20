"""Evaluate public TEF-RAG v6 generation predictions.

This is a reader-facing wrapper around the frozen metric implementation.  It
does not use the formal private one-shot seal; callers provide prediction files
and the released public gold under ``data/generation``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tef_rag_v6.generation_eval import (
    Canonicalizer,
    evaluate_generation_prediction,
    macro_average,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = ROOT / "data/generation/gold_test.jsonl"
DEFAULT_GOLD_INDEX = ROOT / "data/generation/gold_test_index.jsonl"
DEFAULT_QUERIES = ROOT / "data/retrieval/tef_v6_temporal_hard_benchmark_v1/public/queries_test.jsonl"
DEFAULT_SCHEMA = ROOT / "data/generation/schema.json"
DEFAULT_ALIASES = ROOT / "data/generation/alias_registry.json"
DEFAULT_PARAMETERS = ROOT / "data/generation/parameter_registry.json"
DEFAULT_EVIDENCE = ROOT / "data/retrieval/tef_v6_temporal_hard_benchmark_v1/public/evidence.jsonl"
METHODS = ("bm25", "bge_reranker", "temporal_bm25", "ta_rag", "tef_rag_stage3d")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_gold(gold_path: Path, index_path: Path) -> dict[str, dict[str, Any]]:
    gold_rows = _jsonl(gold_path)
    index_rows = _jsonl(index_path)
    if len(gold_rows) != len(index_rows):
        raise ValueError("gold and index row counts differ")
    if len(gold_rows) != 240:
        raise ValueError("released test gold/index must contain exactly 240 semantic objects")
    by_query: dict[str, dict[str, Any]] = {}
    for gold, index in zip(gold_rows, index_rows):
        query_ids = index.get("query_ids")
        if not isinstance(query_ids, list) or any(not isinstance(value, str) for value in query_ids):
            raise ValueError("gold index query_ids must be a list of strings")
        if len(query_ids) != 2:
            raise ValueError("each released test gold index row must cover exactly two query IDs")
        if not isinstance(gold, dict):
            raise ValueError("gold rows must be objects")
        for query_id in query_ids:
            if query_id in by_query:
                raise ValueError(f"duplicate gold query_id: {query_id}")
            by_query[query_id] = gold
    if len(by_query) != 480:
        raise ValueError("released test gold/index must cover exactly 480 unique query IDs")
    return by_query


def evaluate_method(
    prediction_path: Path,
    gold_by_query: dict[str, dict[str, Any]],
    query_by_id: dict[str, dict[str, Any]],
    schema: dict[str, Any],
    canon: Canonicalizer,
    evidence_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, float]:
    rows = _jsonl(prediction_path)
    expected_ids = list(query_by_id)
    if len(rows) != len(expected_ids):
        raise ValueError(f"{prediction_path}: expected exactly {len(expected_ids)} prediction rows")
    row_ids = [row.get("query_id") for row in rows]
    if any(not isinstance(value, str) for value in row_ids) or row_ids != expected_ids or len(set(row_ids)) != len(expected_ids):
        raise ValueError(f"{prediction_path}: query coverage/order/uniqueness mismatch")
    scored = []
    for row in rows:
        query_id = row["query_id"]
        query = query_by_id[query_id]
        prediction = row.get("generation", row.get("prediction"))
        if not isinstance(prediction, dict):
            raise ValueError(f"{prediction_path}: {query_id}: generation must be an object")
        input_ids = row.get("input_evidence_ids", row.get("selected_evidence_ids", []))
        if not isinstance(input_ids, list) or len(input_ids) > 5:
            raise ValueError(f"{prediction_path}: {query_id}: input evidence must be a list of at most 5 IDs")
        if any(not isinstance(value, str) for value in input_ids) or len(input_ids) != len(set(input_ids)):
            raise ValueError(f"{prediction_path}: {query_id}: input evidence IDs must be unique strings")
        if evidence_by_id is not None:
            query_time = query.get("query_time")
            for evidence_id in input_ids:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None:
                    raise ValueError(f"{prediction_path}: {query_id}: unknown input evidence {evidence_id}")
                if evidence.get("asset_id") != query.get("asset_id"):
                    raise ValueError(f"{prediction_path}: {query_id}: input evidence asset mismatch")
                from datetime import datetime
                cutoff = datetime.fromisoformat(str(query_time).replace("Z", "+00:00"))
                event_time = datetime.fromisoformat(str(evidence["event_time"]).replace("Z", "+00:00"))
                available_at = datetime.fromisoformat(str(evidence["available_at"]).replace("Z", "+00:00"))
                if event_time > cutoff or available_at > cutoff:
                    raise ValueError(f"{prediction_path}: {query_id}: input evidence is not visible at cutoff")
        scored.append(
            evaluate_generation_prediction(
                prediction,
                gold_by_query[query_id],
                schema,
                canon,
                set(input_ids),
                query["asset_id"],
            )
        )
    return macro_average(scored)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True, help="Directory containing one <method>.jsonl per retrieval method")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--gold-index", type=Path, default=DEFAULT_GOLD_INDEX)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--alias-registry", type=Path, default=DEFAULT_ALIASES)
    parser.add_argument("--parameter-registry", type=Path, default=DEFAULT_PARAMETERS)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()

    gold_by_query = load_gold(args.gold, args.gold_index)
    query_rows = _jsonl(args.queries)
    query_ids = [row.get("query_id") for row in query_rows]
    if len(query_rows) != 480 or any(not isinstance(value, str) for value in query_ids) or len(set(query_ids)) != 480:
        raise ValueError("queries_test.jsonl must contain exactly 480 unique rows")
    query_by_id = {row["query_id"]: row for row in query_rows}
    if set(gold_by_query) != set(query_by_id):
        raise ValueError("released gold/index query coverage differs from public test queries")
    evidence_rows = _jsonl(args.evidence)
    evidence_by_id = {row["evidence_id"]: row for row in evidence_rows}
    if len(evidence_by_id) != len(evidence_rows):
        raise ValueError("public evidence IDs must be unique")
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    canon = Canonicalizer(
        json.loads(args.alias_registry.read_text(encoding="utf-8")),
        json.loads(args.parameter_registry.read_text(encoding="utf-8")),
    )
    metrics = {}
    for method in METHODS:
        metrics[method] = evaluate_method(args.predictions / f"{method}.jsonl", gold_by_query, query_by_id, schema, canon, evidence_by_id)
    print(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
