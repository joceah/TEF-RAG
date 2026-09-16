# TEF-RAG v6 Stage 2C bottleneck attribution

## Context

Stage 2B.1 showed that aggregate typed-relation feasibility and actual FlowComplete were both
.2896 on validation, but aggregate equality cannot identify whether they succeed on the same
queries. Stage 2C freezes the improved-prefilter + cached LLM relation + greedy pipeline and
performs evaluation-only attribution. No algorithm or threshold changes were made.

## Relation versus selection matrix

| Split | Relation yes / actual yes | Relation yes / actual no | Relation no / actual yes | Relation no / actual no |
|---|---:|---:|---:|---:|
| Development | 44 | 379 | 224 | 793 |
| Validation | 45 | 94 | 94 | 247 |

On validation, P(actual success | relation feasible) is .3237 and P(actual success | relation
infeasible) is .2757. The equal aggregate rates therefore conceal 94 selection failures despite
a feasible typed graph and 94 downstream successes despite typed-graph infeasibility.

## Globally consistent relation funnel

| Stage | Development | Validation |
|---|---:|---:|
| Search-pool Flow oracle | .9729 | .9771 |
| Prefilter endpoint feasible | .5375 | .6375 |
| LLM accepted-edge feasible | .5146 | .6021 |
| Typed relation feasible | .2938 | .2896 |
| Actual FlowComplete | .1861 | .2896 |

Every level enumerates one globally consistent required-group assignment. The largest validation
drops are pair proposal (-33.96 percentage points) and relation typing (-31.25 points); accepted
edge existence contributes only -3.54 points.

## Relation failure attribution

Among validation D cases (relation infeasible and actual failure), 129 are prefilter pair misses,
13 are NO_EDGE/low-confidence failures, 94 are wrong relation types, and 11 lack a usable official
top-30/global assignment. Development counts are 511, 28, 215, and 39 respectively.

The weakest validation relation types by correct-type recall are `qualifies` (.0221, 136 gold
edges), `updates` (.0278, 36), `contrasts` (.4643, 56), `supersession` (.5513, 78), and
`preserves_uncertainty` (.6786, 56). `qualifies` also has only .5294 prefilter recall.

## Selector attribution

All 379 development B cases and all 94 validation B cases are objective misalignment under the
frozen scoring function; none are search failures under that objective. On validation, the
greedy set exceeds the best typed-feasible assignment by 1.58 score points on average, while
missing 1.81 assignment evidence items. This explains why a wider/raw beam did not help.

## Decision

Relation-side failures currently outnumber typed-graph-available selector failures, and the
largest single D attribution is missing endpoint pairs. The next highest-priority experiment is
a learned or query-conditioned pair proposal mechanism, evaluated for downstream flow utility.
Subsequent work should address severe `qualifies`/`updates` type confusion and recalibrate set
scoring; merely changing the search algorithm is not supported.

## Limitations and integrity

`DEPLOYMENT_METADATA_ASSUMPTION`: the frozen improved prefilter uses evidence-side `chain_id`;
future work must confirm its deployment availability. The historical validation review hash
mismatch remains `BENCHMARK_ISSUE_FOUND`; benchmark and manifest were not changed. All 42,963
judgments were cache hits, HTTP calls were zero, and no test/private artifact was accessed.
