# TEF-RAG v6 retrieval test: four single ablations

These are **test** results on the 480 frozen test queries, evaluated with the original `tef_rag_v6.evaluation.evaluate_prediction` and the test evaluator whose SHA-256 is `477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3`. Predictions were written and hashed before this evaluator was read. The published ablation table contains validation results only; the four test rows below are new, post hoc evaluations and should not be presented as part of the original one-shot sealed test.

| Variant | Recall@5 | nDCG@5 | Complete@5 | FlowComplete@5 |
| --- | ---: | ---: | ---: | ---: |
| Full TEF-RAG (existing sealed test) | 0.7228 | 0.6231 | 0.3188 | 0.3146 |
| w/o Pair Proposal | 0.6829 | 0.5870 | 0.2667 | 0.2604 |
| w/o Graph Features | 0.6558 | 0.5723 | 0.2375 | 0.2354 |
| w/o Hard Negatives | 0.6540 | 0.5557 | 0.1979 | 0.1917 |
| w/o Nonlinear Ranker | 0.6242 | 0.6324 | 0.2042 | 0.1938 |
| w/o Pair Proposal + Nonlinear Ranker (existing joint test) | 0.5835 | 0.6034 | 0.1625 | 0.1521 |

The other pre-existing retrieval baselines on this same test split are:

| Baseline | Recall@5 | nDCG@5 | Complete@5 | FlowComplete@5 |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 0.3791 | 0.3915 | 0.0563 | 0.0563 |
| BGE reranker | 0.2916 | 0.3070 | 0.0417 | 0.0417 |
| Temporal BM25 | 0.4591 | 0.4955 | 0.0792 | 0.0792 |
| TA-RAG | 0.2769 | 0.2907 | 0.0375 | 0.0375 |

The Full row and four baseline rows are read from the pre-existing sealed test `metrics.json` (SHA-256 `5d6a59c0961fb467ed44f11557cdb299e872ba53dbe656dbe13e14053b7f632b`); the joint row is read from the existing joint ablation test metrics. None was rerun for this work. All four single-ablation prediction files have 480 unique ordered query IDs, at most five unique temporally available evidence IDs per query, and matching asset IDs. All relation judgments were cache hits: 11,098/11,098 for w/o Pair Proposal and 14,862/14,862 for each of the other three. These four test runs made zero new API requests. The original frozen Full test predictions were reproduced for a ten-query configuration check.

The pair-proposal ablation uses the existing `improved` rule pair prefilter and the frozen full RankNet. The nonlinear-ranker ablation uses the learned pair proposer and the preceding greedy evidence-set selector. The graph-feature ablation keeps relation judging, the relation graph, candidate-bank construction, and the two RankNet training rounds; it removes only 19 relation-graph-derived RankNet inputs. The hard-negative ablation retains the first RankNet training round only. Both restored models were trained on 1,440 development queries with the original seed, architecture, optimizer, and development relation cache; they made no API requests. Their validation checks reproduce the paper's four displayed metrics exactly to four decimals: graph-free `0.7184 / 0.6601 / 0.3750 / 0.3667`; round-0 `0.6748 / 0.6042 / 0.2875 / 0.2833`.

Commands used:

```powershell
D:\Anaconda3\python.exe -m scripts.train_tef_rag_v6_single_ablation_models train
D:\Anaconda3\python.exe -m scripts.train_tef_rag_v6_single_ablation_models validate
D:\Anaconda3\python.exe -m scripts.run_tef_rag_v6_single_ablation_tests predict <variant>
D:\Anaconda3\python.exe -m scripts.run_tef_rag_v6_single_ablation_tests evaluate <variant>
D:\Anaconda3\python.exe -m scripts.run_tef_rag_v6_single_ablation_tests verify <variant>
```

`<variant>` was run separately for `no_pair_proposal`, `no_graph_features`, `no_hard_negatives`, and `no_nonlinear_ranker`. Full predictions, aggregate metrics, and a manifest for each variant are saved alongside this summary. The two restored model files, normalization files, and training manifest are saved in `artifacts/v6/single_ablation_tests` and this results directory. API caches, `local.env`, and temporary files are excluded from Git.
