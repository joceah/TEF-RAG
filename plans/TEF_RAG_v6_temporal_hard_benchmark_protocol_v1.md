# TEF-RAG v6 Temporal-Hard Benchmark Protocol v1

**STATUS: DRAFT FOR USER REVIEW**

**NOT YET FROZEN**

**NO DATA GENERATED FROM THIS PROTOCOL YET**

## 1. 范围与研究问题

本文档是预登记草案，不授权生成数据。Benchmark 用于评价：面向储能电站具身运维任务规划，检索系统能否在设备/实体、query time、双时间可见性、model scope 和规程版本等硬约束下，恢复并选择 coherent、可审计、能够支撑当前任务的 **Temporal Evidence Flow**。

它不是普通 Temporal QA。目标证据包括规程、工单、维护历史、状态/趋势、告警、检查、更正、预测和验证记录，并最终支持结构化工单和有依赖关系的动作计划。

## 2. 三个必须分开的设计层次

### 2.1 Numerical Telemetry Distribution

电压、电流、温度、SOC 及后续经用户确认的 telemetry，其分布必须与事件结构、RAG 难度分开设计。正常观测占绝大多数；明显不合理偏离、传感器故障或通信/采集错误等极端异常点/片段必须很少，不能为了提高检索难度而增加其比例。

`数值异常 != 设备故障 != temporal-hard query`

实际物理范围、采样频率和稀有异常比例仍为 `DRAFT_FOR_REVIEW`，冻结前需由领域来源或专家审核支持。

### 2.2 Operation & Maintenance Event Structure

场景应以真实业务逻辑组织 state observation、alarm、diagnosis、work order、inspection、correction、reopen、supersession、procedure applicability、repair、verification 和 persistent uncertainty。每条链只包含与任务有关的阶段，不强制套用 Observation→Diagnosis→Action→Verification 模板。

### 2.3 RAG Temporal Difficulty

难度标签允许重叠，必须在评价目标算法之前根据 authored structure 确定：

- `MULTI_EPISODE_DISAMBIGUATION`
- `CUTOFF_SENSITIVE`
- `LATE_ARRIVING_EVIDENCE`
- `SUPERSEDED_DIAGNOSIS`
- `PROCEDURE_VERSIONING`
- `CROSS_SOURCE_REQUIRED`
- `SIMILAR_SYMPTOM_DIFFERENT_CAUSE`
- `PERSISTENT_UNCERTAINTY`

## 3. 双层 Benchmark

### 3.1 Realistic Distribution Set

用于评价 deployment-like distribution 下的稳定性。Telemetry 大部分正常，极端数值异常很少，temporal-hard task 以自然比例出现。不能仅凭该层证明 Temporal Evidence Flow mechanism superiority。

### 3.2 Temporal-Hard Challenge Set

专门压力测试 multi-episode、late arrival、supersession、procedure versioning、cross-source dependency、similar symptom/different cause 和 persistent uncertainty。它只提高任务结构难度，不提高极端 telemetry 异常比例。Challenge 的类型配比和样本量仍为 `DRAFT_FOR_REVIEW`。

## 4. Split、family 与资产隔离

预定 split 为 `development`、`validation`、`test`。每个案例必须包含 `scenario_family_id`、`template_family_id`、`asset_id`、`chain_id` 和 `intent_id`。

- 同一 `chain_id` 不能跨 split。
- 同一 `intent_id` 及其所有 paraphrase 必须位于同一 split。
- 同一 `scenario_family_id` 不得同时出现在 test 与 development/validation；Test scenario family 必须隔离。
- 同一 `template_family_id` 禁止跨 development、validation、test。只改设备 ID、平移日期或轻微改变数值不构成独立 test case。
- Temporal-Hard Challenge Test 的 target `asset_id` 必须与 Challenge development/validation exact asset-disjoint；设备型号或 model class 可以重复。
- Realistic Distribution Set 不强制 exact asset-disjoint，但仍必须满足 chain、intent、scenario family 和 template family isolation。
- Test 场景必须具有独立事件组合，不能只是参数化近复制。
- Paraphrase 只用于 robustness，不作为独立 primary sample。主要统计以独立 intent/chain 为单位，并按 `intent_id`、`chain_id` 及适用时的 `asset_id` 聚类。

## 5. `RECENCY_SOLVABLE_AT_5` 的确定性定义

对每个 query：

