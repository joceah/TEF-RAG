# TEF-RAG v6 Stage 2A-1: Query-conditioned LLM relations

## 1. Research question

Stage 2A-1 isolates one change: whether replacing Stage 1 heuristic relation judgment with query-conditioned semantic judgment improves Temporal Evidence Flow. BM25 candidates, temporal/procedure hard gates, node scores, greedy flow search, `candidate_k`, `search_pool_k` and `final_k` remain frozen.

## 2. Stage 1 limitation

Stage 1 edges mainly use event-type rules, evidence metadata, same-chain/episode priors and lexical overlap. Its `source_compatibility` node feature is effectively constant because it checks a candidate source type against the set of candidate source types; this known limitation remains unchanged to keep the experiment controlled.

## 3. LLM relation architecture

`BM25 → deterministic temporal/procedure gate → frozen node scoring → deterministic pair prefilter → query-conditioned LLM relation judgment → frozen greedy flow search`

The three modes are `heuristic`, `llm` and `hybrid`. Hybrid preserves explicit `supersedes` metadata and all deterministic temporal/procedure constraints; the LLM cannot override eligibility. Output labels are limited to the frozen relation taxonomy plus internal `NO_EDGE`.

The final experiment uses the official DeepSeek OpenAI-compatible endpoint configured by the untracked `D:/electric-project/local.env` (`deepseek-v4-flash`, thinking disabled). Calls remain strictly serial: one query per request, with at most 16 prefiltered pairs in that request. The client has an in-flight lock, timeout, bounded retries with 429 backoff, strict schema/taxonomy/endpoint validation, pair-level SHA-256 cache and resume-safe writes. Compact relation codes are deterministically mapped back to the frozen taxonomy. Secrets, cache and failure logs are not committed.

## 4. Pair prefilter

Only temporally ordered pairs inside the top-30 frozen relation pool are considered. Explicit supersession is always retained; other pairs require compatible chain/event evidence and a Stage 1 heuristic floor. Priority combines heuristic plausibility, node score, episode coherence and explicit metadata. At most 16 pairs per query reach the LLM. The prefilter selects pairs only; it does not assign the final semantic label.

## 5. Prompt design

Final prompt version: `tef-v6-stage2a-relation-v7`. It receives public query text/time/model/context plus deployment-visible evidence text and metadata. It explicitly requests valid JSON, rejects generic relatedness, forbids cross-case mixing, chooses the output schema by the request's top-level field (including a one-item `cases` payload), uses compact relation codes with a deterministic mapping to the frozen taxonomy, and requests confidence plus a short enumerated reason code. No gold group, canonical flow, gold edge, difficulty, benchmark explanation or query chain ID is supplied.

## 6. Experiment protocol

- Benchmark: `TEF_RAG_v6_temporal_hard_benchmark_v1`, `FINAL_SEALED`.
- Development: 1,440 queries; validation: 480 queries; `final_k=5`.
- Prompt/prefilter/threshold/hybrid mapping were finalized using a deterministic 48-query development sanity sample. Configuration was frozen after the full development run and checked before validation.
- The runner accepts only `development` and `validation`; test evaluation is not implemented.

## 7. Development results

| mode | Recall@5 | Hit@5 | nDCG@5 | Complete@5 | FlowComplete@5 | Edge recall | Uncertainty acc. | Constraint violations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| heuristic | 0.5830 | 0.9063 | 0.5977 | 0.1562 | 0.1514 | 0.2646 | 0.9632 | 0.0000 |
| llm | **0.6008** | **0.9361** | **0.6171** | **0.1632** | **0.1576** | **0.2724** | **0.9653** | 0.0000 |
| hybrid | 0.5900 | **0.9361** | 0.6080 | 0.1569 | 0.1514 | 0.2572 | **0.9653** | 0.0000 |

Against the frozen heuristic, LLM relation scoring improves Recall@5 by 1.78 percentage points, nDCG@5 by 1.94 points and FlowComplete@5 by 0.63 points. Hybrid is weaker than pure LLM and is not selected as the Stage 2A result.

