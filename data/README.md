# TEF-RAG v6 data

This release contains the datasets used by the final TEF-RAG v6 paper experiments. They are **public-source-grounded, AI-assisted synthetic benchmarks**: they are not real station work orders, field-certified procedures, or real-world failure-rate statistics. Public sources constrain reference envelopes and provenance boundaries; unsupported operational causal chains, thresholds, and procedures are benchmark modeling choices.

## Reader-facing datasets

- `retrieval/` — TEF-RAG v6 temporal-hard retrieval benchmark, including development/validation labels, the post-evaluation released historical test evaluator, and frozen formal test predictions.
- `generation/` — structured work-order/action-plan gold for development, validation, and the post-evaluation released test split, plus schema and canonicalization registries.

## Provenance transport

`generated/tef_v6_temporal_hard_benchmark_v1/` and `generated/tef_v6_generation_gold_v1/` retain deterministic transport, manifests, hashes, and metadata used by the frozen protocol. Historical manifests are not rewritten when an artifact is released after evaluation. In particular, `public_test_gold=false` records that the retrieval test evaluator was hidden at formal sealing time; the exact evaluator bytes were published later under `retrieval/` after the V6 experiments and predictions were frozen.

## Source boundary

The retrieval benchmark source registry is under `generated/tef_v6_temporal_hard_benchmark_v1/metadata/source_registry.json`. Manufacturer/product references are used only for the support boundaries stated there. Synthetic telemetry bands, event chains, work orders, procedures, and difficulty mixtures remain reproducible modeling choices unless explicitly source-backed.

Both formal V6 test evaluations are complete. Their reader-facing aggregate results are in `../paper/results/final_retrieval_metrics.json` and `../paper/results/final_generation_metrics.json`.
