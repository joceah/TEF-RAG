"""Validate the public retrieval benchmark and released evaluator."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.evaluate_public_retrieval import BENCHMARK, TEST_EVALUATOR_SHA256, jsonl, sha256


def main() -> None:
    queries = sum((jsonl(BENCHMARK / f"queries_{split}.jsonl") for split in ("development", "validation", "test")), [])
    chains = sum((jsonl(BENCHMARK / f"chains_{split}.jsonl") for split in ("development", "validation", "test")), [])
    evidence = jsonl(BENCHMARK / "evidence.jsonl")
    gold = sum((jsonl(BENCHMARK / f"gold_{split}.jsonl") for split in ("development", "validation")), [])

    errors = []
    if len(queries) != 2400 or len({row["query_id"] for row in queries}) != 2400:
        errors.append("expected 2400 unique queries")
    if len(chains) != 400 or len({row["chain_id"] for row in chains}) != 400:
        errors.append("expected 400 unique chains")
    if len(evidence) != 3888 or len({row["evidence_id"] for row in evidence}) != 3888:
        errors.append("expected 3888 unique evidence records")
    non_test_ids = {row["query_id"] for row in queries if row["split"] != "test"}
    if len(gold) != 1920 or {row["query_id"] for row in gold} != non_test_ids:
        errors.append("development/validation references do not cover their query set")
    evaluator = BENCHMARK / "test_evaluator.jsonl"
    if sha256(evaluator) != TEST_EVALUATOR_SHA256 or len(jsonl(evaluator)) != 480:
        errors.append("released test evaluator is invalid")

    if errors:
        raise SystemExit("retrieval validation failed:\n- " + "\n- ".join(errors))
    print("retrieval validation passed: 400 chains, 3,888 evidence records, 2,400 queries")


if __name__ == "__main__":
    main()
