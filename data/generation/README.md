# TEF-RAG v6 generation benchmark

The generation gold is public because the formal blind test evaluation has completed.

- `gold_development.jsonl` / `gold_development_index.jsonl`
- `gold_validation.jsonl` / `gold_validation_index.jsonl`
- `gold_test.jsonl` / `gold_test_index.jsonl`
- `schema.json`, `alias_registry.json`, and `parameter_registry.json`

The test artifacts intentionally preserve their audited byte representations:

- `gold_test.jsonl`: historical audited source bytes (CRLF), SHA-256 `dccf5a831b9b145d5aab26288088d14d2e9af6fafd06d4eced3a22983a7c9aea`.
- `gold_test_index.jsonl`: canonical public LF representation, SHA-256 `8433880d300e541713aba7eae86564bcb705f6f9c638043a66d7262f5b195d35`.

`.gitattributes` marks the historical test gold as binary so Git does not rewrite its line endings. The index is reconstructed from the public frozen benchmark inputs using the original deterministic builder ordering. No private files are needed to read or validate this released directory.

Validate it with:

```bash
python -m scripts.validate_tef_rag_v6_public_generation
```
