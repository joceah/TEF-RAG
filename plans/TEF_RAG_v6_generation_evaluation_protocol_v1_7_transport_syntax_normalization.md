# TEF-RAG v6 generation evaluation protocol v1.7

## Transport syntax normalization clarification

After the v1.6 correction, no new formal generation or scoring run started. Private generation gold and its index have never been accessed. Independent diagnostics using the frozen Chat Completions request and the Responses API `json_schema` request reproduced the same provider transport artifact: a complete JSON object followed by exactly one additional `}`.

This v1.7 change is provider transport syntax handling. It is not semantic or schema repair. It does not change the model, official Chat Completions endpoint, prompt, frozen schema, retrieval outputs, metrics, canonicalization, temperature, thinking mode, max tokens, or one-repair policy. Responses API is diagnostic-only and is not part of the formal experiment.

The formal path remains:

```text
HTTP response
-> finish_reason check
-> strict JSON parse, or the single approved transport normalization
-> schema and evidence-grounding validation
-> at most one existing repair request
```

The shared parser first applies the existing whitespace, BOM, and JSON fence cleanup, then calls `json.loads`. A strict object is accepted unchanged. Only a `json.JSONDecodeError` whose message is exactly `Extra data` may enter the diagnostic path. The parser uses `JSONDecoder.raw_decode` and accepts the result only when the first value is a dictionary and the remaining text is exactly one character, `}`. It then parses the prefix again and verifies that the resulting dictionary is identical. Any whitespace plus `}`, multiple braces, arbitrary trailing text, incomplete JSON, malformed strings, or non-object first value is rejected with the original parse failure.

This normalization does not count as the one allowed schema/grounding repair because it changes no JSON field or value. `finish_reason=length` is rejected before parsing and never enters normalization. Formal cache entries and prediction rows persist the parse mode and content hashes so cache hits and frozen artifacts retain the same provenance without publishing raw assistant content.
