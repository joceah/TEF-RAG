# temporal_maintenance_dev_v2 Difficulty Audit

> **DIAGNOSTIC ONLY.** 本审计读取 authoring chain、gold evidence 与 evaluation metadata 仅用于离线难度刻画和冻结结果评测；这些字段不得进入 retrieval。未修改算法、权重或数据，未调用 LLM。数据为 dev，不是独立 test；未混入 v5 16-query stress set。

## Dataset overview

- 1152 query / 576 intent（每个 intent 两种确定性表达），192 条合成链，48 台目标设备。
- ordinary 384，temporal 768。扩展记录没有逐条专家审核，query 不能视为 1152 个独立真实事件。
- 本审计复用冻结 `rankings_combined.jsonl` 与仓库既有 `score()`，Top-k 固定为 5。

## Difficulty taxonomy and deterministic rules

结构标签来自 authored scenario、双 cutoff、必要证据组的 record kind / asset、规程场景和 persistent_unknown 标记。`RECENCY_ONLY` 采用可审计的结构判据：同设备、双时间可见、按 `(event_time, available_at)` 倒序的前 5 条覆盖全部必要证据组。它可以与其他标签共存，表示题目虽有时序措辞，但 Latest-5 已足够，并非由某算法失败反推。

## Difficulty distribution

| Difficulty | Count | Percent |
|---|---:|---:|
| RECENCY_ONLY | 956 | 82.99% |
| MULTI_EPISODE_DISAMBIGUATION | 144 | 12.50% |
| CUTOFF_SENSITIVE | 768 | 66.67% |
| LATE_ARRIVING_EVIDENCE | 96 | 8.33% |
| SUPERSEDED_DIAGNOSIS | 192 | 16.67% |
| PROCEDURE_VERSIONING | 96 | 8.33% |
| CROSS_SOURCE_REQUIRED | 96 | 8.33% |
| SIMILAR_SYMPTOM_DIFFERENT_CAUSE | 96 | 8.33% |
| PERSISTENT_UNCERTAINTY | 96 | 8.33% |

平均每 query 2.205 个标签。普通/temporal 的完整分布见 `difficulty_summary.json`。

## Recency-solvable analysis

全部 query 中 Latest-5 结构可解 956/1152（82.99%）；768 个 temporal query 中为 572/768（74.48%）。这直接衡量“same device + newest records”是否覆盖 gold，而不是把 Latest 的最终均值当作难度定义。

## Baseline capability matrix (Recall@5 / nDCG@5 / Complete@5)

| Difficulty | N | Latest R/nDCG/C | BM25 R/nDCG/C | Hybrid R/nDCG/C | TMC-RAG-v2 (frozen) R/nDCG/C |
|---|---:|---:|---:|---:|---:|
| ALL | 1152 | 0.9397/0.9356/0.8299 | 0.0900/0.0764/0.0113 | 0.3496/0.3073/0.1441 | 0.9460/0.9320/0.8446 |
| TEMPORAL_HARD_NOT_RECENCY_SOLVABLE | 196 | 0.6454/0.7339/0.0000 | 0.1594/0.1555/0.0000 | 0.3975/0.3887/0.0510 | 0.6990/0.7516/0.1531 |
| RECENCY_ONLY | 956 | 1.0000/0.9769/1.0000 | 0.0757/0.0602/0.0136 | 0.3398/0.2906/0.1632 | 0.9966/0.9690/0.9864 |
| MULTI_EPISODE_DISAMBIGUATION | 144 | 0.8808/0.8589/0.6667 | 0.0486/0.0375/0.0139 | 0.3981/0.3999/0.0903 | 0.9132/0.9085/0.7222 |
| CUTOFF_SENSITIVE | 768 | 0.9095/0.9033/0.7448 | 0.1207/0.1070/0.0039 | 0.4489/0.4227/0.1432 | 0.9189/0.8980/0.7669 |
| LATE_ARRIVING_EVIDENCE | 96 | 0.9948/0.9826/0.9792 | 0.1094/0.0822/0.0000 | 0.4635/0.4013/0.2812 | 0.9818/0.9354/0.9271 |
| SUPERSEDED_DIAGNOSIS | 192 | 0.9635/0.9257/0.9167 | 0.1771/0.1586/0.0000 | 0.3919/0.3556/0.1354 | 0.9635/0.9189/0.9062 |
| PROCEDURE_VERSIONING | 96 | 0.6354/0.7338/0.0000 | 0.2917/0.2906/0.0000 | 0.5269/0.5096/0.0938 | 0.6250/0.6941/0.0000 |
| CROSS_SOURCE_REQUIRED | 96 | 0.6354/0.7338/0.0000 | 0.2917/0.2906/0.0000 | 0.5269/0.5096/0.0938 | 0.6250/0.6941/0.0000 |
| SIMILAR_SYMPTOM_DIFFERENT_CAUSE | 96 | 0.8976/0.9222/0.6458 | 0.0156/0.0080/0.0000 | 0.4401/0.4068/0.1562 | 0.9479/0.9346/0.8125 |
| PERSISTENT_UNCERTAINTY | 96 | 0.9653/0.9424/0.9375 | 0.0990/0.0789/0.0000 | 0.3472/0.3153/0.1354 | 0.9757/0.9310/0.9375 |

