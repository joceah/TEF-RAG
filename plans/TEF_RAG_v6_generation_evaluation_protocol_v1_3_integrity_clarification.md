# TEF-RAG v6 Generation Evaluation Protocol v1.3 Integrity Clarification

Status: frozen before any formal generation prediction or scoring. This clarification uses only the v1/v1.1/v1.2 protocol and published development/validation generation gold. It does not revise private gold, retrieval outputs, citation definitions, dependency closure, or numeric tolerance.

## Parameter representation

The published development and validation gold contain 461 parameter entries, all direct strings. The v1 structured `{value, unit}` form is retained. The narrow compatible schema accepts exactly either a direct string evidence value or an object with exactly `value` and `unit`. `value` is a number, a string, or a numeric range object with exactly `lower` and `upper`; `unit` is a string or null. Arbitrary nested objects, lists, booleans, and extra fields are invalid. A direct string is matched only against another direct string after the frozen text and parameter-name canonicalization; no numeric or unit meaning is inferred from it. Structured numeric values use the v1 absolute tolerance of 1e-6 after conversion to equivalent SI units. Ranges require both boundaries to match. The frozen conversion set is V/mV/kV, A/mA, Ω/ohm/kΩ/kohm, Pa/kPa/MPa, s/ms/min/h, and K/°C/℃. Unsupported unit spellings are compared literally after text normalization; no new parameter aliases or inferred units are introduced.

## Duplicate actions

Neither the original gold builder nor the v1.1 canonicalizer enforces uniqueness of canonical `(action_type, target, parameters)` within a plan. Published development and validation gold contain no duplicate canonical-action plans. v1.3 makes gold canonical-action uniqueness an explicit evaluation gate. If any private gold plan contains duplicate canonical actions, formal scoring stops for independent adjudication; the evaluator must not choose a favorable pairing using gold dependency, citation, or recommendation scores.

Prediction duplicate actions remain allowed as false positives under one-to-one maximum-cardinality matching. Candidate prediction actions are ordered by their own canonical tuple, recommendation membership, cited evidence, and incoming/outgoing dependency structure expressed as canonical action tuples. Gold candidates are ordered by canonical tuple. Raw prediction IDs do not select a pairing. Dependency comparison remains based on DAG transitive closure; unknown raw dependency endpoints are additionally counted as false-positive dependency predictions.

## Formal session and sealing

The five retrieval methods share one formal `generate --all` session. A session fingerprint binds runner source, generator instructions, schema, request configuration, official endpoint, frozen public benchmark artifacts, and sealed retrieval predictions. Every saved row records its session and initial/repair request fingerprints. Freeze and evaluation recheck them before private access. The evaluator additionally locks runner/evaluator source and registries, refuses repeat formal scoring, and writes private item-level details only outside the repository.

The private gold and private index are paired by row only after their two independently frozen aggregate SHA256 values both match. The index hash must be supplied from the original independent sealing environment. No per-item private hash or index metadata is published.
