# TEF-RAG v6 validation ablations

All four ablations use only the frozen validation split (480 queries). The
Full reference is the frozen Stage3D validation result. Pair budget is 32,
search pool is 30, candidate-bank version is
`stage3b-full5-top15-swap-v1`, and relation prompt/threshold remain frozen.

| Variant | Recall@5 | nDCG@5 | Complete@5 | FlowComplete@5 | Edge Recall |
|---|---:|---:|---:|---:|---:|
| Full TEF-RAG | 0.756667 | 0.688548 | 0.406250 | 0.404167 | 0.476389 |
| w/o Learned Pair Proposal | 0.749375 | 0.683225 | 0.406250 | 0.402083 | 0.451389 |
| w/o Relation Graph Features | 0.718368 | 0.660051 | 0.375000 | 0.366667 | 0.421354 |
| w/o Hard-Negative Mining | 0.674792 | 0.604210 | 0.287500 | 0.283333 | 0.390972 |
| w/o Nonlinear Set Ranker | 0.706979 | 0.696470 | 0.318750 | 0.312500 | 0.425694 |

## Delta vs Full

| Variant | ΔRecall@5 | ΔFlowComplete@5 |
|---|---:|---:|
| w/o Learned Pair Proposal | -0.007292 | -0.002083 |
| w/o Relation Graph Features | -0.038299 | -0.037500 |
| w/o Hard-Negative Mining | -0.081875 | -0.120833 |
| w/o Nonlinear Set Ranker | -0.049688 | -0.091667 |

The Stage3A result is reused directly. Its frozen proposer is semantically
comparable to Full: learned proposal, pair budget 32, search pool 30, relation
prompt `tef-v6-stage2a-relation-v7`, and threshold 0.6. No fifth ablation or
hyperparameter sweep was performed.

The graph-feature ablation removes 19 relation/graph-derived set features and
retains 43 node/relevance/temporal/role/diversity features. It retrains the
same 64-32 MLP with the same RankNet objective, split, normalizer policy, and
one-round hard-negative mining. Relation outputs remain available, so its Edge
Recall is reported rather than coerced to zero.

The heuristic Top32 ablation required 1,872 missing validation-only relation
judgments to complete the frozen cache. They were requested serially through
the authorized official endpoint with the frozen prompt/model and 4-second
interval; no test data or sealed evaluator was accessed.

Machine-readable metrics and provenance are in
`results/v6/ablation/metrics.json` and `results/v6/ablation/manifest.json`.
