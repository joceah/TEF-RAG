# TEF-RAG v6 Temporal-Hard Benchmark v1

Status: `SEMANTICALLY_AUTHORED_CANDIDATE_PENDING_BLIND_SECOND_REVIEW`

This artifact was authored semantically under frozen protocol commit `b0e6e004378e7d7f29cabece1efa6b2c30489e9b`.

## Scale

- 400 authored chains
- 1200 primary intents
- 2400 query rows
- 100 target assets
- Realistic Distribution: 200 chains
- Temporal-Hard Challenge: 200 chains
- split: 60/20/20 per layer

Each chain has 3 distinct primary intents and each intent has 2 deterministic paraphrases. Paraphrases are robustness variants, not independent statistical units.

## Test sealing

Public test artifacts contain only query/evidence/limited chain metadata. Item-level test difficulty labels, required groups, canonical flow, answer summaries, and review reasoning are not committed.

Sealed test evaluator SHA256:

`477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3`

The sealed evaluator has 480 query-level records and is stored outside the public GitHub branch.

## Review state

The current ChatGPT authoring context completed a first semantic pass over all authored semantic families and instantiated chains. This pass is **not blind** to authoring. The frozen protocol requires a second blind source-grounded AI review for validation/test, so the dataset is not yet labeled final/released.

No TEF-RAG v6 retrieval method, reranker, multi-step method, or other target method was run during authoring.

## Evidence semantics

Operational causal stories and synthetic procedures are modeling choices unless a record has an explicit `source_basis_id`. Public manufacturer sources constrain product/reference envelopes only and are not presented as station-specific SOPs.

`required_groups` use OR only for genuinely equivalent alternatives. Complementary evidence is split into separate groups. `required_flow_edges` use typed relations; endpoint pairs are globally consistency-constrained for FlowComplete.

## Repository transport format

Large fixed JSONL artifacts are committed under `compressed/*.jsonl.xz` to keep connector-side publication compact. This is a transport choice only; it does not regenerate semantics.

Run:

`python scripts/materialize_tef_v6_semantic_benchmark_v1.py`

to materialize the logical `public/*.jsonl` and review JSONL files. The validator can also read the `.xz` files directly without materialization. `transport_manifest.json` records compressed and uncompressed SHA256 values.

The materializer contains no sealed test gold and cannot recreate it.
