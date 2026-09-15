# TEF-RAG v6 Semantic Benchmark v1 — Authoring/Validation Summary

- Frozen protocol: `b0e6e004378e7d7f29cabece1efa6b2c30489e9b`
- Status: `SEMANTICALLY_AUTHORED_CANDIDATE_PENDING_BLIND_SECOND_REVIEW`
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

## Semantic corrections relative to the 16-chain pilot

1. complementary evidence is split into separate required groups; OR alternatives are only equivalent records;
2. flow relation types are semantic rather than a single `supports_next`;
3. late-arrival cases have no already-visible evidence that independently reveals the final correction;
4. procedures carry machine-readable version/validity/supersession/model-scope metadata;
5. source provenance explicitly distinguishes public-source-backed reference facts from modeling choices;
6. test item labels/gold/flow/review reasoning are withheld from the public development branch.

## Review boundary

Pass 1 was performed in the authoring ChatGPT context and is not blind. Validation/test still require the frozen protocol's second blind review in a fresh context before final release.
