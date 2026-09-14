# TEF-RAG v5.1 Failure Attribution

> DIAGNOSTIC ONLY — NOT AVAILABLE AT RETRIEVAL TIME. This is a seen diagnostic set. The analysis is for failure attribution and model development only. It must not be reported as a new unbiased holdout result.

## Experimental Setup

The frozen 16-query v5 dataset, candidate IDs, embeddings, query profiles, record roles, and relation projections were reused without regeneration. Beam width is 64 and Top-k is 5. No LLM or external API was called. Latest-control queries use the existing recency mode and are excluded from set-search attribution.

## Beam vs Exact

Exact search enumerates every feasible Top-k combination from the identical visible candidate pool and calls the same v5 `score_set` implementation as beam search. Ties use total objective, semantic component, then lexicographically sorted record IDs. Returned order is a deterministic best-prefix serialization.

| Scope | Set queries | Exact set match | Mean objective gap | Max objective gap | Beam Complete@5 | Exact Complete@5 |
|---|---:|---:|---:|---:|---:|---:|
| All set-mode | 12 | 1.0000 | 0.000000000000 | 0.000000000000 | 0.1667 | 0.1667 |
| Complex chain | 8 | 1.0000 | 0.000000000000 | 0.000000000000 | 0.1250 | 0.1250 |

## Aggregate Results

| Scope / selector | Recall@5 | nDCG@5 | Complete@5 |
|---|---:|---:|---:|
| All / Beam | 0.7906 | 0.7968 | 0.3750 |
| All / Exact | 0.7906 | 0.7968 | 0.3750 |
| Complex / Beam | 0.6750 | 0.7074 | 0.1250 |
| Complex / Exact | 0.6750 | 0.7074 | 0.1250 |

## Per-query Failure Summary

| Query | Task | Match | Gap | Beam complete | Exact complete | Labels |
|---|---|---:|---:|---:|---:|---|
| tefv5h-q-01-00 | complex_chain | 1 | 0.000000000000 | 0 | 0 | RELATION_PROJECTION_ERROR, WRONG_BRANCH, BROKEN_FLOW, OBJECTIVE_PREFERS_FRAGMENTED_EVIDENCE |
| tefv5h-q-01-01 | complex_chain | 1 | 0.000000000000 | 0 | 0 | RELATION_PROJECTION_ERROR, WRONG_BRANCH, BROKEN_FLOW, OBJECTIVE_PREFERS_FRAGMENTED_EVIDENCE |
| tefv5h-q-01-02 | cutoff_sensitive | 1 | 0.000000000000 | 0 | 0 | RELATION_PROJECTION_ERROR, WRONG_BRANCH, BROKEN_FLOW, OBJECTIVE_PREFERS_FRAGMENTED_EVIDENCE |
| tefv5h-q-01-03 | latest_control | 1 | n/a | 1 | 1 | — |
| tefv5h-q-02-00 | complex_chain | 1 | 0.000000000000 | 0 | 0 | RELATION_PROJECTION_ERROR, WRONG_BRANCH, BROKEN_FLOW, OBJECTIVE_PREFERS_FRAGMENTED_EVIDENCE |
| tefv5h-q-02-01 | complex_chain | 1 | 0.000000000000 | 0 | 0 | QUERY_PROFILE_ERROR, ROLE_PROJECTION_ERROR, RELATION_PROJECTION_ERROR, WRONG_BRANCH, BROKEN_FLOW, OBJECTIVE_PREFERS_FRAGMENTED_EVIDENCE |
| tefv5h-q-02-02 | cutoff_sensitive | 1 | 0.000000000000 | 0 | 0 | QUERY_PROFILE_ERROR, RELATION_PROJECTION_ERROR, WRONG_BRANCH |
| tefv5h-q-02-03 | latest_control | 1 | n/a | 1 | 1 | — |
| tefv5h-q-03-00 | complex_chain | 1 | 0.000000000000 | 0 | 0 | ROLE_PROJECTION_ERROR, RELATION_PROJECTION_ERROR, WRONG_BRANCH, BROKEN_FLOW, OBJECTIVE_PREFERS_FRAGMENTED_EVIDENCE |
| tefv5h-q-03-01 | complex_chain | 1 | 0.000000000000 | 0 | 0 | QUERY_PROFILE_ERROR, RELATION_PROJECTION_ERROR, MISSING_BRIDGE, WRONG_BRANCH, BROKEN_FLOW, OBJECTIVE_PREFERS_FRAGMENTED_EVIDENCE |
| tefv5h-q-03-02 | cutoff_sensitive | 1 | 0.000000000000 | 1 | 1 | — |
| tefv5h-q-03-03 | latest_control | 1 | n/a | 1 | 1 | — |
| tefv5h-q-04-00 | complex_chain | 1 | 0.000000000000 | 0 | 0 | RELATION_PROJECTION_ERROR, MISSING_BRIDGE, WRONG_BRANCH, REDUNDANCY, BROKEN_FLOW, OBJECTIVE_PREFERS_FRAGMENTED_EVIDENCE |
| tefv5h-q-04-01 | complex_chain | 1 | 0.000000000000 | 1 | 1 | — |
| tefv5h-q-04-02 | cutoff_sensitive | 1 | 0.000000000000 | 0 | 0 | QUERY_PROFILE_ERROR, WRONG_BRANCH, REDUNDANCY, BROKEN_FLOW, OBJECTIVE_PREFERS_FRAGMENTED_EVIDENCE |
| tefv5h-q-04-03 | latest_control | 1 | n/a | 1 | 1 | — |

