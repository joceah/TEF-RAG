# TEF-RAG v6 retrieval benchmark

This directory is the reader-facing copy of the public `tef_v6_temporal_hard_benchmark_v1` benchmark used by the V6 retrieval pipeline.

- `public/queries_*.jsonl`, `public/evidence.jsonl`, and `public/chains_*.jsonl` are the materialized inputs.
- `public/gold_development.jsonl` and `public/gold_validation.jsonl` contain the public retrieval labels.
- The 480-row historical test evaluator was kept sealed during all model development and formal test evaluation. After the TEF-RAG v6 experiments were completed and predictions/results were frozen, the exact historical evaluator was released at `public/test_evaluator.jsonl` for reproducibility (SHA-256 `477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3`). The historical benchmark manifest retains `public_test_gold=false` to preserve the original formal-seal state.
- Frozen formal retrieval predictions are published under `../frozen_test_predictions/`; their manifest SHA-256 is `995b9f739ad85f77f54977f357714438d9b425e76a5fea07b9022b767185ab7f`.
- `metadata/` contains the relation taxonomy, source registry, review status, split summary, and validation review metadata.

The public evaluator is run with `python -m scripts.evaluate_tef_rag_v6_public_retrieval`. It reuses `tef_rag_v6.evaluation.evaluate_prediction` and `.average`, and rejects any evaluator, query, prediction, evidence, duplicate, or visibility mismatch before scoring. The original deterministic transport and validator remain under `data/generated/tef_v6_temporal_hard_benchmark_v1/` for byte-level provenance.
