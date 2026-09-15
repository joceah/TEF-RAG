# TEF-RAG v6 Temporal-Hard Benchmark Protocol v1

**STATUS: DRAFT FOR USER REVIEW**  
**NOT YET FROZEN**  
**NO DATA GENERATED FROM THIS PROTOCOL YET**

## 1. Scope and research question

This is a preregistration draft, not authorization to generate data. The benchmark evaluates whether a retrieval system can recover a coherent, current-task-supporting **Temporal Evidence Flow** for embodied maintenance planning in energy-storage power stations. Evidence must remain valid under hard device/entity, query-time, bitemporal visibility, model-scope, and procedure-version constraints.

The benchmark is not generic Temporal QA. Its target is selecting an auditable evidence set from procedures, work orders, maintenance history, state/trend evidence, alarms, inspections, corrections, predictions, and verification records, so downstream systems can construct structured work orders and dependency-aware action plans.

## 2. Three separate design layers

### 2.1 Numerical Telemetry Distribution

Voltage, current, temperature, SOC, and any later user-approved telemetry ranges must be governed separately from event and RAG difficulty design. Normal observations must dominate. Extreme anomalous points or segments—implausible deviations, sensor faults, or communication/acquisition errors—must be rare and must never be inflated merely to make retrieval harder.

`numerical anomaly != device fault != temporal-hard query`

Actual physical ranges, sampling frequencies, and anomaly rates remain `DRAFT_FOR_REVIEW`; they must be supported by domain sources or expert review before freezing.

### 2.2 Operation & Maintenance Event Structure

Scenarios must use realistic business logic across state observation, alarm, diagnosis, work order, inspection, correction, reopen, supersession, procedure applicability, repair, verification, and persistent uncertainty. A chain may omit irrelevant stages; no fixed Observation→Diagnosis→Action→Verification template is required.

### 2.3 RAG Temporal Difficulty

Difficulty labels may overlap and must be assigned from authored structure before target-method evaluation:

- `MULTI_EPISODE_DISAMBIGUATION`
- `CUTOFF_SENSITIVE`
- `LATE_ARRIVING_EVIDENCE`
- `SUPERSEDED_DIAGNOSIS`
- `PROCEDURE_VERSIONING`
- `CROSS_SOURCE_REQUIRED`
- `SIMILAR_SYMPTOM_DIFFERENT_CAUSE`
- `PERSISTENT_UNCERTAINTY`

## 3. Two benchmark layers

### 3.1 Realistic Distribution Set

This layer estimates deployment-like stability. Telemetry is mostly normal, extreme numerical anomalies are rare, and temporal-hard tasks occur at a natural rather than artificially concentrated rate. It must not be used alone to claim superiority of a Temporal Evidence Flow mechanism.

### 3.2 Temporal-Hard Challenge Set

This layer directly stresses multi-episode histories, late arrival, supersession, procedure versioning, cross-source dependency, similar symptoms with different causes, and persistent uncertainty. It raises structural task difficulty without raising the extreme telemetry anomaly rate. Challenge proportions and sample counts remain `DRAFT_FOR_REVIEW`.

## 4. Independence, splits, and paraphrases

The intended splits are `development`, `validation`, and `test`.

- An authored chain cannot cross splits.
- An intent and all its paraphrases must share a split.
- Parameterized near-copies of one scenario template cannot be placed in development and test and then treated as independent evidence.
- Test scenarios require independent event combinations, not only renamed assets or shifted dates.
- Paraphrases may measure robustness, but do not constitute independent primary samples.
- Primary sample units are independent intents/chains. Main uncertainty estimates and significance tests must cluster by `intent_id`, `chain_id`, and, where appropriate, `asset_id`.

## 5. Canonical task-support flow annotation

Every Challenge query must provide an author-defined `canonical_task_support_flow`, created before algorithm evaluation and never inferred backward from retrieval outputs. Its schema requires:

