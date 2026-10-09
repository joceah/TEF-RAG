# Final set ranker optimization: cache preflight blocked

Base: `origin/release/tef-rag-v6-paper` at `7521229b20e0fa70d4cb42b16f32ebea01778364`.

The configured relation cache at `D:\electric-project\ranknet-ndcg-tuning\.cache\tef_rag_v6_llm_relation` is absent (0 files, 0 bytes). A read-only replay of the frozen learned pair proposer found 43,746 required development pair lookups and 13,030 validation pair lookups, all missing from that path. Example missing query and evidence IDs are saved in `cache_preflight.json`.

A separate historical cache exists under `.github_export/TEF-RAG/.cache/tef_rag_v6_llm_relation` (81,641 files; 20,543,180 bytes), but it is outside the configured path and exact fingerprint coverage for this checkout was not established. It was not used for training or evaluation.

Following the cache-miss stop rule, no ranker training, validation tuning, or test evaluation occurred. No test gold or generation was used; `local.env` was not read; new LLM calls and HTTP requests were both zero. Therefore there are no selected validation metrics, tuned checkpoint, test predictions, or test metrics to report.

The independent RankNet architecture fix was completed: `hidden_sizes` now controls the MLP layers, with the default `[64, 32]` retaining the original parameter layout and seeded initialization. Stage3D training now passes its config value to `RankNetMLP`; the checkpoint loader supports existing metadata and configurable architectures. The Stage3D tests pass. Architecture, objective, optimizer, and model selection sweeps remain unrun until the frozen cache is restored.
