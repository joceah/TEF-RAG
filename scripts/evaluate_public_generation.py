"""Evaluate structured-generation predictions against the released reference outputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tef_rag.generation_eval import Canonicalizer, evaluate_generation_prediction, macro_average

ROOT = Path(__file__).resolve().parents[1]
GENERATION = ROOT / "data/generation"
BENCHMARK = ROOT / "data/retrieval/benchmark"
METHODS = ("bm25", "bge_reranker", "temporal_bm25", "ta_rag", "tef_rag")


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_gold() -> dict[str, dict[str, Any]]:
    gold_rows = jsonl(GENERATION / "gold_test.jsonl")
    index_rows = jsonl(GENERATION / "gold_test_index.jsonl")
    if len(gold_rows) != 240 or len(index_rows) != 240:
        raise ValueError("test references must contain 240 semantic objects")
    by_query = {}
    for gold, index in zip(gold_rows, index_rows):
        for query_id in index["query_ids"]:
            if query_id in by_query:
                raise ValueError(f"duplicate query ID in reference index: {query_id}")
            by_query[query_id] = gold
    if len(by_query) != 480:
        raise ValueError("test references must cover 480 queries")
    return by_query


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True, help="Directory containing one <method>.jsonl file per method")
    args = parser.parse_args()

    gold_by_query = load_gold()
    query_rows = jsonl(BENCHMARK / "queries_test.jsonl")
    query_by_id = {row["query_id"]: row for row in query_rows}
    evidence_rows = jsonl(BENCHMARK / "evidence.jsonl")
    evidence_by_id = {row["evidence_id"]: row for row in evidence_rows}
    schema = json.loads((GENERATION / "schema.json").read_text(encoding="utf-8"))
    canon = Canonicalizer(
        json.loads((GENERATION / "alias_registry.json").read_text(encoding="utf-8")),
        json.loads((GENERATION / "parameter_registry.json").read_text(encoding="utf-8")),
    )

    metrics = {}
    expected_ids = [row["query_id"] for row in query_rows]
    for method in METHODS:
        rows = jsonl(args.predictions / f"{method}.jsonl")
        if [row.get("query_id") for row in rows] != expected_ids:
            raise ValueError(f"{method}: prediction query coverage/order mismatch")
        scored = []
        for row in rows:
            query = query_by_id[row["query_id"]]
            prediction = row.get("generation", row.get("prediction"))
            if not isinstance(prediction, dict):
                raise ValueError(f"{method}/{row['query_id']}: generation output must be an object")
            input_ids = row.get("input_evidence_ids", row.get("selected_evidence_ids", []))
            if len(input_ids) > 5 or len(input_ids) != len(set(input_ids)):
                raise ValueError(f"{method}/{row['query_id']}: invalid input evidence list")
            for evidence_id in input_ids:
                if evidence_id not in evidence_by_id:
                    raise ValueError(f"{method}/{row['query_id']}: unknown evidence {evidence_id}")
            scored.append(evaluate_generation_prediction(
                prediction, gold_by_query[row["query_id"]], schema, canon,
                set(input_ids), query["asset_id"]
            ))
        metrics[method] = macro_average(scored)

    print(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
