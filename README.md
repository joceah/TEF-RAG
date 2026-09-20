# TEF-RAG

TEF-RAG (Temporal Evidence Flow Retrieval-Augmented Generation) is a reproducible benchmark and implementation for maintenance questions whose answer depends on event time, evidence availability, procedure versions, and ordered actions. **TEF-RAG v6 is the final implementation used for the paper experiments.**

## Repository layout

- `tef_rag_v6/` — V6 retrieval, temporal constraints, relation scoring, rankers, and frozen generation metrics.
- `baseline_adapters/` — comparison retrieval adapters used by the V6 study.
- `scripts/` — benchmark materialization, V6 stage runners, validators, and the public generation evaluator.
- `data/retrieval/` — reader-facing materialized retrieval inputs and public development/validation labels.
- `data/generation/` — development, validation, and released post-blind-evaluation test generation gold and registries.
- `artifacts/v6/` — small V6 learned-model and feature artifacts required by the final stages.
- `tests/` — release-tree unit, regression, and dataset tests.
- `paper/` — the paper snapshot and aggregate reference metrics.

The original deterministic transport files remain under `data/generated/tef_v6_*` for provenance and validator compatibility. They are not required for ordinary reading of the materialized datasets.

## Installation

Python 3.11 or newer is required.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
python -m pip install -e ".[test]"
python -m pytest -q
```

For semantic retrieval and learned ranking stages install the relevant extras:

```bash
python -m pip install -e ".[semantic,ranknet]"
```

The downstream generator uses the official DeepSeek endpoint and an API key supplied through the local environment. Use a local, untracked `local.env` or exported variables; never commit credentials.

## Datasets

### Retrieval

`data/retrieval/tef_v6_temporal_hard_benchmark_v1/public/` contains 400 chains, 2,400 queries, the shared evidence corpus, and development/validation retrieval labels. The benchmark manifest intentionally keeps the 480-row test retrieval evaluator sealed (`public_test_gold=false`); test queries, chains, and evidence are public.

The files are already materialized. To verify the canonical transport and all benchmark invariants:

```bash
python -m scripts.validate_tef_v6_semantic_benchmark_v1
python -m scripts.validate_tef_rag_v6_public_retrieval
```

### Generation

`data/generation/` contains the structured generation schema and registries plus development, validation, and test gold/index files. The test gold was released only after the blind evaluation completed. Canonical LF hashes are:

| file | SHA-256 |
| --- | --- |
| `gold_test.jsonl` | `dccf5a831b9b145d5aab26288088d14d2e9af6fafd06d4eced3a22983a7c9aea` |
| `gold_test_index.jsonl` | `8433880d300e541713aba7eae86564bcb705f6f9c638043a66d7262f5b195d35` |

Validate the released gold and indexes with:

```bash
python -m scripts.validate_tef_rag_v6_public_generation
```

## Reproduce retrieval

The V6 stages use only the public retrieval inputs and write results under an output directory supplied to each runner. A typical development/validation run is:

```bash
python -m scripts.run_tef_rag_v6_stage1
python -m scripts.run_tef_rag_v6_stage2a
python -m scripts.run_tef_rag_v6_stage2b
python -m scripts.run_tef_rag_v6_stage2b1
python -m scripts.run_tef_rag_v6_stage2c
python -m scripts.run_tef_rag_v6_stage3a
python -m scripts.run_tef_rag_v6_stage3b
python -m scripts.run_tef_rag_v6_stage3c
python -m scripts.run_tef_rag_v6_stage3d
python -m scripts.run_tef_rag_v6_baseline_suite
```

The runners do not expose test labels. Retrieval metrics are computed from the public development/validation gold or from a separately prepared sealed evaluation environment.

## Reproduce generation evaluation

The formal generator consumes each method's frozen selected evidence and uses the shared V6 prompt, schema, and one-repair policy. The formal runner is:

```bash
python -m scripts.run_tef_rag_v6_generation_eval preflight
python -m scripts.run_tef_rag_v6_generation_eval generate --all
python -m scripts.run_tef_rag_v6_generation_eval freeze
```

For a public, non-sealed evaluation of prediction files, use the wrapper below. It reuses `tef_rag_v6.generation_eval` metric formulas and reads the released test gold/index; it does not use the formal private one-shot lock:

```bash
python -m scripts.evaluate_tef_rag_v6_public_generation --predictions path/to/predictions
```

Each prediction file is named `<method>.jsonl` and contains `query_id`, `input_evidence_ids`, and a `generation` object. The wrapper expects the five method names `bm25`, `bge_reranker`, `temporal_bm25`, `ta_rag`, and `tef_rag_stage3d`.

## Reference paper metrics

The released aggregate generation reference is in [`paper/results/final_generation_metrics.json`](paper/results/final_generation_metrics.json). It contains no item-level predictions or private evaluation details. Retrieval aggregate tables and methodological context are in [`paper/`](paper/).

## Reproducibility notes

- Generator model: `deepseek-flash`, official endpoint, temperature `0`, thinking disabled, maximum one schema/grounding repair.
- Retrieval and generation schemas, alias registries, and parameter registries are versioned in this repository.
- Random seeds and learned-model metadata are recorded with the V6 artifacts and stage scripts.
- Dataset text files are normalized to LF and protected by `.gitattributes` for byte-stable hashing.
- No API key, local environment file, cache, private item-level evaluation detail, or formal prediction output is part of this release.