## Structural Diagnostics

`num_connected_components` uses the underlying undirected form of the projected relation graph. Edge density uses unique directed pairs divided by `n*(n-1)`. Role coverage reuses the v5 probability-coverage semantics. `required_bridge_miss_rate` uses articulation points in the projected graph induced by gold nodes; `flow_completion_rate` measures fully covered non-singleton connected components in that same projected-gold graph.

These bridge and flow values are conservative, projection-conditioned diagnostics. The dataset does not provide a canonical per-query gold chain edge list, so they must not be interpreted as exact ground-truth flow metrics. Null means no defensible projected bridge/flow denominator exists.

| Selector | Mean components | Mean largest-component ratio | Mean edges | Mean edge density | Mean role coverage | Mean bridge miss rate | Mean flow completion |
|---|---:|---:|---:|---:|---:|---:|---:|
| Scoped Hybrid | 2.6667 | 0.6000 | 2.7500 | 0.1208 | 0.6793 | 0.3571 (7 q) | 0.3750 (12 q) |
| Beam | 2.5000 | 0.6333 | 2.9167 | 0.1292 | 0.7577 | 0.2143 (7 q) | 0.2917 (12 q) |
| Exact | 2.5000 | 0.6333 | 2.9167 | 0.1292 | 0.7577 | 0.2143 (7 q) | 0.2917 (12 q) |

## Failure Taxonomy

- `BROKEN_FLOW`: 9
- `MISSING_BRIDGE`: 2
- `OBJECTIVE_PREFERS_FRAGMENTED_EVIDENCE`: 9
- `QUERY_PROFILE_ERROR`: 4
- `REDUNDANCY`: 2
- `RELATION_PROJECTION_ERROR`: 9
- `ROLE_PROJECTION_ERROR`: 2
- `WRONG_BRANCH`: 10

Role-complete but flow-incomplete cases (Exact): 2.
Relation-rich but flow-incomplete cases (Exact): 9.

Taxonomy labels are deterministic diagnostic rules, not independently adjudicated causal ground truth. Authoring roles and logic edges are read only by this offline analyzer to surface possible profile/projection mismatches.

## Main Findings

Exact and Beam select the same objective-optimal sets on every set-mode query. The observed Complete@5 failures therefore cannot be attributed to beam approximation on this diagnostic set.

Among 10 Beam failures on set-objective queries, Exact resolves 0 and leaves 10 unresolved; 0 failures have a positive objective gap.
A gold-complete Top-5 set is feasible for 10 of those failures. The exact optimum scores strictly above the best gold-complete set in 10 cases (mean margin 0.0693). This comparison is diagnostic-only.

## Implications for v6

Search is not the primary issue on these 8/12-candidate pools. The next stage should investigate a preregistered closure-/flow-completion-aware v6 objective and independently validate it, without tuning on this seen set.

## Limitations

This dataset was already used during development and is not an unbiased holdout. It is small, synthetic, and not independently reviewed. Structural conclusions depend on the frozen public relation and role projections. Required evidence groups are singleton groups, and no canonical per-query gold edge chain is available. Exact search diagnoses the existing objective only; it does not establish that a new objective will generalize.