## 8. Validation results

| mode | Recall@5 | Hit@5 | nDCG@5 | Complete@5 | FlowComplete@5 | Edge recall | Uncertainty acc. | Constraint violations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| heuristic | 0.6357 | 0.9146 | 0.6460 | 0.2271 | 0.2208 | 0.3201 | **0.9563** | 0.0000 |
| llm | **0.6753** | **0.9563** | **0.6777** | **0.2667** | **0.2583** | **0.3517** | 0.9542 | 0.0000 |
| hybrid | 0.6660 | **0.9563** | 0.6699 | 0.2437 | 0.2354 | 0.3378 | 0.9542 | 0.0000 |

On untouched validation, pure LLM improves Recall@5 by 3.96 points, nDCG@5 by 3.17 points, FlowComplete@5 by 3.75 points and edge recall by 3.16 points. The 0.21-point uncertainty-accuracy decrease is small but retained as a negative result. No mode violates a temporal/procedure hard constraint.

## 9. Relation diagnostics

- The deterministic prefilter retains 71.08% of required development edges and 75.84% of required validation edges before LLM judgment.
- Accepted LLM graph edges average 11.98 per development query and 10.83 per validation query; `NO_EDGE` rates are 22.31% and 26.42%.
- LLM graph-edge recall is 58.53% on development and 60.44% on validation. Validation exceeds the heuristic graph (58.17%), while development is nearly tied (58.73%).
- All 1,440 development and 480 validation query cases have resume-safe cached judgments. The committed `cache_warm_*.json` counters cover only the final resume segment (development: 639 pending cases/653 attempts; validation: 372/379), not the earlier successful segments, so they must not be interpreted as whole-run token or retry totals.
- Structured-output recovery produced no invalid taxonomy label and no failed batch in the successful final segments; one trailing missing judgment was conservatively padded as `NO_EDGE` in each split.

## 10. Failure analysis

The automatic categories below count the primary failure assigned per query.

| category | dev heuristic | dev llm | val heuristic | val llm | interpretation |
|---|---:|---:|---:|---:|---|
| flow search error | 843 | 819 | 293 | 271 | largest remaining bottleneck; LLM edges help but greedy selection still misses complete flows |
| relation classification error | 185 | 204 | 75 | 95 | semantic labels improve final retrieval overall but introduce additional label mismatches |
| evidence redundancy | 238 | 260 | 38 | 41 | LLM scoring sometimes keeps near-duplicate supporting nodes |
| procedure applicability error | 81 | 76 | 20 | 19 | hard gates remain effective and slightly improve under the selected graph |
| uncertainty handling error | 53 | 50 | 21 | 22 | largely stable; validation shows one additional failure |

Representative validation failures are recorded in `failure_analysis_validation.json`; no manual test inspection was used.

## 11. Conclusion

Query-conditioned LLM relation scoring passes the Stage 2A criterion: improvements found on development reproduce more strongly on validation, including flow-level and edge-level metrics, without weakening deterministic temporal safety. Pure LLM scoring is the selected variant. Hybrid dilution is not beneficial under the current fixed weighting.

## 12. Stage 2B recommendation

1. Replace greedy flow selection with a constrained beam or small integer-program search over the already scored graph; flow-search failures dominate both splits.
2. Train or calibrate relation-specific confidence thresholds on development, especially for `supports`, `governs` and `supersession`, while preserving the frozen deterministic eligibility gate.
3. Improve pair prefilter coverage before increasing LLM volume; roughly one quarter to three tenths of required edges are excluded before semantic judgment.

## Integrity

The sealed benchmark semantic content was not modified. Test gold, the sealed test evaluator and private test review artifacts were not accessed. Target-method test runs remain zero.

`BENCHMARK_ISSUE_FOUND` remains recorded from Stage 1: `metadata/validation_second_blind_review.json` has an existing manifest/file SHA-256 mismatch. Neither file was changed.
