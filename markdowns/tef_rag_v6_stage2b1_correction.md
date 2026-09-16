# TEF-RAG v6 Stage 2B.1 correction

## Why this correction

Stage 2B compared greedy over top-30 with beam expansion truncated to top-20, and labelled a
predicted-relation feasibility diagnostic as a FlowComplete oracle. Stage 2B.1 corrects both
definitions without changing retrieval, temporal gating, node scoring, the improved prefilter,
the relation prompt, confidence thresholds, or cached judgments.

## Corrected search setup

Greedy, raw beam, and beam-with-fallback now share the identical top-30 search pool and frozen
improved-prefilter relation graph. Beam width remains 8; connectivity weight .10, uncertainty
weight .12, length normalization 0, and fallback minimum gain 1.0 are unchanged. Raw beam is
reported separately and never falls back.

## Corrected oracle hierarchy

`candidate_pool_group_complete_oracle_at_5` tests group coverage in the eligible candidate
pool. `search_pool_group_complete_oracle_at_5` tests it in top-30. The official
`search_pool_flow_complete_oracle_at_5` uses exactly the evaluator's globally consistent gold
endpoint assignment and does not require a predicted edge or relation type.
`relation_graph_feasibility_at_5` retains the old predicted typed-edge diagnostic under an
accurate name; it is not an upper bound on official FlowComplete.

## Results

| Method | Dev Recall@5 | Dev FlowComplete@5 | Val Recall@5 | Val FlowComplete@5 |
|---|---:|---:|---:|---:|
| Improved prefilter + greedy | .6147 | .1861 | .6880 | .2896 |
| Improved prefilter + raw beam | .5905 | .1493 | .6644 | .2563 |
| Improved prefilter + beam fallback | .6138 | .1847 | .6880 | .2896 |

Raw beam differs from greedy on 1,426/1,440 development queries and 475/480 validation
queries, but is worse on both splits. Fallback activates on 1,438/1,440 development queries
and every validation query. Thus the previous validation equality was caused by fallback,
not by beam and greedy independently selecting the same evidence.

The corrected top-30 Flow oracle is .9729 on development and .9771 on validation, versus
actual greedy FlowComplete of .1861 and .2896. Candidate group oracle is 1.0 on both splits.
Predicted relation-graph feasibility is .2938/.2896 and remains a separate diagnostic.

## Bottleneck decomposition

| Type | Meaning | Development | Validation |
|---|---|---:|---:|
| 1 | candidate pool insufficient | 0 | 0 |
| 2 | top-30 group coverage insufficient | 39 | 10 |
| 3 | groups present but valid endpoints unavailable | 0 | 1 |
| 4 | valid flow exists but selector misses it | 1,133 | 330 |

## Interpretation

The fair raw beam comparison does not improve greedy. However, the official oracle shows very
large selection headroom: 68.75% of validation queries are pure selection misses after a valid
top-30 flow is available. The next stage should therefore focus on calibrated/learned set or
flow scoring, not wider beam, candidate expansion, or relation prompt changes.

All 42,963 relation judgments used across development and validation were cache hits; new LLM
HTTP calls were zero. Validation was run once after the development freeze. No test or private
artifact was accessed, and benchmark semantic content remains unchanged.
