# TEF-RAG v6 downstream generation evaluation v1

This runner evaluates whether better retrieval evidence flows improve the final structured work order and embodied action plan.

## Fairness contract

All five frozen retrieval methods use exactly the same downstream generator:

- model: `deepseek-chat`
- base URL: official DeepSeek API
- temperature: `0`
- prompt version: `tef-v6-generation-eval-v1`
- one repair attempt maximum
- identical JSON schema and canonicalization registries

The generator receives only the public query and the five selected evidence records. It does **not** receive retrieval method identity, retrieval score, TEF relation edges, graph diagnostics, or generation gold.

## Formal sequence

```bash
python scripts/run_tef_rag_v6_generation_eval.py preflight
python scripts/run_tef_rag_v6_generation_eval.py generate --all
python scripts/run_tef_rag_v6_generation_eval.py freeze
python scripts/run_tef_rag_v6_generation_eval.py evaluate --private-root ../.tef_v6_generation_gold_private
```

`generate --all` is the recommended formal mode because calls are interleaved query-major across the five methods.

`freeze` must complete before private generation gold is read. It hashes every generation prediction file and records `private_generation_gold_accessed=false`.

`evaluate` verifies those hashes and the private generation-gold SHA256 before scoring. Item-level test scores are written only below the private gold root; the repository receives aggregate metrics only.

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
