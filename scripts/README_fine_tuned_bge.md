# Fine-tuned BGE baseline

This baseline adapts `BAAI/bge-reranker-v2-m3` using document-level relevance supervision from the development split only. Acceptable evidence IDs from required evidence groups are positives; high-ranked eligible BM25 Top-30 nonpositives are negatives. Relation and evidence-flow labels are not used.

The released experiment used rank-8 low-rank adapters on the attention query/value projections and the classification head, trained for two epochs with seed `20261008`. Checkpoint selection used validation nDCG@5 with Recall@5 as a tie-breaker. Test annotations were not opened until selection was complete.

Run locally from a downloaded model snapshot:

```bash
python -m scripts.run_fine_tuned_bge train --model-path /path/to/bge-reranker-v2-m3
python -m scripts.run_fine_tuned_bge test --model-path /path/to/bge-reranker-v2-m3
```

Published aggregate metrics are stored in `results/fine_tuned_bge_metrics.json`. The public test predictions are stored in `data/retrieval/predictions/fine_tuned_bge.json`. Large intermediate checkpoints are intentionally not committed.
