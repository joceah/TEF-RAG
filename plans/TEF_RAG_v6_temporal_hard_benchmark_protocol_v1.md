# TEF-RAG v6 Temporal-Hard Benchmark Protocol v1

**STATUS: DRAFT FOR USER REVIEW**

**NOT YET FROZEN**

**NO DATA GENERATED FROM THIS PROTOCOL YET**

> 2026-09-15 更新：此前保留的样本量、difficulty 配比、telemetry 生成范围、major stratum、审核与 test 使用策略已经给出确定方案；protocol 仍保持 DRAFT，等待用户最终确认后再以独立 commit 标记 `FROZEN BEFORE DATA GENERATION`。

## 1. 范围与研究问题

本文档是预登记草案，不授权生成数据。Benchmark 用于评价：面向储能电站具身运维任务规划，检索系统能否在设备/实体、query time、双时间可见性、model scope 和规程版本等硬约束下，恢复并选择 coherent、可审计、能够支撑当前任务的 **Temporal Evidence Flow**。

它不是普通 Temporal QA。目标证据包括规程、工单、维护历史、状态/趋势、告警、检查、更正、预测和验证记录，并最终支持结构化工单和有依赖关系的动作计划。

## 2. 三个必须分开的设计层次

### 2.1 Numerical Telemetry Distribution

电压、电流、温度、SOC 等 telemetry 的分布必须与事件结构、RAG 难度分开设计。正常观测占绝大多数；明显不合理偏离、传感器故障或通信/采集错误等极端异常点/片段必须很少，不能为了提高检索难度而增加其比例。

`数值异常 != 设备故障 != temporal-hard query`

Benchmark v1 采用 **280 Ah-class 方形 LFP 储能电芯**作为数值参考体系。公开资料支撑的物理 envelope 与本项目人为设定的生成 band 必须分开报告，见第 17 节。

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

用于评价 deployment-like synthetic mixture 下的稳定性。Telemetry 大部分正常，极端数值异常很少，temporal-hard task 不人为集中。不能把该层的人为 mixture 比例写成真实电站故障发生率，也不能仅凭该层证明 Temporal Evidence Flow mechanism superiority。

### 3.2 Temporal-Hard Challenge Set

专门压力测试 multi-episode、late arrival、supersession、procedure versioning、cross-source dependency、similar symptom/different cause 和 persistent uncertainty。它只提高任务结构难度，不提高极端 telemetry 异常比例。正式规模与 difficulty 配比见第 15–16 节。

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

它回答实际 Latest baseline 是否表现过强。即使两个阈值同为 0.40，它们也是不同字段、不同概念。

### 6.3 Major stratum

一个 difficulty 只有在 Challenge 中满足以下条件时才作为正式 `major stratum` 单独报告 Gate：

- 至少 `20` 条以该 difficulty 为 primary difficulty 的 authored chains；
- 对应至少 `60` 个 primary intents；
- validation 至少 `4 chains / 12 intents`；
- test 至少 `4 chains / 12 intents`。

每个 major stratum 必须满足：

`RECENCY_SOLVABLE_AT_5 rate <= 0.50`

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

Benchmark v1 采用 `1 s` raw telemetry cadence 作为生成/仿真的基础时间分辨率，RAG-facing state/trend evidence 以 `1 min` 为主要语义粒度，并可保留 `5 / 15 / 60 min` trend windows。`1 s` 是参考公开大型 BESS field dataset 后采用的 benchmark cadence，不声称是所有 LFP 储能系统的行业统一采样标准。

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

本草案已经指定规模、配比、telemetry 数值生成策略、major stratum、审核方案与 test 使用策略，但仍保持 `DRAFT_FOR_REVIEW`。用户最终确认后，必须使用单独 commit 将状态改为 `FROZEN BEFORE DATA GENERATION`，之后才能生成正式 benchmark。

Freeze 前还必须完成一次 protocol-level source audit，确保所有标记为“公开资料支撑”的物理 envelope 均有可追溯来源；任何缺少足够公开依据的具体数值必须明确标为 benchmark modeling choice，而不能包装成真实行业标准。

