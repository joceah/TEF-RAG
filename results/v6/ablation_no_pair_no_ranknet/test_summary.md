# w/o Pair Proposal + Nonlinear Ranker — retrieval test

The frozen joint ablation was run on all 480 test queries. Predictions were saved before the test evaluator was read. The same rule-based `improved` pair prefilter, relation-aware greedy evidence-set selector, Top-30 search pool, Top-5 budget, relation prompt v7, `deepseek-chat` model, temperature 0, confidence threshold 0.6, and `tef_rag_v6.evaluation.evaluate_prediction` were used. Neither the learned pair proposer nor nonlinear RankNet was loaded.

| Variant | Recall@5 | nDCG@5 | Complete@5 | FlowComplete@5 |
| --- | ---: | ---: | ---: | ---: |
| Full TEF-RAG (existing sealed test result) | 0.7228 | 0.6231 | 0.3188 | 0.3146 |
| **w/o Pair Proposal + Nonlinear Ranker** | **0.5835** | **0.6034** | **0.1625** | **0.1521** |

The full result is read from the existing sealed test metrics; it was not rerun. The joint ablation is lower by 0.1393 Recall@5, 0.0197 nDCG@5, 0.1563 Complete@5, and 0.1625 FlowComplete@5. No separate test results for the two single ablations were generated here.

The initial preflight found 5,117 missing judgments among 11,098 pair lookups. The first API-backed attempt stopped near the end after an incomplete DeepSeek JSON response; successfully judged pairs remained cached. A second attempt completed all 480 queries using 10,879 cache hits and 219 new judgments (38 requests, one retry **during that second attempt**). The request count for the interrupted attempt was not recorded, so 38 is not the total request count across both attempts. API cache, progress checkpoint, local.env, and temporary logs are excluded from Git.

Cache-only verification reproduced all 480 saved Top-5 selections, the exact `improved` pair lists, greedy selector choices, and candidate bank sizes. It also checked unique Top-5 IDs, temporal availability, asset eligibility, no relation-judging failures, and the prediction hash. The original evaluator produced the aggregate metrics in `test_metrics.json` from the frozen predictions and the SHA-checked test evaluator.

Commands:

```powershell
D:\Anaconda3\python.exe -m scripts.run_tef_rag_v6_joint_ablation preflight --split test
D:\Anaconda3\python.exe -m scripts.run_tef_rag_v6_joint_ablation run --split test --allow-api
D:\Anaconda3\python.exe -m scripts.run_tef_rag_v6_joint_ablation evaluate-test
D:\Anaconda3\python.exe -m scripts.run_tef_rag_v6_joint_ablation verify-test
```
