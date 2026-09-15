# TEF-RAG v6 Semantic Benchmark v1 — Final Review Summary

- Frozen protocol: `b0e6e004378e7d7f29cabece1efa6b2c30489e9b`
- Dataset status: `FINAL_SEALED`
- Positioning: public-source-grounded, AI-assisted synthetic benchmark
- 400 chains / 1200 primary intents / 2400 query rows / 100 assets
- Evidence records: 3888
- Test gold public: no
- Sealed test records: 480
- Sealed test SHA256: `477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3`
- Target-method runs: 0

## Validation formal second blind semantic review

Completed 2026-09-16: 80/80 chains PASS, 0 `REVIEW_UNRESOLVED`, 0 pass-1/pass-2 disagreements. Public validation audit SHA256: `00dc11c5b178c4ba774194a59e563032199640be9e47fd35c3edf6c13e608046`.

## Test formal second blind semantic review

A fresh reviewer context received the sealed evaluator through exact Library listing and raw materialization. Before any pass-1 reviewer information was read, a sanitized blind packet was created programmatically with `first_pass_review` and equivalent reviewer-result fields removed. Independent judgments were then fixed before comparison.

- test chains reviewed: 80/80
- query rows covered: 480
- PASS: 80
- `REVIEW_UNRESOLVED`: 0
- independent private artifact SHA256: `6e274720b45f8fe1d23b9e662cd294168acbcce91cb3a37e11000e2d6bb1e3f7`
- pass-1/pass-2 agreement: 80
- disagreement: 0
- resolved disagreements: 0
- semantic benchmark item changes: none

Review scope covered query/gold scenario semantics, paraphrase consistency, required-group semantics, typed flow/relation semantics, cutoff/late-arrival semantics, procedure applicability/versioning, and persistent uncertainty. Previously completed source-boundary and physical/numerical audits were not redundantly repeated.

## Deterministic final validation

Fresh sealing checks confirm 80 test chains / 480 evaluator rows / 3 intents × 2 paraphrases per chain; required-group and flow endpoint references are valid; temporal-visibility constraints remain valid; sealed evaluator SHA integrity passes; public test gold is false; target-method runs are zero. No benchmark semantic item changed during this sealing pass, so dataset artifacts were not regenerated.

## Confidentiality boundary

The sealed evaluator and test item-level second-pass artifact remain private. Public GitHub contains only test queries/evidence/limited chain metadata, aggregate review/QC, and hashes. Test gold, required groups, canonical flow, and item-level reviewer reasoning are not published.

## Final seal

`final_seal.status = COMPLETE`. The benchmark is formally released as **TEF-RAG v6 Semantic Benchmark v1**, with the positioning above and without claims of expert review, field certification, or real-world provenance.
