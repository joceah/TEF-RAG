# TEF-RAG v6 Stage 3A: learned pair proposal

## 1. Stage 2C motivation

Stage 2C isolated pair proposal as a major validation bottleneck: search-pool Flow Oracle was 97.71%, while the rule prefilter's globally consistent endpoint feasibility was 63.75%. Stage 3A changes only pair proposal; BM25, temporal/procedure eligibility, node scoring, relation prompt v7, confidence threshold, greedy set scoring, and `final_k=5` remain frozen.

## 2. Pair proposer formulation

For every legal chronological pair in the frozen top-30 pool, a lightweight classifier estimates whether the pair is worth sending to the relation scorer. Inference ranks probability descending, then `source_id`, then `target_id`, and selects a fixed per-query Top-N. The proposer does not predict relation type.

## 3. Development-only supervision

Labels use development gold only. Every allowed endpoint pair of every required flow edge is positive; every other legal chronological pair is negative. Validation is evaluation-only, and the runner exposes no test split.

## 4. Features

Deployment-visible features include query-to-source/target and source-to-target lexical overlap, frozen node relevance/total/recency/role scores, event and source type one-hots, event transitions, temporal gaps, query role demands, procedure/correction/uncertainty/verification flags, and explicit supersession metadata. The primary schema excludes query/evidence `chain_id`, `query_id`, evidence-ID patterns, gold fields, difficulty, and split. `episode_id` is not a model feature.

## 5. Grouped split

Development chains are deterministically split 80/20 with seed `20260916`, preventing paraphrases of one underlying chain from crossing train and tune. There are 188 train chains and 52 tune chains; the manifest is represented by a stable hash rather than a large sample file.

## 6. Learned model

The model is scikit-learn `LogisticRegression(class_weight="balanced", C=1, solver="liblinear", max_iter=300)`. After development selection it is refit on all 1,440 development queries (4,349 positive and 370,207 negative pairs) and exported as auditable JSON with its feature schema and SHA256.

## 7. Rule / learned / hybrid comparison

The rule baseline is the frozen Stage 2B improved prefilter. Learned and budget-bounded hybrid variants were compared at Top-16, Top-24, and Top-32. Hybrid protects only explicit supersession and strong procedure-to-action/diagnosis/verification candidates; it does not restore chain-ID heuristics. The development selection rule froze pure learned Top-32.

## 8. Pair recall-cost curve

On the grouped tune partition, learned Top-16/24/32 achieved endpoint feasibility 73.08%/78.53%/82.05% and required-edge recall 90.00%/93.09%/94.12%, versus 54.17% and 78.25% for the rule baseline. Their mean proposal counts were 15.17/22.37/29.31 versus 22.16. On all development queries, frozen Top-32 achieved 84.79% endpoint feasibility and 94.83% required-edge recall, versus 53.75% and 78.34% for the rule.

## 9. Downstream relation funnel

On validation, the rule funnel was 97.71% search oracle → 63.75% pair feasible → 60.21% has-edge feasible → 28.96% typed feasible. Frozen Stage 3A was 97.71% → 85.83% → 79.17% → 37.29%. The relation-side sequence ends at typed relation feasibility. Actual FlowComplete is reported separately in the 2×2 relation-feasible × actual-success matrices because it is not a nested subset.

## 10. Final retrieval metrics

On development, Stage 3A improved Recall@5 from 61.47% to 63.86%, Complete@5 from 19.10% to 22.15%, FlowComplete@5 from 18.61% to 21.60%, and Edge Recall from 30.26% to 36.90%. On frozen validation it improved the same metrics from 68.80%/29.79%/28.96%/38.45% to 70.70%/31.88%/31.25%/42.57%.

## 11. Corrected 5-vs-5 selector diagnostic

For typed-feasible failures, each feasible required assignment is padded from the same top-30 pool to exactly five evidence items while preserving official FlowComplete. Its best frozen `_set_score()` is compared with the five-item greedy set. This removes the prior positive-node-score bias from comparing five items against only three or four. On validation, the rule baseline's 94 B cases split into 90 objective-misalignment and 4 search-failure cases; Stage 3A's 129 B cases split into 125 and 4, with no ties.

## 12. LLM cost/cache reuse

The relation fingerprint remains a function of query, source, target, and frozen prompt version; proposal mode, branch, and budget never enter it. Existing Stage 2A/2B judgments are reused and only missing learned pairs are warmed. Exact cache hits, new judgments, HTTP requests, and token counts are recorded per split in `llm_cache_diagnostics_*.json`.

## 13. Limitations

The benchmark is synthetic, `BENCHMARK_ISSUE_FOUND` remains in force, and Stage 3A does not address known weak relation typing for `qualifies` and `updates`. Top-32 also spends a larger pair budget than the rule baseline, so both the same-cost Top-24 curve and the frozen primary result should be considered.

## 14. Next-stage decision

Stage 3A resolves a substantial part of the rule proposal bottleneck and produces a real +2.29-point validation FlowComplete gain. However, the new 79.17% has-edge feasibility contracts to 37.29% typed feasibility, and `qualifies`/`updates` correct-type recall remains only 3.68%/5.56%. Relation typing is now the highest-priority next stage. No validation result was used to retune Stage 3A.
