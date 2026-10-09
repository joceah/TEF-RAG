# Final set ranker nDCG tuning

Base: `origin/release/tef-rag-v6-paper` at `7521229b20e0fa70d4cb42b16f32ebea01778364`. Only the final nonlinear set ranker was tuned. Development gold supplied training preferences; validation selected the model; one frozen test evaluation followed. No generation or upstream model retraining occurred.

The matching per-pair relation judgments were found under `D:\electric-project\.github_export\TEF-RAG\.cache`, not in the historical paper-release `results/v6` tree. Development/validation used the historical `tef_rag_v6_llm_relation` cache with frozen model `deepseek-v4-flash`; test used the original sealed-test `tef_rag_v6_test_relation` cache with `deepseek-chat`. Coverage was development 43,746/43,746, validation 13,030/13,030, and test 14,862/14,862 exact fingerprints. `forbidden_http` was active; new LLM calls and HTTP requests were both zero.

The original Stage3D checkpoint reproduced its validation metrics before tuning. The final frozen trial, `r256_adamw_1e4`, used `[256,128,64]`, AdamW, learning rate `1e-4`, weight decay `1e-5`, batch size 128, and seed 20260916. Its preference data retained original flow-complete versus non-flow-complete pairs and added pairs with different nDCG within the same flow/complete status, all from existing development candidate sets. Eight finite trials covered `[64,32]`, `[128,64]`, `[128,64,32]`, and `[256,128,64]`, Adam and AdamW, learning rates `1e-4`/`3e-4`/`1e-3`, weight decay `0`/`1e-5`/`1e-4`, and batches 128/256/512. Full trial and epoch metrics are in `validation_trials.json`; the Pareto frontier is saved separately.

| Validation variant | Recall@5 | nDCG@5 | Complete@5 | FlowComplete@5 |
| --- | ---: | ---: | ---: | ---: |
| Original Stage3D | 0.7567 | 0.6885 | 0.4063 | 0.4042 |
| Selected ranker | **0.7670** | **0.7269** | **0.4063** | **0.4063** |

| Final test variant | Recall@5 | nDCG@5 | Complete@5 | FlowComplete@5 |
| --- | ---: | ---: | ---: | ---: |
| Original TEF-RAG | 0.7228 | 0.6231 | 0.3188 | 0.3146 |
| Selected ranker | **0.7236** | **0.6483** | **0.3063** | **0.3042** |

The selected ranker gained about +0.0008 Recall and +0.0252 nDCG versus original TEF-RAG test, with about -0.0125 Complete and -0.0104 FlowComplete. Its nDCG was 0.0018 below Fine-tuned BGE's 0.6501. No parameters were changed after the test result.

Commands:

```text
D:\Anaconda3\python.exe -m scripts.run_tef_rag_v6_ranknet_ndcg_tuning materialize
D:\Anaconda3\python.exe -m scripts.run_tef_rag_v6_ranknet_ndcg_tuning tune
D:\Anaconda3\python.exe -m scripts.run_tef_rag_v6_ranknet_ndcg_tuning preflight-test
D:\Anaconda3\python.exe -m scripts.run_tef_rag_v6_ranknet_ndcg_tuning test
```

The validation materialization was resumed once after correcting the empty-bank fallback matrix; the completed development pair matrix was reused. The final test predictions were generated once. The first evaluation attempt stopped before reading sealed gold because an older evaluator file had the wrong SHA; the SHA-matching evaluator was then used for one aggregate evaluation.
