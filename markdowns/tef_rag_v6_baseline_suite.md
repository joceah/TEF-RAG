# TEF-RAG v6 frozen baseline suite

## Implementation

All baselines begin from the same per-query deployment-visible snapshot: matching public asset scope, `event_time <= query_time`, and `available_at <= query_time`, including the frozen procedure validity/model-scope rules. The runner projects raw records to public inference fields before invoking any method. It never accepts a test split.

- **BM25** reuses `tef_rag_v6.pipeline.BM25Index` and the frozen mixed Latin/Han tokenizer (`k1=1.5`, `b=0.75`). It independently indexes the complete safe snapshot and returns five original evidence IDs.
- **BM25 + BGE-Reranker** independently retrieves BM25 Top-30, then scores only `[query_text, evidence_text]` pairs with `BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`.
- **Temporal-BM25** uses `lambda * normalized_bm25 + (1-lambda) * temporal_score`. Its deterministic parser handles explicit years/ranges, directional before/after phrases, and current/latest/recent phrases. Queries without explicit temporal intent receive a constant temporal score and therefore preserve BM25 order.
- **TA-RAG** is pinned to `kwunhang/TA-RAG@9e5e28a9e7ddad7d6d022c4d3533dbca2aff03b9`. The compatibility layer invokes the official `temporal_process_sentence`, anchors its `date.today()` reference to each query's `query_time`, maps point events to one-second half-open intervals, uses NCLS filtering, `nomic-ai/nomic-embed-text-v1.5` normalized embeddings, a per-snapshot FAISS index, and the official BGE reranking stage. Provenance remains the original evidence ID. The user-authorized LLM substitution is frozen as official DeepSeek `deepseek-chat`, temperature 0, at `https://api.deepseek.com`; the runtime API key is never persisted. Calls were serial with a four-second minimum start interval.

## Development selection

Temporal-BM25 compared exactly `lambda in {0.25, 0.50, 0.75}`. The frozen selection rule is FlowComplete@5, then Complete@5, then Recall@5, then the smaller temporal weight. `lambda=0.25` won directly on the primary metric.

| Method | Recall@5 | Hit@5 | nDCG@5 | Complete@5 | FlowComplete@5 | Edge Recall |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 0.455903 | 0.915278 | 0.472405 | 0.080556 | 0.079861 | 0.000000 |
| BGE-Reranker | 0.399687 | 0.809722 | 0.418820 | 0.054167 | 0.053472 | 0.000000 |
| Temporal-BM25 (0.25) | 0.525475 | 0.931944 | 0.546944 | 0.111111 | 0.109028 | 0.000000 |
| TA-RAG | 0.375498 | 0.761111 | 0.396275 | 0.049306 | 0.049306 | 0.000000 |

All rows use their exact frozen stacks; no fallback model or simplified TA-RAG algorithm was used.

## Frozen configuration and validation

The machine-readable source of truth is `results/v6/baseline_suite/baseline_freeze.json`. Formal validation is fail-closed unless all four development baselines completed, the manifest hash matches, and the validation marker does not already exist. Validation is permitted exactly once after a complete freeze. Frozen Stage3D metrics are read from the existing committed result; Stage3D is not retrained and no relation LLM calls are made.

| Method | Recall@5 | Hit@5 | nDCG@5 | Complete@5 | FlowComplete@5 | Edge Recall |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 0.581319 | 0.950000 | 0.595978 | 0.175000 | 0.175000 | 0.000000 |
| BGE-Reranker | 0.500694 | 0.835417 | 0.498705 | 0.122917 | 0.122917 | 0.000000 |
| Temporal-BM25 (0.25) | 0.637604 | 0.962500 | 0.644929 | 0.235417 | 0.235417 | 0.000000 |
| TA-RAG | 0.474688 | 0.789583 | 0.474884 | 0.114583 | 0.114583 | 0.000000 |
| TEF-RAG Stage3D | 0.756667 | 0.970833 | 0.688548 | 0.406250 | 0.404167 | 0.476389 |

## Runtime and dependency limitations

The official NCLS package has no Python 3.13 Windows wheel, so TA-RAG uses an ignored isolated Python 3.11 runtime with the official Windows NCLS wheel. Third-party sources, environments, models, caches, endpoint credentials, and private artifacts remain excluded from Git. CPU execution of the 568M-parameter multilingual BGE reranker and Nomic embeddings is expected to be substantially slower than GPU execution.
