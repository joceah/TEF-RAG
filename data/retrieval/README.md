# TEF-RAG v6 retrieval benchmark

This directory is the reader-facing copy of the public `tef_v6_temporal_hard_benchmark_v1` benchmark used by the V6 retrieval pipeline.

- `public/queries_*.jsonl`, `public/evidence.jsonl`, and `public/chains_*.jsonl` are the materialized inputs.
- `public/gold_development.jsonl` and `public/gold_validation.jsonl` contain the public retrieval labels.
- The temporal-hard benchmark manifest intentionally keeps the 480-row test retrieval evaluator sealed (`public_test_gold=false`); the public test split contains queries, chains, and evidence only.
- `metadata/` contains the relation taxonomy, source registry, review status, split summary, and validation review metadata.

The original deterministic transport and validator remain under `data/generated/tef_v6_temporal_hard_benchmark_v1/` for byte-level provenance. The files here are the convenient public entry point.