**方法命名说明：** 全 1152 题的冻结主方法结果 `tmc_v2` 明确标为 `TMC-RAG-v2 (frozen)`；它不是 TEF-RAG-v5。仓库没有覆盖该数据集全部题目的 TEF-RAG-v5 运行，因此不伪造或混入 16 题 stress set。逐 difficulty 数值见 `baseline_by_difficulty.csv`，逐层 TMC-RAG-v2-vs-Latest 的 Recall/nDCG/Complete 胜平负见 `tmc_rag_v2_vs_latest_wtl.csv`。

## Important examples

- **MULTI_EPISODE_DISAMBIGUATION** — `query-00af11ffa381af13a6755722` (C10 同设备并发工单): RECENCY_ONLY: all necessary evidence groups are covered by the five newest visible records for the target device; MULTI_EPISODE_DISAMBIGUATION: the authored task distinguishes recurrence, reopening, or concurrent work episodes on the same asset; CUTOFF_SENSITIVE: the paired authored query cutoffs expose different evidence states and answers
- **CUTOFF_SENSITIVE** — `query-00372df8d5cda241241ed50e` (C15 对象更正): RECENCY_ONLY: all necessary evidence groups are covered by the five newest visible records for the target device; CUTOFF_SENSITIVE: the paired authored query cutoffs expose different evidence states and answers; SUPERSEDED_DIAGNOSIS: a later correction, review, or investigation updates an earlier account
- **LATE_ARRIVING_EVIDENCE** — `query-015606c7aa995f566355976b` (C09 监测缺失与事后回顾): RECENCY_ONLY: all necessary evidence groups are covered by the five newest visible records for the target device; CUTOFF_SENSITIVE: the paired authored query cutoffs expose different evidence states and answers; LATE_ARRIVING_EVIDENCE: the scenario explicitly separates event time from later evidence availability; PERSISTENT_UNCERTAINTY: the authored chain remains underdetermined at the later cutoff and requires uncertainty to be preserved
- **SUPERSEDED_DIAGNOSIS** — `query-00372df8d5cda241241ed50e` (C15 对象更正): RECENCY_ONLY: all necessary evidence groups are covered by the five newest visible records for the target device; CUTOFF_SENSITIVE: the paired authored query cutoffs expose different evidence states and answers; SUPERSEDED_DIAGNOSIS: a later correction, review, or investigation updates an earlier account
- **PROCEDURE_VERSIONING** — `query-059c88dac32319f975d5c791` (C12 型号与计划依赖): CUTOFF_SENSITIVE: the paired authored query cutoffs expose different evidence states and answers; PROCEDURE_VERSIONING: the answer depends on the procedure/model rule valid at the query time; CROSS_SOURCE_REQUIRED: necessary evidence spans multiple record kinds or assets
- **CROSS_SOURCE_REQUIRED** — `query-059c88dac32319f975d5c791` (C12 型号与计划依赖): CUTOFF_SENSITIVE: the paired authored query cutoffs expose different evidence states and answers; PROCEDURE_VERSIONING: the answer depends on the procedure/model rule valid at the query time; CROSS_SOURCE_REQUIRED: necessary evidence spans multiple record kinds or assets
- **SIMILAR_SYMPTOM_DIFFERENT_CAUSE** — `query-00ea5499346b790a447f9220` (C07 相似症状): RECENCY_ONLY: all necessary evidence groups are covered by the five newest visible records for the target device; CUTOFF_SENSITIVE: the paired authored query cutoffs expose different evidence states and answers; SIMILAR_SYMPTOM_DIFFERENT_CAUSE: the scenario contrasts similar symptoms whose supported explanation differs
- **PERSISTENT_UNCERTAINTY** — `query-00839f8970d26b5e4c559b05` (C08 环境相关与因果): RECENCY_ONLY: all necessary evidence groups are covered by the five newest visible records for the target device; CUTOFF_SENSITIVE: the paired authored query cutoffs expose different evidence states and answers; SUPERSEDED_DIAGNOSIS: a later correction, review, or investigation updates an earlier account; PERSISTENT_UNCERTAINTY: the authored chain remains underdetermined at the later cutoff and requires uncertainty to be preserved

