# TEF-RAG v6 first sealed test

The five prediction files were completed and SHA256-frozen before the sealed
evaluator was accessed. All methods used the same 480 test queries and Top-5
output contract. This is the first and only formal sealed evaluation.

| Method | Recall@5 | Hit@5 | nDCG@5 | Complete@5 | FlowComplete@5 |
|---|---:|---:|---:|---:|---:|
| BM25 | 37.9132% | 86.4583% | 39.1465% | 5.6250% | 5.6250% |
| BGE-Reranker | 29.1597% | 75.6250% | 30.6975% | 4.1667% | 4.1667% |
| Temporal-BM25 | 45.9062% | 91.2500% | 49.5500% | 7.9167% | 7.9167% |
| TA-RAG | 27.6944% | 70.6250% | 29.0685% | 3.7500% | 3.7500% |
| TEF-RAG Stage3D | 72.2812% | 98.7500% | 62.3148% | 31.8750% | 31.4583% |

TEF-RAG Stage3D Edge Recall is 43.6458%. Edge Recall is N/A for the four
baselines because they do not emit relation predictions.

The evaluator SHA256 was
`477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3`.
The frozen prediction hashes and complete runtime accounting are recorded in
`results/v6/sealed_test/prediction_manifest.json` and
`results/v6/sealed_test/final_evaluation_manifest.json`.

`BENCHMARK_ISSUE_FOUND` remains recorded for the known non-fatal validation
review metadata bookkeeping mismatch. No method, baseline, prediction, or
benchmark setting was changed after test results were revealed.
