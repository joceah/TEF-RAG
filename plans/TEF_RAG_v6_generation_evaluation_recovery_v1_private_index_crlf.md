# TEF-RAG v6 private index CRLF recovery protocol v1

This is an evaluation recovery protocol. It is not generation protocol v1.10.

The generation protocol remains `v1.9-exact-duplicate-root-field-suffix`.
Frozen predictions, the generation manifest, scoring implementation, schema,
registries, prompt, and retrieval inputs remain unchanged.

The first private evaluation attempt created its one-shot lock and failed before
JSON parsing or scoring because the private index raw SHA differed from the
frozen public LF seal. Public reconstruction proved that the private file is
exactly the canonical reconstructed bytes with every LF translated to CRLF;
parsed rows and all semantic fields are equal.

This recovery accepts only that audited representation. It requires the frozen
manifest and original failed lock, absence of all original evaluation outputs,
the unchanged scoring fingerprint and prediction hashes, the canonical public
index SHA, the observed private raw SHA
`5904d4b4e65bafa9c0accef2a66fb4c3d96ea29b2cbfdc6b7b9e6002675511d6`, and
exact byte equality to `canonical_lf.replace(b"\n", b"\r\n")`. It also checks
the 240 parsed rows, their order and complete dictionaries, unique semantic
IDs, and 480 unique query IDs.

All public checks happen before an atomic
`evaluation_recovery_crlf_v1_started.json` lock. Private files are read only
after that lock exists. The original `evaluation_started.json` is never
deleted or overwritten. Recovery writes only
`metrics_recovery_crlf_v1.json`,
`final_evaluation_recovery_crlf_v1_manifest.json`, and the external
`evaluation_details_v1_recovery_crlf/` directory. It never creates or
overwrites the original metrics or final manifest.

The recovery imports and calls the frozen evaluator functions for private gold
validation and metric scoring. It does not change expected hashes, rewrite the
private index, normalize arbitrary newlines, or implement a second metric
formula. A recovery lock is atomic and one-shot; any existing recovery lock or
output fails closed.