- `required_nodes`
- `required_groups`
- `support_edges`
- `update_edges`
- `supersession_edges`
- `prerequisite_edges`
- `verification_edges`

An edge list may be empty when that relation is genuinely absent, but the field must exist. Nodes and edges must be legal at the query cutoff. Authoring/gold annotations remain evaluator-only and cannot enter retrieval.

## 6. Bitemporal and procedure-version requirements

Every evidence record must distinguish `event_time` from `available_at`. Late-arrival scenarios may have `event_time << available_at`; paired cutoffs must include one after the event but before evidence arrival and another after arrival, producing different legal evidence flows.

Procedure-version scenarios require V1, V2, and V3 with `valid_from`, `valid_to`, `supersedes`, `withdrawn_at`, and `model_scope`. Query cutoffs must cover each version's applicability period. In at least some scenarios, executable steps must materially differ across versions; cosmetic revision text is insufficient.

## 7. Evidence units and telemetry pipeline

The primary retrieval unit is an operation-semantic evidence record, not a mass of raw samples:

`raw time series → statistics / detector / predictor → state snapshot / trend card / event evidence → RAG`

Raw telemetry may support evidence generation and validation. Predictions such as SOH/RUL must come from identified professional models or authored evidence rather than free-form LLM invention.

## 8. Metrics

Primary retrieval metrics at the frozen `Top-k = 5` are:

- `Recall@5`
- `nDCG@5`
- `Complete@5`
- `FlowComplete@5`

`FlowComplete@5` is 1 only when the selected Top-5 satisfies all required groups/nodes and all query-applicable required canonical flow edges; it is defined from authoring flow, never the evaluated model's projected graph. `edge_recall` and `flow_node_recall` are secondary diagnostics. Retrieval and downstream generation are reported separately.

## 9. Baselines and fairness

Required baselines are Latest, BM25, Hybrid, TMC-RAG-v2 as a historical engineering baseline, the frozen current TEF-RAG version, and relevant external baselines that can run correctly. All methods share Top-k, evidence corpus, query cutoff, and visibility constraints. An external method whose intended mechanism did not activate must be marked `compatibility run`, not presented as a complete reproduction.

## 10. Latest-5 acceptance gate

Before any target-algorithm comparison, run a structural Latest-5 audit on the Challenge Set. Draft acceptance requires:

`Challenge Set overall Latest-5 Complete@5 <= 0.40`

No major difficulty stratum may be almost entirely solved because it is dominated by `RECENCY_ONLY` cases. The exact definition of “major stratum” and any additional per-stratum ceiling remain `DRAFT_FOR_REVIEW`.

If generated data fail this gate, the dataset may be regenerated or expanded only through preregistered generation rules. Item-wise deletion or selection based on TEF-RAG success/failure is prohibited.

## 11. Multi-step retrieval boundary

Queries may be tagged `long_span`, `multi_episode`, or `revision_history`. This round does not implement decomposition or multi-step retrieval. Adaptive Temporal Decomposition may be considered only after a frozen benchmark demonstrates systematic single-step failure.

## 12. Prohibited leakage and reinterpretation

- The old 196-query hard subset remains a seen development diagnostic subset, never a new test.
- Gold, authoring roles, canonical flows, and reference answers are evaluator-only.
- No test filtering may depend on the observed outcome of TEF-RAG or another target method.
- No v5 weight/objective change, v6 implementation, reranker, TreeRAG, or data generation is part of this protocol-drafting round.

## 13. Freeze and execution gates

This draft may change after user review. A later explicit user approval and separate commit are required to change status to `FROZEN BEFORE DATA GENERATION`. Before freezing, the user must confirm at least:

- dataset and per-layer sample sizes;
- challenge difficulty proportions and combinations;
- physical telemetry ranges, sampling frequencies, and rare-anomaly limits;
- “major stratum” definition and any per-stratum Latest-5 ceiling;
- human/domain review process and acceptance thresholds;
- validation/test release and access policy.

No benchmark data, query, telemetry, or post-generation result has been created under this draft.
