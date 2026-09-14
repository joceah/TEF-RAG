# TEF-RAG Agent Context

> **Canonical working context for coding/research agents.** Read this file first. Keep it short, current, and decision-oriented. Historical iteration details belong in `docs/DEVELOPMENT_HISTORY.md`.
>
> Updated: 2026-09-14  
> Current development branch: `tef-rag-v5.1-failure-attribution`

## 1. Research background: do not drift away from this

The most important project source is:

`docs/project_background/一种储能电站多模态异构数据的时空对齐与可信感知方法.docx`

**All later method and dataset iterations must remain grounded in the problem defined by this document unless the user explicitly changes the research direction.** The initial paper in `paper/TMC_RAG_ICRA_style_zh_v2.pdf` is useful historical context, but its method is not the final research target.

The core task is **embodied operation-and-maintenance planning for battery energy storage stations**, not generic temporal QA and not generic incident-log retrieval.

The system must combine heterogeneous evidence such as:

- unstructured procedures/manuals/safety documents;
- structured work orders, equipment records, alarms, maintenance history;
- BMS/SCADA state records;
- professional-model prediction evidence when applicable.

The downstream target is not only a natural-language answer. It should support a **structured work order and an executable/partially ordered embodied action plan**.

The original background identifies four enduring problem requirements:

1. **Context completeness** — procedure steps depend on section-level context, prerequisites and scope.
2. **Field precision** — device IDs, timestamps, alarm codes and other structured fields cannot be replaced by semantic approximation.
3. **Temporal/order correctness** — evidence availability and operation dependencies matter; unsafe reordering is not acceptable.
4. **Predictive support when needed** — health/trend decisions should use professional prediction evidence rather than asking the LLM to invent SOH/RUL behavior.

Do **not** reduce the research problem to a universal `Observation -> Diagnosis -> Action -> Verification` chain. That pattern may occur in some cases, but TEF-RAG should model a **query-conditioned task-support evidence flow** across heterogeneous sources. Depending on the query, a coherent flow may involve current state, historical precedent, forecast, applicable procedure, prerequisite, action support, correction/supersession, verification, or preserved uncertainty.

## 2. Hard constraints vs. learnable/optimizable selection

A central project principle is to separate **feasibility constraints** from **evidence selection policy**.

### Preserve as hard feasibility constraints

These are domain-validity rules, not the main claimed algorithmic novelty:

- target device/entity must be correct;
- `event_time <= query_time` when event time exists;
- `available_at <= query_time`;
- procedure/model/version validity must hold at query time;
- retrieval must never read gold/reference labels;
- future or unavailable evidence must not leak into retrieval;
- offline authoring/gold fields may be used only for diagnostics/evaluation.

### Do not freeze old engineering rules as the research contribution

The following are mutable implementation choices and may be replaced by better methods:

- fixed task-to-source routing;
- fixed source quotas such as N manuals / M work orders / one state / one forecast;
- BM25-only or dense-only choices;
- fixed parent/full-section restoration strategy;
- hand-written importance rules;
- manually fixed evidence-role or relation heuristics if a better auditable representation is developed.

The research direction is to let the algorithm decide **which valid evidence combination best supports the current maintenance task under a finite context budget**.

---

# 3. Two permanent workstreams

Unless the user explicitly changes the project direction, development must always advance along **both** of these workstreams. Do not optimize one while ignoring the other.

## A. DATA: build a benchmark that actually requires temporal evidence reasoning

The benchmark must test the failure modes that motivate TEF-RAG, rather than being solvable by `same device + newest records`.

### Data design invariants

- Difficulty must be designed **before** evaluating the target algorithm; do not delete or select queries post hoc because a method failed or succeeded.
- New validation/test data must be independent of the seen v5/v5.1 diagnostic set.
- Prefer fewer genuinely hard, independently reviewed cases over thousands of template-repeated easy paraphrases.
- Two paraphrases of one intent are not two independent events. Statistical analysis should cluster by intent / asset / authored chain or another defensible independent unit.
- Freeze benchmark construction rules and difficulty acceptance criteria before comparing new algorithms.
- A simple `Latest-5` baseline must be treated as a required difficulty audit. A temporal benchmark dominated by Latest-5-solvable queries is not an adequate primary validation set.
- Old hard subsets extracted after seeing results may be used for **development diagnostics only**, not relabeled as an independent test set.

### Difficulty families that should remain central

New data should include combinations of:

- `MULTI_EPISODE_DISAMBIGUATION`
- `CUTOFF_SENSITIVE`
- `LATE_ARRIVING_EVIDENCE`
- `SUPERSEDED_DIAGNOSIS`
- `PROCEDURE_VERSIONING`
- `CROSS_SOURCE_REQUIRED`
- `SIMILAR_SYMPTOM_DIFFERENT_CAUSE`
- `PERSISTENT_UNCERTAINTY`

The hard cases should include longer histories, interleaved episodes, corrections/reopenings, real procedure revision/withdrawal logic, multiple source dependencies, and cases where the newest visible records belong to the wrong branch/episode.

### Future annotation target

For a serious v6 validation set, prefer explicit annotation of a **canonical task-support evidence flow** or defensible support edges, rather than only a set of necessary evidence IDs. This enables a real `FlowComplete@k`-style metric instead of a projection-conditioned proxy.

---

## B. ALGORITHM: move from hard-coded retrieval policy to coherent task-support evidence selection

The algorithmic goal is not simply “more temporal weighting”. It is:

> **Within the hard validity/visibility constraints, retrieve a query-conditioned, complementary, coherent and auditable evidence set that supports the maintenance task under Top-k/context budget.**

The intended research evolution is:

`hard-rule TMC-RAG -> query-conditioned set selection -> correct evidence representation/graph -> task-support flow completion`

Do not redesign the algorithm before attributing the current failure mode. Search, representation/projection and objective errors must be separated experimentally.

---

# 4. Current status

## 4.1 Initial TMC-RAG / paper stage

The initial TMC-RAG pipeline demonstrated useful domain constraints: source-aware retrieval, bitemporal visibility, device/model/version filtering, procedure restoration, structured output and bounded repair. However, much of the retrieval policy was manually specified, so it is treated as an engineering baseline / historical stage rather than the final novelty claim.

## 4.2 TEF-RAG v5

v5 replaced path-prefix filling with a **query-conditioned set-level objective**:

`Semantic + DirectedChain + RoleCoverage - Redundancy`

with fixed weights in the frozen v5 implementation. It improved some ranking behavior but did not establish a complex-chain advantage over Scoped Hybrid.

On the frozen 16-query v5 stress set:

- complex-chain Scoped Hybrid: Recall@5 `0.6750`, nDCG@5 `0.6841`, Complete@5 `0.2500`;
- complex-chain TEF-RAG v5: Recall@5 `0.6750`, nDCG@5 `0.7074`, Complete@5 `0.1250`.

This set is now **seen diagnostic data**. It must not be tuned on and then reused as unbiased validation.

## 4.3 TEF-RAG v5.1 failure attribution — completed

Exhaustive exact set search was added using the same frozen v5 `score_set` objective.

Key result:

- 12/12 set-mode queries: Beam selected exactly the same set as Exact;
- mean/max objective gap: `0`;
- complex-chain metrics remain `0.6750 / 0.7074 / 0.1250`;
- 10 failed set-objective queries had a feasible gold-complete Top-5, yet the exact objective preferred an incomplete set in all 10; mean objective margin over the best gold-complete set: `0.0693` (diagnostic only).

Therefore **beam-search approximation is not the primary failure source on the current small candidate pools**.

However, v5.1 does **not** yet cleanly separate:

- query-profile error;
- role projection error;
- relation/evidence-graph projection error;
- set-objective misalignment.

The taxonomy strongly suggests representation and objective problems may coexist. Do not jump directly from “search is not the problem” to “the objective alone is proven wrong”.

## 4.4 `temporal_maintenance_dev_v2` difficulty audit — completed

This dataset is development material, not an independent test set.

Current audit summary:

- 1,152 queries / 576 intents;
- 192 synthetic chains;
- 48 target devices;
- `RECENCY_ONLY`: 956/1152 = `82.99%`;
- among 768 temporal queries, Latest-5 structurally covers all necessary evidence for 572 = `74.48%`;
- therefore only 196 temporal queries are `TEMPORAL_HARD_NOT_RECENCY_SOLVABLE` (`25.52%` of temporal, `17.01%` of all queries).

This means the full old dev set is dominated by recency-solvable tasks and cannot be the primary evidence for future TEF-v6 claims.

Important naming rule: the full-1152 frozen method result in this audit is **TMC-RAG-v2**, not TEF-RAG-v5. Do not label it simply `TEF` in future reports.

Known audit cleanup: fix the unrendered `{len(operational_hard)}` / percentage placeholder in the report.

---

# 5. Immediate next tasks

## Algorithm task: v5.2 Oracle Projection Attribution

