# TEF-RAG v6 generation gold v1.1 canonicalization

Deterministic canonicalization only; no LLM calls. Diagnosis, action, dependency, and object-level citation semantics were not rewritten. Top-level citations were recomputed as the object-level union and procedure fields were normalized from visible procedure metadata.

- Addendum SHA256: `8f209531985b362c4a754e27fb0983af6de9d62270502db79657e2b09e3a350e`
- Deterministic repairs: `{"top_citation_union": 275, "procedure_canonicalization": 552, "object_citation_dedupe": 118}`
- Semantic objects: development=720, validation=240, test=240 (test private)
- Remaining REVIEW_UNRESOLVED chains: 0
- GENERATION_GOLD_READY: True

```json
{
  "canonicalization_version": "v1.1",
  "splits": {
    "development": {
      "semantic_gold_objects": 720,
      "schema_valid": 720,
      "temporal_valid": 720,
      "procedure_valid": 720,
      "citation_valid": 720,
      "provenance_valid": 720,
      "dag_valid": 720,
      "paraphrase_consistent": 720,
      "review_unresolved": 0
    },
    "validation": {
      "semantic_gold_objects": 240,
      "schema_valid": 240,
      "temporal_valid": 240,
      "procedure_valid": 240,
      "citation_valid": 240,
      "provenance_valid": 240,
      "dag_valid": 240,
      "paraphrase_consistent": 240,
      "review_unresolved": 0
    },
    "test": {
      "semantic_gold_objects": 240,
      "schema_valid": 240,
      "temporal_valid": 240,
      "procedure_valid": 240,
      "citation_valid": 240,
      "provenance_valid": 240,
      "dag_valid": 240,
      "paraphrase_consistent": 240,
      "review_unresolved": 0
    }
  },
  "all_checks_pass": true
}
```

## Independent audit closure

- Test generation gold remains private; repository metadata is aggregate-only for the test split.
- Item-level disagreement/adjudication metadata is retained only for development/validation.
- Pass A/B canonical exact agreement (chain level): development 11/240, validation 2/80, test 1/80; remaining chains were resolved by the frozen third-pass adjudication procedure.
- These low exact-agreement rates reflect strict whole-object comparison over free-text, citations, and action plans; the dataset is therefore described as AI-assisted adjudicated synthetic gold, not high-agreement human annotation.
- Formal generation scoring uses the v1.2 strict-text metric clarification; no fuzzy/embedding/LLM judge is used.

