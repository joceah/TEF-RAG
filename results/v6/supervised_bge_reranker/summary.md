# Supervised BGE reranker baseline

Base: `origin/release/tef-rag-v6-paper` at `c72d22d33462b23f22781bd414f8a3f74fb0a749`. Original model: `BAAI/bge-reranker-v2-m3` revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, model weights SHA-256 `d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286`.

The retrieval path is the frozen BGE baseline's eligible snapshot → BM25 Top 30 → BGE reranking → Top 5. Development alone supplies binary document relevance. All acceptable evidence IDs across required groups are positives; four highest BM25 ranked eligible nonpositives per query are negatives where available. No flow edges or relation annotations enter training. The encoder is frozen, with rank 8 query/value adapters and the classification head trained for two epochs using BCEWithLogits, learning rate 0.0002, batch size 8, seed 20261008. The run used 1,440 development queries (240 chains), 6,116 positives, and 5,482 negatives. Validation has 480 queries (80 chains); test has 480 queries (80 chains). The selected epoch 2 adapter has SHA-256 `3e0e7afb5b36238cd81b2f2a8eab72796bdc39439c1ce000fa6eda3034af782b`; selection used validation nDCG@5 (0.864998) and Recall@5 (0.867882) as tie breaker. Test was run after selection.

## Retrieval test

| Method | Recall@5 | nDCG@5 | Complete@5 | FlowComplete@5 |
| --- | ---: | ---: | ---: | ---: |
| BGE Reranker | 0.291597 | 0.306975 | 0.041667 | 0.041667 |
| Supervised BGE Reranker | **0.664965** | **0.650121** | **0.285417** | **0.283333** |
| Temporal-BM25 | 0.459063 | 0.495500 | 0.079167 | 0.079167 |
| TEF-RAG | 0.722813 | 0.623148 | 0.318750 | 0.314583 |

## Downstream generation test

| Method | Field Macro F1 (strict) | Action F1 | Citation F1 | Plan EM (strict) |
| --- | ---: | ---: | ---: | ---: |
| BGE Reranker | 0.412877 | 0.119792 | 0.040501 | 0.014583 |
| Supervised BGE Reranker | **0.481845** | **0.190972** | **0.095394** | **0.043750** |
| TEF-RAG | 0.534524 | 0.203472 | 0.158460 | 0.041667 |

The old method values above were read from `paper/results/final_retrieval_metrics.json` and `paper/results/final_generation_metrics.json`; no old method was rerun. The new method was scored by the repository's frozen retrieval and public generation evaluator implementations. The same `deepseek-flash` prompt, temperature 0, disabled thinking, JSON schema, and maximum one repair were used. There were 507 API requests, zero API retries and failures during the completed run, 27 repairs, and two outputs with residual validation errors.

## Audit

- Exactly 480 retrieval predictions and 480 generation predictions, each with at most five evidence IDs.
- All selected evidence passed the frozen eligible snapshot filter, including time, availability, asset, and procedure applicability checks.
- Every generation input evidence ID list exactly matches its supervised BGE retrieval output.
- The generator's prompt builder receives only public query fields, selected evidence, and the output schema; it does not receive retrieval method identity, retrieval gold, or graph annotations.
- Development/validation alone were used for training and checkpoint selection. Test gold was read only after the selected checkpoint had been saved.
- One training attempt was restarted after its output directory was missing; this was fixed before the completed two-epoch run. A sandbox network attempt failed, and the initial external API approval was denied until public synthetic data provenance and the user's explicit DeepSeek instruction were supplied. The approved final generation run completed without API retries or failures.
- `local.env`, the API key, downloaded base model, API cache, and diagnostics are excluded from the commit.