当前没有依据本草案生成任何 benchmark data、query、telemetry 或 test result。

## 15. 正式数据规模与 split

正式 benchmark 采用 `400 authored chains / 1200 independent primary intents / 2400 query rows / 100 target assets`。

每条 authored chain 固定设计 `3` 个不同 primary intents；每个 intent 生成 `2` 个表达版本，仅用于语言鲁棒性，不视为两个独立统计样本。

| Layer | Chains | Primary intents | Query rows | Target assets |
|---|---:|---:|---:|---:|
| Realistic Distribution Set | 200 | 600 | 1200 | 50 |
| Temporal-Hard Challenge Set | 200 | 600 | 1200 | 50 |
| Total | 400 | 1200 | 2400 | 100 |

两个 layer 都按 `60/20/20` 进行 chain-level split：

| Split / layer | Chains | Primary intents | Query rows |
|---|---:|---:|---:|
| development | 120 | 360 | 720 |
| validation | 40 | 120 | 240 |
| test | 40 | 120 | 240 |

Challenge 的 50 个 assets 按 development / validation / test = `30 / 10 / 10` exact asset-disjoint。Realistic 使用另外 50 个 target assets，与 Challenge 不重叠；Realistic 内部不强制 exact asset-disjoint，但仍执行 family/chain/intent isolation。

## 16. Difficulty 配比

### 16.1 Temporal-Hard Challenge Set

Challenge 的 200 chains 固定为：

- `160` 条 single-primary hard chains：8 种 difficulty 各 `20` 条；
- `40` 条 compositional-hard chains：每条组合 `2–3` 种 difficulty。

每个 primary difficulty 的 20 条 chains 按 development / validation / test = `12 / 4 / 4` 分配；40 条 compositional-hard chains 按 `24 / 8 / 8` 分配。这样每种 primary difficulty 至少包含 `60` 个 primary intents，其中 validation/test 各至少 `12` 个。

Compositional-hard 场景中的 secondary difficulty 标签用于组合分析，但不得把同一 chain 重复计算成多个独立样本。

### 16.2 Realistic Distribution Set

Realistic Set 是人为构造的 deployment-like synthetic mixture，不表示真实故障发生率：

- routine / mostly recency-solvable：`120 chains (60%)`；
- single temporal complication：`50 chains (25%)`；
- compound temporal-hard：`30 chains (15%)`。

对应每个 split 使用同一 60/25/15 比例：development `72/30/18`，validation `24/10/6`，test `24/10/6`。

## 17. Telemetry 参数与来源边界

### 17.1 公开资料支撑的 reference envelope

Benchmark v1 以 280 Ah-class 方形 LFP 储能电芯为 reference system。公开厂商资料支持：

- chemistry：LiFePO4 (LFP)；
- nominal capacity：`280 Ah`；
- nominal voltage：`3.2 V`；
- operating voltage：`2.50–3.65 V` when `T > 0°C`；在 `T <= 0°C` 的 Hithium 280Ah datasheet 中给出 `2.00–3.65 V`；
- ambient charging range：`0–60°C`；
- ambient discharging range：`-30–60°C`。

这些数值只作为 synthetic telemetry 的参考 envelope，不替代具体电站 BMS 保护阈值，也不能当作安全操作建议。公开来源中的温度范围明确是 **ambient temperature**；`cell_temperature` 是独立 telemetry variable，deterministic validator 不得把 cell sensor value 直接与 ambient envelope 比较。

### 17.2 Benchmark modeling choices

以下参数属于本 benchmark 的可复现实验设计，而不是行业统一标准：

