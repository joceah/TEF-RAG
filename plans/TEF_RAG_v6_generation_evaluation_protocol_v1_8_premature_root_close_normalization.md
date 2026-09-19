# TEF-RAG v6 generation evaluation protocol v1.8

## Premature root close normalization

The v1.7 formal run remained an archival failed run. It produced 319 partial
prediction rows, was never frozen or evaluated, and never accessed private
generation gold or its index. The failure at
`TEFV6-C0059-I02-post_arrival-P2` was an `assistant_content_json` failure:
DeepSeek returned a valid HTTP JSON envelope whose assistant content closed
the root object before `action_plan`. All three existing attempts failed and
the v1.7 parser correctly rejected the content.

Before a new formal run, v1.8 adds one deterministic transport normalization
mode named `premature_root_close`. It is considered only after strict parsing
raises `Extra data`, and only when:

1. `raw_decode()` returns a dictionary and the consumed prefix ends in one
   structural `}`;
2. the remaining text begins immediately with `,"<key>":`;
3. `<key>` is a declared top-level property of the frozen generation schema
   and is absent from the decoded dictionary;
4. removing exactly that one consumed root-closing character and reparsing the
   complete string with strict `json.loads()` produces one dictionary with no
   trailing content.

No other character is inserted, removed, reordered, escaped, balanced, or
synthesized. Quote repair, comma repair, generic brace balancing, trailing
text deletion, semantic correction, and multi-edit recovery remain forbidden.
In particular, a remainder that repeats a root key already present in the
decoded object is rejected as a duplicate-root-key case; the archived v1.7
assistant content remains archival and is not rewritten or made resumeable.
Schema validation, evidence-grounding validation, and the existing one-repair
policy run unchanged after normalization. The normalization does not consume
the one allowed repair request.

Accepted rows record `parse_mode=premature_root_close`, original and accepted
content hashes, one removed character, the original JSON error message and
position, the recovered root key, and the normalization version. Strict and
`single_extra_closing_brace` provenance remain unchanged.

Because this changes parser acceptance semantics, v1.8 has a new protocol and
formal session identity. The new result namespace is
`results/v6/generation_eval_v1_8_premature_root_close/` and the new API cache
namespace is
`.cache/tef_rag_v6_generation_eval_v1_8_premature_root_close/`. The v1.7
partial rows and cache are archival and must not be reused or rewritten.

This clarification changes transport parsing only. It does not change the
model, endpoint, prompt, schema, retrieval predictions, metric definitions,
canonicalization, temperature, thinking mode, or one-repair policy.