1. 只保留满足当前 query 全部硬约束的 evidence：target asset/entity 正确，`event_time <= query_time`，`available_at <= query_time`，procedure/model/version 在 query time 合法。
2. 合法 evidence 按 `(event_time, available_at, evidence_id)` 降序排列；`evidence_id` 是 deterministic tie-break。
3. 取最新 Top-5。
4. 若该 Top-5 覆盖全部 `required_groups`，则 `recency_solvable_at_5 = true`，否则为 `false`。

这是“数据结构能否被 newest records 直接解决”的判据，不等同于 Latest baseline 的实际 Recall/Complete。

## 6. Latest-5 双重难度 Gate

在任何目标算法比较之前，Challenge Set 必须同时通过两个互不混淆的 Gate。

### 6.1 Structural Difficulty Gate

`Challenge Set overall RECENCY_SOLVABLE_AT_5 rate <= 0.40`

它回答数据本身是否需要非平凡时间结构。

### 6.2 Baseline Performance Sanity Check

`Challenge Set overall Latest-5 Complete@5 <= 0.40`

它回答实际 Latest baseline 是否表现过强。即使两个草案阈值目前同为 0.40，它们也是不同字段、不同概念。

主要 difficulty stratum 不能被 `RECENCY_ONLY` / `RECENCY_SOLVABLE_AT_5` 大量主导，但 `major_stratum_definition` 和 `major_stratum_recency_solvable_ceiling` 均保持 `DRAFT_FOR_REVIEW`，等待样本量与 difficulty 配比确定后再冻结。

若生成后的数据未通过 Gate，只能按照预登记生成规则整体重新生成或扩充；禁止根据 TEF-RAG 或其他目标方法的逐题成功/失败筛选或删除样本。

## 7. Group-aware Canonical Task-Support Flow

每个 Challenge query 必须具有在算法评价前定义的 `canonical_task_support_flow`，且不能根据检索输出反向构造。

### 7.1 Required groups

每个 `required_group` 必须具有稳定的 `group_id` 和 `acceptable_evidence_ids`。例如 `G1 = [A1, A2]` 表示 A1 或 A2 任意一个就能满足该 evidence requirement，不要求两者全部出现。`required_groups` 是 `Complete@5` 的 primary completeness semantics：Top-5 必须对每个 group 至少命中一个 acceptable evidence。

`required_nodes` 仅是可选的 diagnostic/provenance annotation，可用于作者标记、来源追踪和 node-level analysis；它不是 `Complete@5` 的 primary requirement，也不要求其中所有节点都被检索到。

### 7.2 Required flow edges

Primary flow constraint 使用 `required_flow_edges`。每条 edge 至少包含 `edge_id`、`from_group`、`to_group`、`relation_type` 和 `allowed_endpoint_pairs`。

```json
{
  "edge_id": "E1",
  "from_group": "G1",
  "to_group": "G2",
  "relation_type": "supports",
  "allowed_endpoint_pairs": [["A1", "B2"], ["A2", "B1"]]
}
```

虽然多个 evidence 均可分别满足 G1/G2，但只有 authoring 明确列出的 endpoint pair 才能构成 canonical flow edge。Node-level `support_edges`、`update_edges`、`supersession_edges`、`prerequisite_edges`、`verification_edges` 继续作为 authoring/diagnostic metadata 保留。

## 8. `FlowComplete@5` 正式定义

对每个 required group `Gi`，定义 assignment `f(Gi) = ei`，其中 `ei` 必须既属于 `acceptable_evidence_ids(Gi)`，也属于 retrieved Top-5。在一个具体 assignment 中，每个 group 只选择一个 evidence；同一个 group 在所有相连 edge 中必须复用同一个 evidence，不能在不同 flow edge 中切换。Evaluator 可以枚举多个候选 assignment。

`FlowComplete@5 = 1` 当且仅当同时满足：

1. `Complete@5 = 1`；
2. **存在（EXISTS）至少一个全局一致的 group-to-evidence assignment**，为每个 required group 选择一个 retrieved acceptable evidence；
3. 同一个 assignment 同时满足全部 `required_flow_edges`：对每条 `Gi -> Gj`，`[f(Gi), f(Gj)]` 都属于该 edge 的 `allowed_endpoint_pairs`。