- normal synthetic SOC window：`10–90%`；
- routine normalized charge/discharge P-rate：`normalized P-rate <= 0.5P`；
- high-load/high-charge episode：`0.5P < normalized P-rate <= 1.0P`；
- `>1.0P` 不作为正常持续状态，仅能在明确 transient/abnormal authored scenario 中使用；
- normal synthetic cell-temperature band：`15–35°C`；
- elevated but physically plausible：`35–45°C`；
- fault/event trend generation band：`45–55°C`；
- `>55°C` 只允许出现在明确高温事件。Cell temperature 超出 modeling band 不等于自动 dirty data，尤其不能因为 `cell_temperature > 60°C` 就套用 ambient datasheet threshold 判为 data-quality anomaly；应结合 authored scenario、thermal event context、source-backed evidence 与 continuity/trend 判断。明显不可能的值仍可标为 data-quality anomaly，但必须有独立于 ambient threshold 的依据。

P-rate 是 normalized power/energy rate，不是安培电流。若后续需要生成 synthetic current in amperes，必须由 authored electrical model（例如 `I = P / V`）推导，或另行定义清楚的 C-rate/current model；禁止把 `0.5P` 直接映射成任何 ampere 数值。HiTHIUM V3.3 的 standard charge/discharge rate `0.5P / 0.5P` 与 V1.1 的 max continuous charge/discharge rate `1P` 都是 manufacturer/version-specific specifications，不是所有 LFP 储能电芯的统一行业标准。

### 17.3 Sampling 与 RAG evidence

- raw telemetry cadence：`1 s`；
- RAG-facing state/trend evidence cadence：`1 min`；
- trend windows：`5 / 15 / 60 min`；
- summary 至少可包含 `min/max/mean/std/slope/last`；
- 长 episode 不要求长期保存全部秒级 raw points，可保留关键事件前后约 `±60 min` 的 1 s raw window，同时保存更长的分钟级 timeline/evidence。

公开的 RWTH Aachen M5BAT 大型储能 field dataset 提供 one-second-resolution 的 BMS/BSC 运行数据，因此 `1 s` raw cadence 是有现实数据先例的 benchmark design choice；该公开数据包含铅酸单元，不能被误写成 LFP-specific sampling standard。

### 17.4 极端 data-quality anomaly 比例

为了保持“极端数值脏点很少”的原则，冻结以下 modeling choice：

- gross data-quality outlier target：`0.02%` raw points；
- hard cap：`0.05%` raw points；
- 含 gross anomaly segment 的 authored chains：`<=2%`。

此比例是 benchmark 设计选择，不是公开统计得到的真实电站故障率。设备真实故障优先表现为持续、物理上可解释、可被多源证据 corroborate 的趋势，而不是单个夸张跳点。

## 18. 审核与质量控制策略

本项目没有可用的储能运维领域专家，因此 benchmark **不得宣称 expert-reviewed / field-certified**。审核采用“100% 自动结构检查 + 100% 公共资料支撑的 AI-assisted semantic review”，并把缺少专业人工审核作为论文限制明确披露。

### 18.1 全量自动检查

所有 `400` 条 chains 必须经过 deterministic validator，至少检查：

- schema、ID uniqueness、split/family/asset isolation；
- `event_time` / `available_at` 与 query cutoff；
- procedure version validity；
- required_groups / canonical flow / allowed_endpoint_pairs 一致性；
- telemetry 是否违反已声明的 source-backed envelope 或 modeling band；
- Latest-5 structural/performance Gate 所需统计；
- gold/authoring 不进入 retrieval input。

### 18.2 AI-assisted source-grounded semantic review

所有 `400` 条 chains 均进行至少一轮 AI-assisted semantic review。审核时必须优先查阅公开厂商 datasheet、公开 BESS field dataset、公开标准/论文或项目已有来源，检查：

- 事件演化是否物理上/业务上自洽；
- 真故障与 data-quality anomaly 是否被混淆；
- procedure/version/cutoff 是否构成真实时序差异；
- query 是否可由 query time 下合法 evidence 回答；
- required_groups 与 canonical flow 是否与 authored scenario 一致；
- hard sample 是否确实要求 temporal evidence flow，而非仅靠 recency。

