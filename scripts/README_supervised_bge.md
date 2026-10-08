# Supervised BGE reranker baseline

This experiment starts from the same `BAAI/bge-reranker-v2-m3` checkpoint as the frozen off-the-shelf BGE baseline. The retrieval path is unchanged: eligible evidence, BM25 Top 30, BGE scoring, Top 5.

The training script reads only development queries, development retrieval gold, validation queries, validation retrieval gold, and the public evidence corpus. It derives binary document relevance from the union of `acceptable_evidence_ids` across each query's required groups. It never reads flow edges or their relation labels for learning. The negatives are the highest BM25 ranked eligible false positives from the same query's Top 30. All eligible positives are included, even when BM25 does not retrieve them in its Top 30. The random seed is fixed. The BGE encoder stays frozen and low rank adapters on query/value projections plus the classification head are trained with binary cross entropy. This is a supervised task adaptation of the same CrossEncoder; no graph labels are injected.

Each epoch is evaluated on validation with the same Top 30 candidate pool. Selection uses validation nDCG@5 and Recall@5 as tie breaker. The test action requires the selected checkpoint manifest and checks its SHA-256 before reading test queries or the official evaluator. The generation action requires retrieval test completion and uses only that method's Top 5 evidence IDs, the frozen prompt and `deepseek-flash` client, and one optional repair. Gold is loaded only by the generation evaluation action.

Run with the original BGE model snapshot and a CUDA capable Python environment:

```powershell
python -m scripts.run_supervised_bge train --model-path D:\path\to\bge-reranker-v2-m3
python -m scripts.run_supervised_bge test --model-path D:\path\to\bge-reranker-v2-m3
python -m scripts.run_supervised_bge_generation generate
python -m scripts.run_supervised_bge_generation evaluate
```

The generation runner reads `API_KEY` from the repository or parent `local.env` through the existing `tef_rag_v6.generation_runner.read_env` implementation. It never writes the key to result artifacts. `results/v6/supervised_bge_reranker/` contains the manifest, validation and test metrics, predictions, and the generation output. Checkpoint adapters and API cache are local runtime files; neither belongs in Git.
