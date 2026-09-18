# TEF-RAG v6 sealed evaluator provenance audit

Date: 2026-09-18  
Scope: provenance only; no sealed scoring and no evaluator JSONL parsing.

## Finding

The expected evaluator hash is
`477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3`.
The sole named local evaluator is
`.local_sealed/tef_v6_benchmark_v1_test_evaluator.jsonl`, 528,640 bytes,
created at 2026-09-15 17:54:16 +08:00 and last written at
2026-09-15 18:17:56 +08:00. Its SHA256 is
`544155811b3ba64ab5407b6222fa73d063659a0d516a24e46182c1dd1c3b4a2d`.

## `477bb7...` provenance

The first Git record of `477bb7...` is commit
`c791af4b7fd4b3b0afc30e76cc75cd98657e189c` (`data: publish semantic
TEF-RAG v6 benchmark candidate`, 2026-09-15 23:52:09 +08:00). That commit
records the hash in the semantic benchmark manifest, README, review metadata,
and review summary. The metadata identifies the authoring context as
`GPT-5.6 Sol direct semantic authoring` and the storage as
`PRIVATE_USER_LIBRARY_SEALED_ARTIFACT`. Later commit
`157f7f82902b8eb09525c501c492b71a539bccb3` retained the same hash after the
formal blind review.

The committed public materializer explicitly excludes sealed test gold and
cannot recreate the evaluator. No repository script records a copy operation
that placed the `477bb7...` artifact at `.local_sealed`.

## `544155...` provenance

The first Git record of `544155...` is commit
`cb95cd95e2fa4e5fbddd8a0e3b32a51041ca2e4b` (`data: generate TEF-RAG v6
benchmark v1 candidate`, 2026-09-15 18:20:12 +08:00). Its manifest labels the
dataset `UNREVIEWED_CANDIDATE`, names the same local evaluator path, records
480 rows, and records exactly `544155...`.

`scripts/generate_tef_v6_benchmark_v1.py` deterministically writes test rows
directly to `.local_sealed/tef_v6_benchmark_v1_test_evaluator.jsonl`, then
hashes that file into the candidate manifest. The local file's last-write time
(18:17:56) immediately precedes the candidate commit and matches the generator
development/run window. This is strong provenance that the present local file
is the old rule-generated candidate left in place when the semantic candidate
was published later that evening.

The `544155...` hash also appears in the subsequent replacement/history chain,
including commits `d8dbf48716ec2481c6aef46beae6a1529268fae4` and `c791af4...`, as the old
hash was replaced by the semantic candidate metadata.

## Copy search and serialization assessment

A path/name scan under `D:\electric-project` and the Codex attachments area
found only the current named evaluator. A SHA-only scan of 333 JSON/JSONL
candidates in the repository and attachments area found no file with hash
`477bb7...`.

There is no evidence that the two hashes are merely newline or deterministic
serialization variants. No `477bb7...` byte source is locally available for a
normalization comparison, and evaluator contents were not opened. More
importantly, `544155...` belongs to the old rule-generated candidate whose
public test-query hash was
`f12402ead57b79d26180a81e0b121d723a5e9cb88fd14eb71031f201c3e67c18`, while
the semantic benchmark associated with `477bb7...` records public test-query
hash `9044c29a0ba531ba26c579c5aac467b80786185da06801d9f7aee653f0f23898`.
The provenance therefore points to different benchmark materializations, not
a proven formatting-only difference.

## Recommendation

Recover/export the private Library sealed artifact whose SHA256 is exactly
`477bb7...`, place it at a new verified local path, and hash-check it without
opening it. Do not overwrite the current `544155...` file until it has been
preserved as the old candidate and the replacement provenance is recorded.
Only after the exact expected hash is present should the already-frozen
predictions proceed to their first formal sealed evaluation.

Integrity state: predictions were not modified or rerun; test gold and private
blind-review artifacts were not accessed; evaluator content was not opened;
formal sealed evaluations remain zero.
