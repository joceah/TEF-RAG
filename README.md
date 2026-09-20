# TEF-RAG

TEF-RAG (Temporal Evidence Flow Retrieval-Augmented Generation) is a reproducible benchmark and implementation for maintenance questions whose answer depends on event time, evidence availability, procedure versions, and ordered actions. **TEF-RAG v6 is the final implementation used for the paper experiments.**

## Repository layout

- `tef_rag_v6/` — V6 retrieval, temporal constraints, relation scoring, rankers, and frozen generation metrics.
- `baseline_adapters/` — comparison retrieval adapters used by the V6 study.
- `scripts/` — benchmark materialization, V6 stage runners, validators, and public retrieval/generation evaluators.
- `data/retrieval/` — reader-facing retrieval benchmark, released historical test evaluator, and frozen formal test predictions.
- `data/generation/` — development, validation, and post-evaluation test generation gold plus schema/registries.
- `artifacts/v6/` — small learned-model and feature artifacts required by the final V6 stages.
- `tests/` — release-tree unit, regression, and dataset tests.
- `paper/` — paper materials and final aggregate reference metrics.

The deterministic transport files under `data/generated/tef_v6_*` are retained for provenance and validator compatibility. Reader-facing materialized data live under `data/retrieval/` and `data/generation/`.

## Installation

Python 3.11 or newer is required.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
python -m pip install -e ".[test]"
python -m pytest -q
```

For the semantic/learned V6 stages, install:

```bash
python -m pip install -e ".[semantic,ranknet]"
```

For full baseline reproduction, install the additional runtime stack with:

```bash
python -m pip install -e ".[reproduce]"
```

The frozen baseline environment recorded `numpy 2.4.6`, `torch 2.14.0+cu130`, `transformers 4.57.6`, `sentence-transformers 5.7.0`, `faiss-cpu 1.15.1`, `ncls 0.0.68`, and `openai 3.14.1`. The `reproduce` extra pins the portable packages where appropriate; install the PyTorch build suitable for your CPU/CUDA platform if the default wheel is not appropriate.

LLM-backed stages require an API key supplied at runtime. Use an untracked `local.env` or environment variable; never commit credentials.

## Datasets

### Retrieval

`data/retrieval/tef_v6_temporal_hard_benchmark_v1/public/` contains 400 chains, 2,400 queries, the shared evidence corpus, development/validation labels, and the exact 480-row historical test evaluator. The test evaluator remained sealed throughout model development and the formal test run. It was released only after predictions and results were frozen for reproducibility.

Historical evaluator SHA-256:

```text
477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3
```

The historical benchmark manifest intentionally still records `public_test_gold=false`, because that describes the state at formal sealing time.

Validate the benchmark and reproduce the frozen retrieval test metrics with:

```bash
python -m scripts.validate_tef_v6_semantic_benchmark_v1
python -m scripts.validate_tef_rag_v6_public_retrieval
python -m scripts.evaluate_tef_rag_v6_public_retrieval
```

The public retrieval evaluator uses the exact released evaluator and the frozen formal predictions under `data/retrieval/frozen_test_predictions/`, and fails closed on hash, query coverage/order, evidence identity, duplicate IDs, and temporal visibility.

### Generation

`data/generation/` contains the structured generation schema/registries and development, validation, and test gold/index files. The test gold was released after the blind evaluation completed.

The two test artifacts intentionally preserve different historical byte conventions:

| file | byte convention | SHA-256 |
| --- | --- | --- |
| `gold_test.jsonl` | audited historical source bytes (CRLF) | `dccf5a831b9b145d5aab26288088d14d2e9af6fafd06d4eced3a22983a7c9aea` |
| `gold_test_index.jsonl` | canonical public LF | `8433880d300e541713aba7eae86564bcb705f6f9c638043a66d7262f5b195d35` |

`.gitattributes` preserves the byte-stable historical files so their published hashes survive fresh checkouts.

Validate the generation dataset with:

```bash
python -m scripts.validate_tef_rag_v6_public_generation
```

## Reproduce retrieval results

The already-frozen formal test can be reproduced without external models or API calls:

```bash
python -m scripts.evaluate_tef_rag_v6_public_retrieval
```

To reproduce the development/validation baseline pipeline from source, first prepare the external model/runtime inputs used by the original run:

- BGE reranker: `BAAI/bge-reranker-v2-m3`, frozen revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`.
- Nomic embedding model: `nomic-ai/nomic-embed-text-v1.5`; the formal freeze records the local snapshot hash `sha256:9e7d262b1fe5ea350782829496efa831901b77486bbde1cea54a4c822d010d5c`.
- TA-RAG upstream: `https://github.com/kwunhang/TA-RAG`, frozen commit `9e5e28a9e7ddad7d6d022c4d3533dbca2aff03b9`.

