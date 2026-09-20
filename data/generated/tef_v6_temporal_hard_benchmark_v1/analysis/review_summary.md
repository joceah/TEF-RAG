# TEF-RAG v6 Semantic Benchmark v1 — Final Review Summary

- Frozen protocol: `b0e6e004378e7d7f29cabece1efa6b2c30489e9b`
- Dataset status: `FINAL_SEALED`
- Positioning: public-source-grounded, AI-assisted synthetic benchmark
- 400 chains / 1,200 primary intents / 2,400 query rows / 100 assets
- Evidence records: 3,888
- Test gold at formal seal: not public
- Historical sealed test records: 480
- Historical sealed test SHA-256: `477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3`
- Target-method runs at authoring/review: 0

## Validation formal second blind semantic review

Completed 2026-09-16: 80/80 chains PASS, 0 `REVIEW_UNRESOLVED`, 0 pass-1/pass-2 disagreements. Public validation audit SHA-256: `00dc11c5b178c4ba774194a59e563032199640be9e47fd35c3edf6c13e608046`.

## Test formal second blind semantic review

A fresh reviewer context received the sealed evaluator through the isolated review workflow. Before pass-1 reviewer information was read, reviewer-result fields were excluded from the blind packet. Independent judgments were fixed before comparison.

- test chains reviewed: 80/80
- query rows covered: 480
- PASS: 80
- `REVIEW_UNRESOLVED`: 0
- independent private artifact SHA-256: `6e274720b45f8fe1d23b9e662cd294168acbcce91cb3a37e11000e2d6bb1e3f7`
- pass-1/pass-2 agreement: 80
- disagreement: 0
- resolved disagreements: 0
- semantic benchmark item changes: none

Review scope covered query/gold scenario semantics, paraphrase consistency, required-group semantics, typed flow/relation semantics, cutoff/late-arrival semantics, procedure applicability/versioning, and persistent uncertainty.

## Deterministic final validation

The formal seal verified 80 test chains / 480 evaluator rows / 3 intents × 2 paraphrases per chain; required-group and flow endpoint references were valid; temporal-visibility constraints held; the sealed evaluator SHA matched; test gold was not public at seal time; and target-method runs were zero.

## Post-evaluation release

The exact historical 480-row evaluator was kept sealed through the formal experiment. After predictions and results were frozen, its original bytes were released for reproducibility at `data/retrieval/tef_v6_temporal_hard_benchmark_v1/public/test_evaluator.jsonl`. The historical manifest is intentionally unchanged and continues to describe the formal-seal state. Item-level second-review reasoning remains private.

## Final seal

`final_seal.status = COMPLETE`. The benchmark is released as **TEF-RAG v6 Semantic Benchmark v1**, without claims of expert review, field certification, or real-world provenance.