## Main findings and dataset gaps

768 个 temporal query 中，572 个（74.48%）的必要证据已被 Latest-5 结构覆盖；只有 196 个（25.52%）同时具有时序结构标签且 Latest-5 不能覆盖。该 196-query 清单是 **seen development diagnostic subset，NOT independent validation/test**。总体均值因此主要测到设备过滤与倒序覆盖。更关键的是，TMC-RAG-v2 (frozen) 在 `PROCEDURE_VERSIONING/CROSS_SOURCE_REQUIRED` 的 Recall@5 为 0.6250，低于 Latest 的 0.6354，Complete@5 均为 0；在 `LATE_ARRIVING_EVIDENCE` 也低于 Latest（0.9818 vs 0.9948）。它只在 `MULTI_EPISODE`（0.9132 vs 0.8808）和 `SIMILAR_SYMPTOM_DIFFERENT_CAUSE`（0.9479 vs 0.8976）显示较清楚的 Recall 优势。因此数据偏易与算法未稳定利用 hard structure 两者同时存在。

当前设计的主要缺口是：difficulty 由 16 个原型模板参数化复制，类别与 scenario 高度绑定；两个改写共享 intent/gold；缺少更多相互独立的 cutoff 对、跨链交织的长历史、自然形成的多源缺失组合，以及真实规程修订/撤回链。`CUTOFF_SENSITIVE` 覆盖广但不等于 cutoff 决策困难，必须结合 Latest-5 可解率解释。

## Recommendation

采用“both、数据优先”的决策：先补充独立、人工复核、Latest-5 无法凭倒序覆盖的 temporal-hard 开发/验证任务，再在现有 hard strata 上修正算法。原因是当前 benchmark 的模板重复和 recency coverage 会显著稀释难度；同时若 TMC-RAG-v2 (frozen) 在现有 hard strata 没有稳定胜过简单基线，也不能只归因于数据过易。禁止在 dev 上按结果删题或继续调权重后覆盖本审计。

## Limitations

- 标签规则是设计语义审计，不是专家逐 query 复标；`CROSS_SOURCE_REQUIRED` 用必要证据跨 record kind/asset 的保守定义。
- query 级百分比包含成对改写；论文统计应按 intent 或 asset/chain 聚类给区间。
- 只评检索 Recall/nDCG/Complete，不评价最终答案的因果措辞、安全性或不确定性表达。
