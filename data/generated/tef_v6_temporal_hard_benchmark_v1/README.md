# TEF-RAG v6 Semantic Benchmark v1

Status: `FINAL_SEALED`

This benchmark was semantically authored under frozen protocol commit `b0e6e004378e7d7f29cabece1efa6b2c30489e9b` and completed the protocol-required validation and test blind second semantic reviews. It remains a **public-source-grounded, AI-assisted synthetic benchmark**; it is not expert-reviewed, field-certified, or a real-world benchmark.

## Scale

- 400 authored chains
- 1200 primary intents
- 2400 query rows
- 100 target assets
- Realistic Distribution: 200 chains
- Temporal-Hard Challenge: 200 chains
- split: 60/20/20 per layer

Each chain has 3 distinct primary intents and each intent has 2 deterministic paraphrases. Paraphrases are robustness variants, not independent statistical units.

## Final review and sealing

- Validation formal second blind review: 80/80 PASS, 0 unresolved, 0 disagreements.
- Test formal second blind review: 80/80 PASS, 0 unresolved, 80 agreements / 0 disagreements.
- Test independent item-level review artifact is private; SHA256: `6e274720b45f8fe1d23b9e662cd294168acbcce91cb3a37e11000e2d6bb1e3f7`.
- Sealed evaluator: 480 records; SHA256: `477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3`.
- Target-method runs at authoring/review: 0.

## Test confidentiality

Public test artifacts contain only query/evidence/limited chain metadata. Item-level test difficulty labels, required groups, canonical flow, answer summaries, test gold, and reviewer reasoning are not committed. The sealed evaluator remains outside the public GitHub branch.

## Evidence semantics

Operational causal stories and synthetic procedures are modeling choices unless a record has an explicit `source_basis_id`. Public manufacturer sources constrain product/reference envelopes only and are not presented as station-specific SOPs.

`required_groups` use OR only for genuinely equivalent alternatives. Complementary evidence is split into separate groups. `required_flow_edges` use typed relations; endpoint pairs are globally consistency-constrained for FlowComplete.

## Repository transport format

Large fixed JSONL artifacts are committed under `compressed/*.jsonl.xz` (base64-part transport where required) to keep connector-side publication compact. This is a transport choice only; it does not regenerate semantics.

Run `python scripts/materialize_tef_v6_semantic_benchmark_v1.py` to materialize logical public JSONL/review artifacts. The materializer contains no sealed test gold and cannot recreate it.
