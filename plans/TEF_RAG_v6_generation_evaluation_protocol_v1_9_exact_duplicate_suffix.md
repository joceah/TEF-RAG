# TEF-RAG v6 generation evaluation protocol v1.9

## Exact duplicate root-field suffix normalization

The archived production failure was not a premature root close. Each response
contained a complete first JSON object with both declared root fields, followed
by a byte-identical duplicate `action_plan` field suffix. The v1.8
`premature_root_close` experiment is withdrawn and is not part of this formal
protocol.

After strict parsing fails with `JSONDecodeError: Extra data`, v1.9 may accept
one and only one deterministic transport form. A duplicate-key-rejecting JSON
decoder must raw-decode the first value, which must be a dictionary with no
duplicate keys. The complete remainder must have exactly the grammar
`,"<root_key>":<json_value>}` followed only by JSON whitespace. The suffix
must contain exactly one root field; its key must be a declared frozen-schema
top-level property already present in the first object. Its value must parse
strictly with duplicate-key rejection and must be both Python-structurally
equal and canonically JSON-equal to the first object's value for that key.

When all conditions hold, the accepted result is the first complete object and
its original JSON text prefix. No field is reconstructed or merged. Any value
difference, second suffix field, trailing fragment, second object, malformed
JSON, undeclared key, duplicate key, or generic longest-valid-prefix case is
rejected. Quote repair, comma repair, brace balancing, arbitrary suffix
deletion, semantic repair, and field synthesis remain forbidden.

The accepted row records
`parse_mode=exact_duplicate_root_field_suffix`, provider/cleaned/accepted
hashes, the duplicated root key, the original `Extra data` message and
position, the exact suffix hash and length, canonical hashes for both values,
the equality marker, and this normalization version. Schema validation,
grounding validation, and the existing one-repair policy run normally after
transport normalization.

Because this tightens the parser contract, v1.9 has a new formal identity:

- result namespace: `results/v6/generation_eval_v1_9_exact_duplicate_suffix/`
- cache namespace: `.cache/tef_rag_v6_generation_eval_v1_9_exact_duplicate_suffix/`
- protocol version: `v1.9-exact-duplicate-root-field-suffix`

The old v1.7 partial rows and the withdrawn v1.8 experiment are archival and
must not be resumed or rewritten.
