# TEF-RAG v6 generation benchmark

The generation gold is public because the blind test evaluation has completed.

- `gold_development.jsonl` / `gold_development_index.jsonl`
- `gold_validation.jsonl` / `gold_validation_index.jsonl`
- `gold_test.jsonl` / `gold_test_index.jsonl`
- `schema.json`, `alias_registry.json`, and `parameter_registry.json`

The canonical test files are byte-stable LF JSONL. The published SHA-256 values are:

- `gold_test.jsonl`: `dccf5a831b9b145d5aab26288088d14d2e9af6fafd06d4eced3a22983a7c9aea`
- `gold_test_index.jsonl`: `8433880d300e541713aba7eae86564bcb705f6f9c638043a66d7262f5b195d35`

The index is reconstructed from the public frozen benchmark inputs using the same deterministic builder ordering as the formal run. No private files are needed to read or validate this directory.
