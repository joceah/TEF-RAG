# TEF-RAG v6 Semantic Benchmark v1 — Review Summary

- Frozen protocol: `b0e6e004378e7d7f29cabece1efa6b2c30489e9b`
- Dataset status: `SEMANTICALLY_AUTHORED_CANDIDATE_PENDING_BLIND_SECOND_REVIEW`
- 400 chains / 1200 primary intents / 2400 query rows / 100 assets
- Evidence records: 3888
- Flow-ambiguity-authored chains: 69
- Test gold public: no
- Sealed test records: 480
- Sealed test SHA256: `477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3`
- Target-method runs: 0

## Difficulty gates

- Challenge RECENCY_SOLVABLE_AT_5 / Latest-5 Complete@5: `0.1217` (threshold `<=0.40`, PASS)
- Challenge Latest-5 FlowComplete@5: `0.1100`
- Realistic Latest-5 Complete@5: `0.7700`
- Routine stratum Latest-5 Complete@5: `1.0000`

All eight Challenge major strata remain at or below the preregistered `0.50` recency-solvable ceiling.

## Validation second blind semantic review — COMPLETE

A second validation review was completed on 2026-09-16 without seeing validation pass-1 item-level verdicts or reasoning before pass-2 judgments were frozen.

- validation chains reviewed: `80 / 80`
- pass: `80`
- `REVIEW_UNRESOLVED`: `0`
- pass-1 / pass-2 disagreements after post-judgment comparison: `0`
- reviewer: `GPT-5.6 Sol`
- item-level public audit: `metadata/validation_second_blind_review.json`
- audit SHA256: `00dc11c5b178c4ba774194a59e563032199640be9e47fd35c3edf6c13e608046`

The review covered scenario semantics, public-source/modeling-choice boundaries, required-group semantics, canonical flow/relation semantics, bitemporal visibility, procedure applicability, late-arrival cutoffs, persistent uncertainty and physical/numerical plausibility.

## Test supplemental audit — PASS, but not formal blind-review credit

The sealed test evaluator was verified against the previously published SHA256 and a full supplemental semantic audit covered all `80` test chains / `480` query rows. No structural or semantic unresolved item was found (`80 PASS / 0 REVIEW_UNRESOLVED`). No test item-level gold, canonical flow or reviewer reasoning is published here.

However, during sealed-artifact discovery in the same 2026-09-16 conversation, Library search snippets exposed first-pass `PASS` verdicts for some test chains before independent pass-2 judgment. The frozen protocol explicitly requires the formal second reviewer to be blind to pass-1 verdict/reasoning before judgment. Therefore this supplemental audit **must not** be counted as the protocol-required formal test second blind review.

The remaining review step is a fresh sealed test review context that receives the sealed evaluator but no pass-1 verdict/reasoning. Only after that pass has `0 REVIEW_UNRESOLVED` and disagreements are resolved may the benchmark be re-hashed and marked final/sealed.

## Semantic corrections relative to the 16-chain pilot

1. complementary evidence is split into separate required groups; OR alternatives are only equivalent records;
2. flow relation types are semantic rather than a single `supports_next`;
3. late-arrival cases have no already-visible evidence that independently reveals the final correction;
4. procedures carry machine-readable version/validity/supersession/model-scope metadata;
5. source provenance explicitly distinguishes public-source-backed reference facts from modeling choices;
6. test item labels/gold/flow/review reasoning are withheld from the public development branch.

## Final-seal boundary

`final_seal.status = BLOCKED_PENDING_FORMAL_TEST_SECOND_BLIND_REVIEW`.

This is a review-process integrity blocker, not a discovered benchmark-content failure. The candidate must remain non-final until the frozen protocol's test blindness requirement is satisfied. No target retrieval method has been run.