Assignment 不要求 injective。同一 evidence 可以同时赋给多个 group，但仅当该 evidence 被每个相关 group 的 `acceptable_evidence_ids` 明确接受。额外的干扰 evidence 不会导致失败；只要存在一组全局一致 assignment 即为成功。若每条 edge 分别能找到局部合法 pair、却无法由同一组 evidence selection 同时满足整条 canonical flow，则 `FlowComplete@5 = 0`。

因此明确允许且必须能评价：`Complete@5 = 1, FlowComplete@5 = 0`。

示例：G1=[A1,A2]，G2=[B1,B2]，合法 pair 只有 A1→B2、A2→B1。若模型选择 A1+B1，则两个 group 都已覆盖，Complete@5=1；但 A1→B1 不合法，所以 FlowComplete@5=0。这正是 FlowComplete 区别于元素覆盖完整性的意义。

运维示例：Episode 1 为“持续温升 → 风机故障 → 风机检修”，Episode 2 为“瞬时温度尖峰 → 温度传感器漂移 → 传感器校准”。若 Retriever 返回本次持续温升、风机故障、传感器漂移和传感器校准，各 group 虽均有 evidence，`Complete@5` 可以为 1；但不能把两个 episode 的局部关系拼成一条 flow。若不存在一致的“异常 → 诊断 → 动作”assignment，则 `FlowComplete@5 = 0`。

BM25、Latest、Hybrid 等 baseline 不需要预测 relation graph。离线 evaluator 只用 `retrieved evidence set + author-defined canonical_task_support_flow` 检查约束，因此所有 baseline 可公平评价。

Primary metrics 为 `Recall@5`、`nDCG@5`、`Complete@5`、`FlowComplete@5`；`edge_recall` 和 `flow_node_recall` 仅作 secondary diagnostics。Retrieval 与 downstream generation 分开报告。

## 9. 双时间与规程版本要求

每条 evidence 必须区分 `event_time` 与 `available_at`。Late-arrival 场景允许 `event_time << available_at`；成对 cutoff 至少包含“事件已发生但 evidence 尚不可见”和“evidence 已到达”两个时点，并要求不同的合法 evidence flow。

Procedure versioning 场景要求 V1、V2、V3，并包含 `valid_from`、`valid_to`、`supersedes`、`withdrawn_at`、`model_scope`。Query cutoff 覆盖每个版本适用期；至少部分场景的可执行步骤必须实质不同，不能只做文字修订。

## 10. Evidence unit 与 telemetry pipeline

RAG 的主要检索单元是有运维语义的 evidence record，而不是海量 raw samples：

`raw time series → statistics / detector / predictor → state snapshot / trend card / event evidence → RAG`

Raw telemetry 可用于生成和验证 evidence。SOH/RUL 等预测必须来自明确的专业模型或 authored evidence，不能由 LLM 自由臆造。

## 11. Baseline 与公平性

必须包含 Latest、BM25、Hybrid、TMC-RAG-v2 历史工程基线、当前冻结 TEF-RAG，以及能够正确运行的相关 external baseline。所有方法共享 Top-k、evidence corpus、query cutoff 和 visibility constraint。预期机制没有实际激活的外部方法必须标为 `compatibility run`，不能写成完整复现。

## 12. Multi-step retrieval 边界

Query 可以标记 `long_span`、`multi_episode`、`revision_history`。本轮不实现 decomposition 或 multi-step retrieval；只有冻结 benchmark 证明 single-step 系统性失败后，才考虑 Adaptive Temporal Decomposition。

## 13. 泄漏与禁止事项

- 旧 196-query hard subset 仍是 seen development diagnostic subset，绝不是新 test。
- Gold、authoring roles、canonical flow 和 reference answer 只能由 evaluator 读取。
- Test 选择不得依赖 TEF-RAG 或其他目标方法的结果。
- 本轮不修改 v5 权重/objective，不实现 v6、reranker、TreeRAG，不生成 benchmark data/query/telemetry。

## 14. Freeze 与执行 Gate

本草案可在用户 review 后修改。只有用户明确批准，后续独立 commit 才能把状态改为 `FROZEN BEFORE DATA GENERATION`。冻结前仍需用户确认：

- 两层数据集及各 split 的样本量；
- Challenge difficulty 类型配比与组合；
- telemetry 物理范围、采样频率和稀有异常比例；
- `major_stratum_definition` 与 `major_stratum_recency_solvable_ceiling`；
- 人工/领域审核流程与验收标准；
- validation/test 发布和访问策略。

当前没有依据本草案生成任何 benchmark data、query、telemetry 或 test result。
