# TEF-RAG v6 generation JSON failure debug bundle

This directory is a debug evidence bundle, not a proposed parser fix. It captures the current working-tree changes and the archived evidence for one interrupted generation attempt. It is intended to make the failure and the v1.8 experiment independently reviewable.

## Provenance and scope

- Base HEAD: `935832eb4d59ac11eacf4d95d50d7fcf0da5c3d4`.
- Original formal command: `python -m scripts.run_tef_rag_v6_generation_eval generate --all`.
- Failed method: `tef_rag_stage3d`; query index `63`; query ID `TEFV6-C0059-I02-post_arrival-P2`.
- Request fingerprint: `29d49b8b10f61fbfdc977b88b00a474c644a22580b482c2dfe6b00202284eb21`.
- The original diagnostic reproduction used instrumented source. It must not be represented as an untouched run of commit `935832eb4d59ac11eacf4d95d50d7fcf0da5c3d4`.
- The old untracked `results/v6/generation_eval_v1/` directory contains the original 319-row partial artifacts and remains intentionally outside this bundle and outside the commit.

During the packaging operation no generation, freeze, evaluate, retrieval, retrieval-side LLM, or private gold/index access was performed.

## Original failure

The checkpoint before the failed request was:

| method | persisted rows |
| --- | ---: |
| bm25 | 64 |
| bge_reranker | 64 |
| temporal_bm25 | 64 |
| ta_rag | 64 |
| tef_rag_stage3d | 63 |
| **total** | **319** |

All three archived attempts received HTTP 200, `Content-Type: application/json`, `finish_reason=stop`, and non-streaming responses. The failing layer was `assistant_content_json`; each strict `json.loads()` failed with `Extra data`.

| attempt | content chars | content bytes | SHA256 | JSON error | raw-decode consumed | top-level keys |
| --- | ---: | ---: | --- | --- | ---: | --- |
| 1 | 1512 | 1642 | `7ba82572789d3b6646a8ab6811d32b1ff00b15e2c1e4b03e56f1a728377703bc` | line 1, col 1045, pos 1044 | 1044 | `work_order`, `action_plan` |
| 2 | 1511 | 1639 | `5d3d701fa1c573b7d8462e6ff5159e61d96667bfba35e0268fb1860f4519db4d` | line 1, col 1044, pos 1043 | 1043 | `work_order`, `action_plan` |
| 3 | 1511 | 1639 | `5d3d701fa1c573b7d8462e6ff5159e61d96667bfba35e0268fb1860f4519db4d` | line 1, col 1044, pos 1043 | 1043 | `work_order`, `action_plan` |

The common trailing remainder is 468 characters (494 UTF-8 bytes), SHA256 `7a34a87bef082e6a3ef09a24df9eaf4edc3706528a5c47b8faf862db478662de`, begins with `,"action_plan":`, and ends with the final action-array close plus `}`. The first raw-decoded value already contains both expected root fields. The consumed `}` therefore closes a complete root object, and the remainder repeats the `action_plan` root field. The precise classification is **`duplicate_root_field_after_complete_object`**, not `premature_root_close`.

Attempt 1 differs from attempts 2 and 3 only at one character in the work-order text (U+3002 `。` is present in attempt 1 and omitted in attempts 2 and 3; character index 426 / UTF-8 byte offset 502). Attempts 2 and 3 are byte-for-byte identical. The malformed suffix is otherwise common. The trailing array portion can be decoded as three actions (`A1`, `A2`, `A3`) after removing its leading field prefix for analysis, but the original remainder itself is not a standalone JSON value because it begins with a comma. No source string is modified here.

## v1.8 experiment status

The current working tree contains the v1.8 `premature_root_close` normalization experiment in `tef_rag_v6/generation_runner.py`, its CLI/protocol fingerprint wiring, documentation, and regression tests. Its safety condition requires the recovered root key to be absent from the first decoded object. Consequently it correctly rejects the archived response above because `action_plan` is already present. The v1.8 rule was based on the earlier misclassification and has not been shown by a real production sample to be required for this failure. This bundle does not claim that v1.8 fixes the archived production response.

## Targeted v1.8 reproduction

`target_summary.json` records one isolated, non-formal request for the same method/query under protocol `v1.8-premature-root-close-normalization`:

- 1 request, 0 retries, 0 cache hits;
- endpoint `https://api.deepseek.com/chat/completions`, model `deepseek-flash`;
- strict parse mode;
- schema validation passed, grounding validation passed, repair was not invoked;
- provider/accepted content SHA256 `722ff23786680f2443e8102f8cdf50ad6c577d4e1fd2d637c338db3c5c7a3950`;
- no malformed response was reproduced.

The isolated target cache is external to this repository and is not included in the bundle.

## Tests recorded before packaging

- Focused generation hardening tests: **76 passed**.
- Full suite: **225 passed, 3 failed**.
- The three failures were `test_known_benchmark_issue_is_recorded_but_nonfatal`, `OracleAttributionV52Tests.test_frozen_retriever_and_exact_search_sources_are_unchanged`, and `SemanticBenchmarkV1Test.test_public_semantic_benchmark_validator`.
- No reliable pre-v1.8 baseline was found, so these three failures are **not proven pre-existing**.

## Open questions

1. The evidence shows a complete first object and a repeated trailing `action_plan`; equality of the first object's array and the trailing array should be checked explicitly before making any semantic claim about them.
2. Whether the v1.8 experiment should remain is unresolved.
3. Whether the production failure warrants a deterministic normalization is unresolved. No automatic duplicate-field repair is proposed by this bundle.

## Included files and redaction

The bundle includes the three assistant-content files, three failure records, reviewed raw HTTP response copies named `*_raw_response_REDACTED.txt`, diagnostic summary, traceback, provenance, source diff, targeted reproduction summary, preflight snapshot, and pre-branch Git snapshots. `current_worktree.diff` records the tracked source/docs/tests changes present before packaging.

No API key, authorization header value, bearer token, `local.env`, private gold/index, formal cache, or isolated cache was copied. The raw response copies are byte-preserving reviewed copies; the `_REDACTED` suffix identifies their reviewed handling, not a byte rewrite. The diagnostic source diff contains code identifiers such as `api_key` and `authorization` but no credential values.
