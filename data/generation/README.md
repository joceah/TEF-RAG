# Structured-generation benchmark

This directory contains structured work-order and action-plan references for development, validation, and test data.

- gold_*.jsonl — structured reference outputs.
- gold_*_index.jsonl — mapping between semantic references and query IDs.
- schema.json — output schema.
- alias_registry.json and parameter_registry.json — deterministic normalization rules.

~~~bash
python -m scripts.validate_public_generation
python -m scripts.evaluate_public_generation --predictions /path/to/predictions
~~~