Example checkout:

```bash
git clone https://github.com/kwunhang/TA-RAG ../TA-RAG
git -C ../TA-RAG checkout 9e5e28a9e7ddad7d6d022c4d3533dbca2aff03b9
```

Run development first, then validation with the same frozen external inputs:

```bash
python -m scripts.run_tef_rag_v6_baseline_suite development \
  --bge-path /path/to/bge-reranker-v2-m3 \
  --nomic-path /path/to/nomic-embed-text-v1.5 \
  --ta-upstream ../TA-RAG \
  --ta-base-url https://api.deepseek.com \
  --ta-model deepseek-chat

python -m scripts.run_tef_rag_v6_baseline_suite validation \
  --bge-path /path/to/bge-reranker-v2-m3 \
  --nomic-path /path/to/nomic-embed-text-v1.5 \
  --ta-upstream ../TA-RAG \
  --ta-base-url https://api.deepseek.com \
  --ta-model deepseek-chat
```

Set `TA_RAG_API_KEY` before running TA-RAG. Development writes the frozen baseline configuration consumed by validation. The published frozen test predictions remain the authoritative artifacts for reproducing the paper's test table.

The V6 stage runners are also retained for method reconstruction and ablation work:

```bash
python -m scripts.run_tef_rag_v6_stage1 --help
python -m scripts.run_tef_rag_v6_stage2a --help
python -m scripts.run_tef_rag_v6_stage3d --help
```

## Reproduce generation evaluation

The formal generator consumes the frozen selected evidence from each retrieval method. Materialize only the frozen inputs first:

```bash
python -m scripts.materialize_tef_v6_semantic_benchmark_v1
python -m scripts.materialize_tef_rag_v6_generation_inputs
python -m scripts.run_tef_rag_v6_generation_eval preflight
```

These steps verify committed benchmark/prediction hashes and make local ignored runtime inputs. They do not rerun retrieval or call an API.

To regenerate model outputs from scratch (this incurs API usage), configure the required DeepSeek key and run:

```bash
python -m scripts.run_tef_rag_v6_generation_eval generate --all
python -m scripts.run_tef_rag_v6_generation_eval freeze
```

For public scoring of prediction files against the released test gold/index:

```bash
python -m scripts.evaluate_tef_rag_v6_public_generation --predictions path/to/predictions
```

Each prediction file is named `<method>.jsonl` and contains `query_id`, input/selected evidence IDs, and a generation object. The public evaluator expects the five methods `bm25`, `bge_reranker`, `temporal_bm25`, `ta_rag`, and `tef_rag_stage3d`, and requires exact 480-query coverage.

## Reference paper metrics

- Retrieval: [`paper/results/final_retrieval_metrics.json`](paper/results/final_retrieval_metrics.json)
- Generation: [`paper/results/final_generation_metrics.json`](paper/results/final_generation_metrics.json)

These files contain aggregate reference metrics only; private item-level evaluation details are not included.

## Reproducibility notes

- Generator model: `deepseek-flash`, official endpoint, temperature `0`, thinking disabled, maximum one schema/grounding repair.
- Retrieval and generation schemas, alias registries, parameter registries, seeds, model metadata, and frozen hashes are versioned in the repository.
- Ordinary text files use LF. A small number of historical sealed/frozen artifacts are marked binary in `.gitattributes` so their audited original bytes are preserved exactly.
- No API key, local environment file, cache, or private item-level review/evaluation detail is included in the release.
- The V6 test evaluator/gold was hidden during the formal blind run and released only after completion; future method-development work should use a new sealed test split rather than treating this released test set as unseen.
