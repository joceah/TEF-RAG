# TEF-RAG v6 Semantic Benchmark Candidate — Local Validation Status

Date: 2026-09-15

| Check | Result |
|---|---|
| Semantic benchmark deterministic validator | PASS |
| Counts | 400 chains / 1,200 intents / 2,400 query rows / 100 assets |
| Evidence records | 3,888 |
| Public dev+validation gold rows | 1,920 |
| Challenge RECENCY_SOLVABLE_AT_5 | 0.1217 <= 0.40, PASS |
| Challenge Latest-5 Complete@5 | 0.1217 <= 0.40, PASS |
| Largest major-stratum recency-solvable rate | 0.3667 <= 0.50, PASS |
| Sealed test evaluator records | 480 |
| Sealed test evaluator SHA256 | `477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3` |
| `python -m unittest tests.test_tef_v6_semantic_benchmark` in local repo-like layout | 1 passed / 0 failed |

No full repository pytest/CI run is claimed for this publication step. No target retrieval method was run.

Review status remains `SEMANTICALLY_AUTHORED_CANDIDATE_PENDING_BLIND_SECOND_REVIEW`: the current authoring context performed the first semantic pass; the protocol-required blind second pass for validation/test must be performed in a fresh review context before final benchmark acceptance.
