# TEF-RAG v6 Generation Evaluation Protocol v1.2 Metric Clarification Addendum

Status: frozen before the first formal generation evaluation.

This addendum does not alter any generation gold object, annotation decision, citation,
action, dependency, or v1.1 canonicalization result. It only clarifies deterministic
matching for free-text slots and the interpretation of exact-match metrics.

## 1. Deterministic text canonicalization

Before metric comparison, textual slots use the frozen `generation-canonical-v1.2`
pipeline:

1. Unicode NFKC normalization;
2. case folding where applicable;
3. full-width/half-width, whitespace, and Chinese/English punctuation normalization;
4. lookup in the frozen alias registry;
5. if no alias exists, use the normalized literal string unchanged.

No embedding similarity, edit-distance threshold, LLM judge, or post-hoc synonym
expansion is permitted.

The rule applies to `diagnosis.concept`, `verification_or_uncertainty.statement`,
action `target`, and other textual scalar slots.

## 2. Strict metric interpretation

The following metrics are intentionally strict protocol-conformance metrics:

- `Field Macro-F1 (strict)`;
- `Work-Order Joint EM (strict)`;
- `Action F1 (strict tuple)`;
- `Plan EM (strict)`;
- `End-to-End EM (strict)`.

For these metrics, an unregistered paraphrase is not treated as equal merely because
it may be semantically similar. This makes the score a conservative lower bound on
semantic equivalence rather than an open-ended semantic-judge score.

`Action F1 (strict tuple)` matches actions on canonical
`(action_type, target, parameters)` as defined in v1. `Dependency F1`, schema
validity, order validity, and citation metrics retain their existing definitions.

## 3. Grounding complement

Strict lexical metrics must be reported together with grounding/structure metrics,
especially `Dependency F1` and `Citation Accuracy/F1`. A method must not be described
as semantically wrong solely because it misses strict text EM when its structured
and citation-grounding metrics are correct.

No LLM-based evaluator is introduced in v1.2.

## 4. Generator-side normalization

All compared retrieval methods must use the same frozen generation model, prompt,
schema, repair policy, and canonicalization instructions. The generator should be
instructed to emit concise evidence-derived canonical phrases instead of stylistic
paraphrases.

The generator must not receive generation gold, test alias answers, method-specific
vocabulary, or any test-derived synonym table.

## 5. Registry freeze

The alias and parameter registries may be finalized using protocol design plus
development/validation data before the first formal generation evaluation. After
the first method prediction is scored, they are frozen and must not be expanded in
response to validation/test errors or model outputs.

This addendum therefore resolves metric reproducibility without changing the sealed
generation gold.
