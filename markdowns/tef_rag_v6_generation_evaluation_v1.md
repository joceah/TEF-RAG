# TEF-RAG v6 downstream generation evaluation v1

This runner evaluates whether better retrieval evidence flows improve the final structured work order and embodied action plan.

## Fairness contract

All five frozen retrieval methods use exactly the same downstream generator:

- model: `deepseek-flash`
- base URL: official DeepSeek API
- temperature: `0`
- thinking mode: `disabled`
- prompt version: `tef-v6-generation-eval-v1.3`
- protocol version: `v1.6-nonthinking-runtime-clarification`
- one repair attempt maximum
- identical JSON schema and canonicalization registries

The generator receives only the public query and the exact frozen selected evidence records, up to the Top-5 budget. A method/query may provide zero records. It does **not** receive retrieval method identity, retrieval score, TEF relation edges, graph diagnostics, or generation gold.

## Formal sequence

```bash
python scripts/run_tef_rag_v6_generation_eval.py preflight
python scripts/run_tef_rag_v6_generation_eval.py generate --all
python scripts/run_tef_rag_v6_generation_eval.py freeze
python scripts/run_tef_rag_v6_generation_eval.py evaluate --private-root ../.tef_v6_generation_gold_private
```

`generate --all` is the only formal mode. It interleaves calls query-major across all five methods; `--method` is rejected. The v1.4 short-output clarification, v1.5 model correction, and v1.6 non-thinking runtime clarification are in `plans/TEF_RAG_v6_generation_evaluation_protocol_v1_4_short_retrieval_output_clarification.md`, `plans/TEF_RAG_v6_generation_evaluation_protocol_v1_5_model_correction.md`, and `plans/TEF_RAG_v6_generation_evaluation_protocol_v1_6_nonthinking_runtime_clarification.md`.

`freeze` must complete before private generation gold is read. It hashes every generation prediction file and records `private_generation_gold_accessed=false`.

An output that remains schema-invalid after the single repair is retained with its validation errors. Freeze locks its prediction and request provenance; evaluation reports Schema Validity 0 and scores the remaining defined metrics conservatively. A second repair is never attempted.

`evaluate` verifies those hashes and the private generation-gold SHA256 before scoring. Item-level test scores are written only below the private gold root; the repository receives aggregate metrics only.

## Integrity gates before a formal run

The preflight requires materialized public `queries_test.jsonl` and `evidence.jsonl`, all five retrieval prediction files, and their frozen hashes. The two public file hashes are in the tracked generation metadata file `materialized_artifact_hashes.json`; they are copied from the already committed benchmark `manifest.json` and independently checked against `transport_manifest.json` compressed-source provenance. The retrieval prediction hashes and query-ID hash come from the sealed retrieval manifest. Missing files or missing/mismatched hashes stop the run; preflight does not recreate retrieval outputs.

Formal generation accepts only `https://api.deepseek.com/chat/completions`. Each generation row records a session fingerprint and the initial and optional repair request fingerprints. Resume verifies every saved row before the client reads credentials or cache. `freeze` locks one session across all 2,400 rows plus runner/evaluator source, schema and registries. `evaluate` rechecks the locks before private gold access. An atomic evaluation-start lock, existing formal metrics, final manifest or private item-level details stop another official evaluation. The private output root must resolve outside the repository.

The aggregate metadata records both `private_gold_sha256` and `private_index_sha256`. The index hash is deterministically reconstructed from the committed public benchmark transport parts using the generation-gold builder's row ordering and JSONL serialization; no private file is read to derive it. The evaluator still fails closed if either aggregate hash is missing or changes. Once both hashes match, row-wise gold/index pairing is safe because each file's contents and row order are fixed. No per-item test fingerprints are published or required.

The published development/validation gold contains direct string parameter values. The frozen v1.3 clarification accepts those literal values alongside the original structured `{value, unit}` form and rejects malformed nested objects. It does not rewrite any gold. Published dev/val plans have unique canonical gold actions; because the original builder did not enforce that property, formal scoring explicitly stops if any private gold plan has duplicates.

## Reported metrics

- Schema Validity
- Field Macro-F1 (strict)
- Work-Order Joint EM (strict)
- Action Precision / Recall / F1
- Dependency Precision / Recall / F1
- Order Validity
- Plan EM (strict)
- Citation Precision / Recall / F1
- Evidence Support Recall
- End-to-End EM (strict)
- Task Success

Free-text slots use protocol v1.2 strict deterministic canonicalization; no embedding similarity, fuzzy threshold, or LLM judge is used.

## Output paths

Before evaluation:

```text
results/v6/generation_eval_v1/
  preflight.json
  generation_runtime.json
  predictions/
    bm25.jsonl
    bge_reranker.jsonl
    temporal_bm25.jsonl
    ta_rag.jsonl
    tef_rag_stage3d.jsonl
  generation_prediction_manifest.json
```

After the single private-gold evaluation:

```text
results/v6/generation_eval_v1/
  metrics.json
  final_evaluation_manifest.json
```

Per-query test scores stay outside the repository at `<private-root>/evaluation_details_v1/`.

Do not tune the prompt, schema, aliases, repair policy, or evaluator after the first formal test scoring.
