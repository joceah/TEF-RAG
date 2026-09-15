# TEF-RAG v6 Benchmark v1 Generation Summary

- Protocol freeze commit: `b0e6e004378e7d7f29cabece1efa6b2c30489e9b`
- Generator preregistration commit: `4302f68a1542b8b9d8498e2f158ebb8262c0684a`
- Effective generator revision after structural-validator corrections: `35db271602314028afa553d71ce4849c10cf9dc2`
- Accepted generation: attempt `0`, seed `20260915`
- Dataset status: `UNREVIEWED_CANDIDATE`
- Review status: `PENDING_AI_SEMANTIC_REVIEW`
- Target-method runs: `0`
- Semantic review performed: `false`

## Counts

- Authored chains / primary intents / query rows / target assets: `400 / 1200 / 2400 / 100`
- Realistic / Challenge chains: `200 / 200`
- Per-layer development / validation / test chains: `120 / 40 / 40`
- Per-layer development / validation / test query rows: `720 / 240 / 240`
- Challenge single-primary / compositional-hard chains: `160 / 40`
- Each primary Challenge difficulty: `20` chains, split `12 / 4 / 4`, `60` primary intents

## Gates

- Challenge `RECENCY_SOLVABLE_AT_5`: `0.1067` (`<= 0.40`, PASS)
- Challenge Latest-5 `Complete@5`: `0.1067` (`<= 0.40`, PASS)
- Every major stratum: `120` query rows; maximum `RECENCY_SOLVABLE_AT_5 = 0.3333` (`<= 0.50`, PASS)

## Validation and artifacts

- Deterministic dataset validator: `PASSED`, `0` errors
- Public dataset path: `data/generated/tef_v6_temporal_hard_benchmark_v1/`
- Full public artifact hashes: `data/generated/tef_v6_temporal_hard_benchmark_v1/manifest.json`
- Public evidence SHA256: `b8e115346f23f237cddf45270ab875e0f26b9a1bd94555dc9ce439f774b0470d`
- Development / validation / test query SHA256: `09d27e4755d2c627ba009acec52b6d669932b063c28d2957fa4f0dbc85982f2c` / `3fce79d94c1ef3ae12a46fa219b639c6ed6409f1a01c1edaa71977cd2d0d162e` / `f12402ead57b79d26180a81e0b121d723a5e9cb88fd14eb71031f201c3e67c18`
- Sealed test artifact: `.local_sealed/tef_v6_benchmark_v1_test_evaluator.jsonl`
- Sealed record count / SHA256 / committed: `480` / `544155811b3ba64ab5407b6222fa73d063659a0d516a24e46182c1dd1c3b4a2d` / `false`

No TEF-RAG/v6, reranker, multi-step retriever, or external target method was run. No item-level AI semantic audit or blind second review was performed in this generation round.
