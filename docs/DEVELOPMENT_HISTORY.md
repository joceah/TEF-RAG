# TEF-RAG Development History

> Historical record only. Agents should read `CLAUDE.md` first for the current research contract, active tasks, and non-negotiable project principles. Do not use this file as the source of truth for the current method.

## 0. Canonical background

The project originates from the storage-station embodied O&M problem defined in:

`docs/project_background/一种储能电站多模态异构数据的时空对齐与可信感知方法.docx`

The initial paper is archived at:

`paper/TMC_RAG_ICRA_style_zh_v2.pdf`

The research problem remains grounded in heterogeneous evidence retrieval for battery energy storage station maintenance planning, with structured work-order and action-plan outputs.

---

## 1. Initial TMC-RAG stage

The first complete prototype organized retrieval by source and encoded many domain constraints explicitly.

Key mechanisms included:

- source-aware retrieval over procedures, work orders, state and prediction records;
- bitemporal visibility using event time and available time;
- device/model/version applicability checks;
- historical windows and freshness rules;
- procedure chunk retrieval followed by full-section restoration;
- structured work-order and action-plan generation;
- runtime validation and at most one bounded repair.

This stage demonstrated that domain-validity constraints matter, but the retrieval policy itself relied heavily on hand-written routing, quotas and rules. It is therefore treated as an engineering baseline and historical precursor rather than the final algorithmic contribution.

---

## 2. Early TEF-RAG iterations

The project then shifted from rule-heavy source allocation toward temporal evidence organization and evidence-flow retrieval.

Historical v1-v4 implementations remain in the repository for reproducibility. Their details should not be copied forward blindly. The important accumulated lesson was that treating a path as an atomic retrieval unit and later truncating it to Top-k can create inconsistent outputs and break evidence completeness.

v4 in particular exposed path-prefix truncation and trace/final-result consistency problems, motivating a set-level reformulation.

---

## 3. TEF-RAG v5 — query-conditioned set selection

v5 introduced a dedicated set-level selector under hard visibility/validity constraints.

The frozen objective jointly scores:

- semantic relevance;
- directed-chain evidence relations;
- query-conditioned evidence-role coverage;
- redundancy penalty.

The design changed the core question from “which individual records rank highest?” or “which path should be filled first?” to “which Top-k evidence set has the best joint utility for this query?”.

The v5 implementation also repaired prior trace inconsistencies and prevented non-selected path nodes from contributing chain score.

### v5 stress-set result

A new small frozen stress set contained 4 cases, 48 records and 16 queries: 8 `complex_chain`, 4 `cutoff_sensitive`, and 4 `latest_control`.

On the 8 complex-chain queries:

- Scoped Hybrid: Recall@5 `0.6750`, nDCG@5 `0.6841`, Complete@5 `0.2500`;
- TEF-RAG v5: Recall@5 `0.6750`, nDCG@5 `0.7074`, Complete@5 `0.1250`.

The preregistered advantage criterion was not met. v5 improved some ordering behavior but did not improve mean complex-chain recall and reduced complete-set hits.

This 16-query set became seen diagnostic data after analysis and must not be reused as an unbiased holdout after tuning.

---

## 4. TEF-RAG v5.1 — failure attribution

v5.1 was created specifically to determine whether v5 failures came from beam-search approximation or from the representation/objective itself.

Changes included:

- exhaustive exact set search over the same candidate pool;
- shared scoring callback with beam search;
- Beam-vs-Exact per-query analysis;
- structural diagnostics;
- deterministic failure taxonomy;
- additional tests for exact optimality and complementarity behavior.

### Main result

On all 12 set-mode queries:

- Beam set = Exact set for `12/12` queries;
- mean objective gap = `0`;
- max objective gap = `0`.

On the 8 complex-chain queries, Exact produced the same `0.6750 / 0.7074 / 0.1250` Recall/nDCG/Complete result as Beam.

Among 10 failed set-objective queries, a gold-complete Top-5 set was feasible in all 10, but the exact v5 objective scored an incomplete set strictly higher in all 10. The diagnostic mean margin was `0.0693`.

Conclusion: search approximation is not the primary failure source on these small candidate pools. Remaining uncertainty is between query/profile/role/relation representation errors and set-objective misalignment.

---

## 5. `temporal_maintenance_dev_v2` dataset expansion

A much larger synthetic development dataset was archived with:

- 48 target devices;
- 192 authored chains;
- 1,152 queries / 576 intents;
- structured provenance, authoring metadata, evaluation gold and reproducibility scripts.

This dataset was intended to broaden temporal maintenance scenarios, but a later difficulty audit showed that raw size overstated effective difficulty.

### Difficulty audit

Key audit findings:

- `RECENCY_ONLY`: `956/1152 = 82.99%`;
- temporal queries: `768`;
- temporal queries structurally solvable by Latest-5: `572/768 = 74.48%`;
- therefore `TEMPORAL_HARD_NOT_RECENCY_SOLVABLE`: `196` queries, or `25.52%` of temporal queries and `17.01%` of all queries.

The audit also found that old frozen TMC-RAG-v2 behavior was not uniformly better than Latest on the hardest structural strata. It performed more clearly on multi-episode disambiguation and similar-symptom/different-cause cases, but not reliably on procedure-versioning, cross-source, or late-arrival strata.

Conclusion: the old dev benchmark is dominated by recency-solvable tasks and is unsuitable as the primary validation benchmark for a future v6 claim.

---

## 6. Current transition point

At the end of v5.1 and the dataset difficulty audit, two research bottlenecks are established:

1. **Algorithm attribution:** search has been ruled out as the primary issue, but projection/representation error and objective misalignment still need to be separated.
2. **Benchmark quality:** the existing large dev set contains too many Latest-solvable cases and needs a new independent temporal-hard benchmark protocol.

The active forward plan is maintained in `CLAUDE.md` and currently centers on:

- v5.2 Oracle Projection Attribution;
- independent temporal-hard benchmark redesign;
- only then preregistering and implementing v6.

---

## Maintenance rule for this file

Append only major completed milestones and stable conclusions. Do not turn this into an experiment diary. Intermediate run logs, parameter sweeps and temporary hypotheses belong in experiment reports or branch-specific notes.
