"""Validate the reader-facing materialized TEF-RAG v6 retrieval dataset."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / "data/retrieval/tef_v6_temporal_hard_benchmark_v1"


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate(base: Path) -> list[str]:
    errors: list[str] = []
    public = base / "public"
    queries = sum((rows(public / f"queries_{split}.jsonl") for split in ("development", "validation", "test")), [])
    chains = sum((rows(public / f"chains_{split}.jsonl") for split in ("development", "validation", "test")), [])
    evidence = rows(public / "evidence.jsonl")
    gold = sum((rows(public / f"gold_{split}.jsonl") for split in ("development", "validation")), [])
    query_ids = {row["query_id"] for row in queries}
    if len(queries) != 2400 or len(query_ids) != 2400:
        errors.append("expected 2400 unique queries")
    if len(chains) != 400 or len({row["chain_id"] for row in chains}) != 400:
        errors.append("expected 400 unique chains")
    if len({row["evidence_id"] for row in evidence}) != len(evidence):
        errors.append("evidence IDs are not unique")
    public_query_ids = {row["query_id"] for row in queries if row["split"] != "test"}
    if len(gold) != 1920 or {row["query_id"] for row in gold} != public_query_ids:
        errors.append("public development/validation retrieval gold does not cover exactly its query set")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    errors = validate(args.root)
    if errors:
        raise SystemExit("public retrieval validation failed:\n- " + "\n- ".join(errors))
    print("public retrieval validation passed: 400 chains, 2400 queries, 1920 public gold rows; test evaluator remains sealed")


if __name__ == "__main__":
    main()
