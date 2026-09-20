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
METHODS = ("bm25", "bge_reranker", "temporal_bm25", "ta_rag", "tef_rag_stage3d")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_gold(gold_path: Path, index_path: Path) -> dict[str, dict[str, Any]]:
    gold_rows = _jsonl(gold_path)
    index_rows = _jsonl(index_path)
    if len(gold_rows) != len(index_rows):
        raise ValueError("gold and index row counts differ")
    by_query: dict[str, dict[str, Any]] = {}
    for gold, index in zip(gold_rows, index_rows):
        for query_id in index["query_ids"]:
            if query_id in by_query:
                raise ValueError(f"duplicate gold query_id: {query_id}")
            by_query[query_id] = gold
    return by_query


def evaluate_method(
    prediction_path: Path,
    gold_by_query: dict[str, dict[str, Any]],
    query_by_id: dict[str, dict[str, Any]],
    schema: dict[str, Any],
    canon: Canonicalizer,
) -> dict[str, float]:
    rows = _jsonl(prediction_path)
    scored = []
    for row in rows:
        query_id = row["query_id"]
        query = query_by_id[query_id]
        prediction = row.get("generation", row.get("prediction"))
        if not isinstance(prediction, dict):
            raise ValueError(f"{prediction_path}: {query_id}: generation must be an object")
        scored.append(
            evaluate_generation_prediction(
                prediction,
                gold_by_query[query_id],
                schema,
                canon,
                set(row.get("input_evidence_ids", row.get("selected_evidence_ids", []))),
                query["asset_id"],
            )
        )
    if not scored:
        raise ValueError(f"{prediction_path}: no prediction rows")
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
    args = parser.parse_args()

    gold_by_query = load_gold(args.gold, args.gold_index)
    query_by_id = {row["query_id"]: row for row in _jsonl(args.queries)}
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    canon = Canonicalizer(
        json.loads(args.alias_registry.read_text(encoding="utf-8")),
        json.loads(args.parameter_registry.read_text(encoding="utf-8")),
    )
    metrics = {}
    for method in METHODS:
        metrics[method] = evaluate_method(args.predictions / f"{method}.jsonl", gold_by_query, query_by_id, schema, canon)
    print(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