Before defining v6, run a small offline counterfactual attribution study on the **seen diagnostic set only**.

Keep candidate pool, semantic scores, Top-k, budget, exact search and frozen objective unchanged. Compare combinations such as:

- current profile + current roles + current relations;
- oracle profile + current roles + current relations;
- current profile + oracle roles + current relations;
- current profile + current roles + oracle relations;
- oracle profile + oracle roles + oracle relations.

Purpose: distinguish whether failures are mainly caused by representation/projection or by the objective even when the representation is correct.

No oracle information may enter actual retrieval. Oracle variants are **offline diagnostic only**.

Decision logic after v5.2:

- oracle relation/representation largely fixes failures -> prioritize evidence graph / relation induction;
- oracle representation is correct but exact objective still prefers incomplete sets -> prioritize closure-/flow-completion-aware objective;
- mixed improvement -> v6 should address both graph induction and flow-aware set selection.

Do not retune v5 weights on the 16-query seen set.

## Data task: hard benchmark redesign

In parallel:

1. fix the current difficulty-audit reporting bug and TMC/TEF naming;
2. export the 196 `TEMPORAL_HARD_NOT_RECENCY_SOLVABLE` queries as a **dev diagnostic manifest only**;
3. design a new independent temporal-hard benchmark protocol before generating/scoring it;
4. predefine a Latest-5 difficulty acceptance criterion before method evaluation;
5. increase independent scenario diversity rather than template/paraphrase count;
6. add human review and, where feasible, canonical task-support flow annotations.

Do not create a “new test set” by simply filtering the old dev set after observing algorithm results.

---

# 6. What v6 is allowed to become

Do not implement v6 until v5.2 attribution and the new benchmark protocol are written down.

A likely v6 direction is some combination of:

- query-conditioned evidence graph/relation induction;
- closure-aware or flow-completion-aware set scoring;
- explicit reward for selecting evidence that belongs to one coherent task-support structure rather than disconnected role/relation fragments.

The final Top-k output may still be a **set**. Paths/flows can be latent scoring structures; do not reintroduce the old v4 mistake where a path becomes an atomic retrieval unit and is later prefix-truncated.

Any v6 objective, weights, success criteria and validation protocol must be preregistered/frozen before evaluating a new independent holdout.

---

# 7. Evaluation discipline

Always report retrieval and downstream generation separately.

Retrieval metrics currently include Recall@k, nDCG@k and Complete@k. For future flow-annotated data, add an explicit flow-completeness metric.

Do not treat:

- a query paraphrase as an independent event;
- protocol compliance as task correctness;
- citation-ID existence as semantic support;
- projected-graph flow diagnostics as canonical ground truth;
- aggregate performance on an easy benchmark as evidence of temporal reasoning advantage.

Always include simple controls: `Latest`, lexical/BM25 where meaningful, Hybrid, and the strongest valid external baselines that can be run correctly. Failed or compatibility-only external runs must be labeled honestly.

---

# 8. Agent execution rules

- Read this file first; read `docs/DEVELOPMENT_HISTORY.md` only when historical context is needed.
- Read the background DOCX before making a major research-direction change.
- Reuse existing code paths and shared scoring logic; do not create parallel implementations that silently diverge.
- Never use gold/authoring fields in retrieval.
- Do not silently change frozen data, objective weights or evaluation definitions.
- Do not call external online commercial LLM APIs. If an experiment genuinely needs an LLM, use the existing project-local OpenAI-compatible configuration and environment variables; never commit credentials.
- Keep unrelated local experiments out of commits. Stage/push only necessary files.
- Do not use `git add .`, `git add -A`, force-push, `git reset --hard`, or destructive cleaning in a mixed research workspace.
- Update this `CLAUDE.md` by **replacing current status/tasks**, not appending a long diary. Move obsolete milestones to `docs/DEVELOPMENT_HISTORY.md`.

---

# 9. Canonical reading order

For most work, read only what is needed:

1. `CLAUDE.md` — current research contract and task state.
2. `docs/project_background/一种储能电站多模态异构数据的时空对齐与可信感知方法.docx` — canonical problem background.
3. Relevant current implementation, especially `tef_rag_v5/` and current analysis scripts.
4. Current diagnostic reports under `experiments/analyses/`.
5. `docs/DEVELOPMENT_HISTORY.md` only for historical evolution.
6. `paper/TMC_RAG_ICRA_style_zh_v2.pdf` only when historical paper context is needed; it does not define the current final method.

If a future method conflicts with the background problem or either of the two permanent workstreams, stop and explicitly justify the change before implementing it.
