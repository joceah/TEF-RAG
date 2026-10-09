# w/o Pair Proposal + Nonlinear Ranker

Validation-only joint ablation on 480 public queries, based on
`origin/release/tef-rag-v6-paper` at `7521229b20e0fa70d4cb42b16f32ebea01778364`.

| Variant | Recall@5 | nDCG@5 | Complete@5 | FlowComplete@5 |
| --- | ---: | ---: | ---: | ---: |
| Full TEF-RAG | 0.7567 | 0.6885 | 0.4063 | 0.4042 |
| w/o Pair Proposal | 0.7494 | 0.6832 | 0.4063 | 0.4021 |
| w/o Nonlinear Ranker | 0.7070 | 0.6965 | 0.3188 | 0.3125 |
| **w/o Pair Proposal + Nonlinear Ranker** | **0.6873** | **0.6860** | **0.2958** | **0.2875** |

The first three rows are existing paper results (`paper/sections_en_v3/05_remaining_outline.tex`), not reruns. The joint run uses the existing `improved` rule pair prefilter from the single w/o Pair Proposal ablation and the existing relation-aware greedy evidence-set selector from the single w/o Nonlinear Ranker ablation. The learned pair proposer and nonlinear RankNet are never loaded. The relation graph, Stage3B candidate bank, Top-30 search pool, Top-5 output limit, and original evaluator are retained.

The frozen pair budget is 32, but the existing `improved` prefilter implements an effective cap of 24 (`max(24, max_pairs_per_query)`). This joint run preserves that exact fallback behavior. It judged 10,130 pairs using the frozen `deepseek-chat` prompt v7, temperature 0, and confidence threshold 0.6. The accessible prior cache had zero matching judgments, so the run made 1,358 API requests (34 retries); the API cache is excluded from Git. Relation judgments may differ slightly from an earlier run despite temperature 0.

The self-check independently verified all 480 predictions, unique Top-5 IDs, temporal and asset eligibility, the exact `improved` pair lists, recomputed greedy choices, the original evaluator metrics, and the prediction hash. No test split or downstream generation was run.

Run command: `D:\Anaconda3\python.exe -m scripts.run_tef_rag_v6_joint_ablation run --allow-api`
