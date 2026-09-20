# v1.9 test record

Environment:

- Windows
- Python 3.13.5 (`D:\Anaconda3\python.exe`)
- Command: `D:\Anaconda3\python.exe -m pytest -q`

Focused generation hardening tests:

- **70 passed**
- Command: `D:\Anaconda3\python.exe -m pytest -q tests/test_tef_rag_v6_generation_hardening.py`

Current full suite:

- **223 passed, 3 failed**
- Failed tests:
  - `test_known_benchmark_issue_is_recorded_but_nonfatal`
  - `OracleAttributionV52Tests.test_frozen_retriever_and_exact_search_sources_are_unchanged`
  - `SemanticBenchmarkV1Test.test_public_semantic_benchmark_validator`

Clean baseline:

- HEAD: `935832eb4d59ac11eacf4d95d50d7fcf0da5c3d4`
- Independent worktree: `D:\electric-project\.tef_v6_clean_baseline_935832`
- **208 passed, 5 failed**
- Baseline-only failures were a schema hash mismatch and the clean worktree
  missing the ignored materialized `queries_test.jsonl` artifact.

The clean baseline and current worktree did not have identical fixture and
materialized-file environments, so passed counts cannot be compared one for
one. The following three failures occurred in the clean HEAD baseline and are
confirmed pre-existing:

- `test_known_benchmark_issue_is_recorded_but_nonfatal`
- `OracleAttributionV52Tests.test_frozen_retriever_and_exact_search_sources_are_unchanged`
- `SemanticBenchmarkV1Test.test_public_semantic_benchmark_validator`

No new full-suite failure was introduced by v1.9.
