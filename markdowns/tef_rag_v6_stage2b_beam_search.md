# TEF-RAG v6 Stage 2B: constrained beam flow search

## Context and question

Stage 2B freezes Stage 2A candidate retrieval, temporal eligibility, node scoring, and
`tef-v6-stage2a-relation-v7`. It asks whether deterministic constrained beam search
improves the cached LLM relation graph, then measures the Stage 2A pair-prefilter ceiling.

## Method

Beam states contain the ordered evidence IDs and derived node, edge, role, connectivity,
uncertainty, redundancy, and disconnected components. Expansion is restricted to the
already hard-eligible search pool. The frozen greedy result is retained as a diverse
relevance fallback. Configuration was tuned on development (widths 4/8/16 and conservative
fallback margins), frozen, and applied once to validation. No gold field enters inference.

The improved prefilter preserves Stage 2A pairs and adds typed observation/diagnosis/action/
verification transitions, procedure and uncertainty/correction pairs, and limited top-node
neighborhoods. It sends at most 24 pairs per query to the unchanged relation scorer.

## Cache reuse and efficiency

Old and new prefilter modes share the same pair cache key. Search mode is not part of that
key. Search-only development and validation made zero HTTP calls with 100% cache hits.
Improved-prefilter cache warming introduced 10,635 development pairs (1,380 HTTP attempts)
and 3,066 validation pairs (430 attempts); all later ablation scoring was cache-only.

Beam expanded 476.1 states/query on development and 363.1 on validation. Cached inference
runtime was about 12.6 ms/query (development) and 10.2 ms/query (validation), versus 4.8 ms
and 4.1 ms for greedy. Old/new prefilter sizes were 15.42/22.80 pairs/query on development
and 14.72/21.10 on validation.

## Results

| Method | Dev Recall@5 | Dev Complete@5 | Dev FlowComplete@5 | Val Recall@5 | Val Complete@5 | Val FlowComplete@5 |
|---|---:|---:|---:|---:|---:|---:|
| Stage2A LLM + greedy | .6008 | .1632 | .1576 | .6753 | .2667 | .2583 |
| Stage2A LLM + beam | .5994 | .1611 | .1556 | .6753 | .2667 | .2583 |
| Improved prefilter + greedy | .6147 | .1910 | .1861 | .6880 | .2979 | .2896 |
| Improved prefilter + beam | .6138 | .1896 | .1847 | .6880 | .2979 | .2896 |

The beam objective did not solve the greedy bottleneck: development was slightly worse and
validation tied after fallback. In contrast, improved prefilter raised development relation-
graph oracle flow completeness from .2611 to .2938 and validation from .2458 to .2896.
Flow-search failures fell from 819 to 773 on development and 271 to 251 on validation.

Candidate oracle completeness is 1.0 on both splits. This and the remaining relation/search
gap show that the next highest-value step is learned or calibrated set scoring, using only
development data, rather than a wider beam. The constant Stage 1 `source_compatibility`
feature remains a recorded TODO and was deliberately left frozen.

## Integrity

The sealed benchmark semantic content, manifest, and review artifacts are unchanged.
Test gold, the sealed test evaluator, and private test review artifacts were not accessed;
target method test runs remain zero. `BENCHMARK_ISSUE_FOUND` remains recorded for the
historical validation review hash mismatch and is outside this method-development change.
