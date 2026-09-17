# TEF-RAG v6 Stage 3C: Pairwise Set Ranker

## 1. Motivation from Stage 3B

Stage 3B showed a large gap between the frozen candidate-bank oracle (79.17% FlowComplete on validation) and pointwise type-aware selection (18.33%). The production baseline remains Stage 3A greedy at 31.25%.

## 2. Why the pointwise objective is mismatched

The deployed decision is query-level Top-1 selection, while Stage 3B independently classified sets. Stage 3C instead learns `utility(q, S+) > utility(q, S-)` from same-query feature differences and mirrored binary examples.

## 3. Frozen candidate bank

The experiment reuses `stage3b-full5-top15-swap-v1` unchanged: exhaustive Top-15 size-5 sets, Stage 3A greedy, raw beam, and greedy single swaps over the frozen Top-30 pool. Candidate generation is gold-free.

## 4. Pairwise ranking formulation

Both rankers are zero-intercept linear logistic models (`C=1.0`, `liblinear`, seed `20260916`). Inference uses the raw linear utility, descending, then the evidence tuple as a deterministic tie-break. No pointwise probability is used.

## 5. Positive/negative construction

FlowComplete development sets are positives. Up to 30 are selected by deterministic uniform subsampling over sorted evidence tuples. Round 0 uses up to 30 highest-handcrafted-score negatives plus 10 deterministic diverse negatives. Each positive is paired with at most five negatives and each query is capped at 150 pairs. Queries without a bank positive are recorded and never receive fabricated positives.

## 6. Hard-negative mining

After Round 0, the ranker scores the complete bank. Round 1 uses up to 20 highest-ranked false positives plus 10 handcrafted hard negatives. Exactly one mining round is performed.

## 7. Type-aware vs agnostic

The agnostic model removes every `relation=` feature. The aware model retains the frozen Stage 3B relation-type count, confidence-sum, and maximum-confidence features. Both see identical banks and all other features are unchanged.

## 8. Development selection

The grouped split remains 188 train / 52 tune groups with hash `5eaff9f5…e15811`. On tune, FlowComplete was 9.62%/11.22% for agnostic/aware Round 0 and 21.79%/21.79% for Round 1. The predeclared secondary metrics selected agnostic Round 1, which was then refit on all development groups and frozen before validation.

## 9. Validation results

| Method | Recall@5 | Complete@5 | FlowComplete@5 | Edge Recall |
|---|---:|---:|---:|---:|
| Stage 3A greedy | 70.70% | 31.88% | 31.25% | 42.57% |
| Bank handcrafted | 67.73% | 27.50% | 26.88% | 38.33% |
| Stage 3B pointwise aware | 66.10% | 18.33% | 18.33% | 37.64% |
| Frozen pairwise agnostic | 68.47% | 22.71% | 21.88% | 39.29% |
| Frozen pairwise aware | 68.32% | 25.21% | 24.17% | 38.33% |

Pairwise ranking improves substantially over the pointwise classifier, but the development-selected primary remains 9.38 points below Stage 3A.

## 10. Positive-rank diagnostics

For the frozen primary, bank-positive Hit@1/3/5/10 is 21.88%/35.63%/41.67%/47.71%, including the frozen greedy fallback for queries whose bank cannot form a size-5 set. Conditional on the 380 queries with a positive in the size-5 bank, the best-positive rank has mean 59.04, median 6.5, p75 43, and p90 171.5. This shows meaningful near-miss headroom but a long tail.

## 11. Cache/test integrity

Validation used 13,030 relation-cache lookups, all hits. New LLM calls and HTTP requests were zero. Test gold, sealed evaluator, and private test artifacts were not accessed; target-method test runs remain zero. `BENCHMARK_ISSUE_FOUND` is retained without changing benchmark semantics.

## 12. Limitations

Round 0 generalizes poorly despite high sampled pairwise accuracy, and a linear representation still leaves a large oracle gap. The aware model improved validation but not development tune, so relation-type utility is not consistently supported.

## 13. Next-stage decision

The next priority is a nonlinear ranking model. Pairwise alignment helped, hard-negative mining was essential, and the remaining evidence points to insufficient linear capacity rather than a need to expand the bank or prioritize relation typing.