所有 validation/test chains 进行第二轮 blind AI review pass，而不宣称 independent 或 expert review。第二轮 reviewer 在形成判断前看不到第一轮 verdict 和 reasoning；可以读取 authored chain、public sources、protocol、gold/canonical flow 与必要上下文，但必须先独立产出自己的 verdict/reasoning，之后才允许比较两轮结果。若使用不同 model/agent，review artifact 可记录 `reviewer_model`、`reviewer_version`、`review_pass_id`，但仍不得称为 expert review。

若两轮判断冲突或证据不足，标记 `REVIEW_UNRESOLVED`，在解决前不得进入 validation/test。解决方式只能是进一步查公开资料、修正 authored logic，或按预登记规则重新生成；不得根据 TEF-RAG retrieval 表现决定保留/删除。

### 18.3 论文披露

最终论文/报告应使用类似表述：`public-source-grounded, AI-assisted reviewed synthetic benchmark`，而不是 `expert-reviewed benchmark`。同时明确：缺少现场运维专家复核与真实电站工单验证，是 benchmark 的 external-validity limitation。

## 19. Development / Validation / Test 使用策略

- development：query/evidence/gold/canonical flow 全部可见，用于方法开发与错误分析；
- validation：gold/canonical flow 可用于模型选择、ablation 和成功判据检查，可重复评价；
- test：query/evidence 对方法可见，gold/canonical flow 在正式 primary evaluation 前对方法开发隐藏，仅由 evaluator 读取。

Test gold/canonical flow 在生成后必须作为独立 evaluator artifact 保存并计算 SHA256；在正式 test evaluation 前，不应提交到公开开发分支。只有当 v6 architecture、objective、weights、baseline protocol 全部冻结后，才运行正式 primary test。

Test semantic review 必须在 sealed evaluator/review workflow 内完成。主算法开发流程只能收到 aggregate QC：test chain 总数、passed/unresolved 数、source-audit pass/fail、artifact hashes 与 schema validation status；不得接收 per-item gold、required_groups、canonical flow、reviewer reasoning 或 failure interpretation。

顺序固定为：生成 test authored chains → deterministic validation → first AI semantic review → second blind AI review → unresolved repair/regeneration → final test artifact → SHA256 → sealed → 冻结 v6 architecture/objective/weights/baselines → primary test evaluation。Unresolved 修复后必须重新生成 final hash；target method 在 final seal 前不得评价，禁止先看 test retrieval 结果再修改 test chain。

若因为 evaluator/code bug 必须重跑 test，需要记录 bug 原因、修改内容、修改前后 commit，并明确该修复是否改变算法；不得根据 test outcome 继续调算法后仍把该 test 称为 untouched test。

## 20. 公开来源与“资料支撑 vs modeling choice”纪律

机器可读 `public_sources` registry 为每条来源固定 `name`、`vendor_or_institution`、`version_or_date`、`access_date`、`supports`、`url`，有 DOI 时另记 `doi`。当前至少包括：

1. HiTHIUM V1.1 EU English datasheet：支持 280Ah/LFP/3.2V/voltage、ambient temperature 与 `1P` max continuous rate。
2. HiTHIUM 20240918 V3.3 Chinese datasheet：支持相应产品规格与 `0.5P/0.5P` standard rate。
3. HiTHIUM current product page：仅作当前产品 identity/context corroboration。
4. REPT BATTERO 2025 energy-storage brochure：仅交叉印证 280Ah/3.2V/2.50–3.65V stationary-LFP reference choice。
5. RWTH Aachen M5BAT dataset（DOI `10.18154/RWTH-2026-06637`）：仅支持 `one_second_resolution_BESS_field_data`；其记录对象为 lead-acid，绝不支持 LFP temperature、LFP voltage range 或 LFP sampling standard。

文档和最终论文必须清楚区分：

- `source-backed envelope`：公开资料直接支持的规格/数据特征；
- `benchmark modeling choice`：为了可复现 synthetic benchmark 而人为冻结的 SOC window、temperature bands、anomaly ratio、difficulty mixture、split size 等。

没有公开来源直接支持的 modeling choice 不得写成“行业真实统计”或“厂商安全阈值”。
