# TEF-RAG 开发历史

> 本文件只记录历史演进。Agent 应先阅读 `CLAUDE.md`，以获取当前研究契约、正在执行的任务与不可改变的核心原则。不要把本文件当作当前方法的唯一事实来源。

## 0. 项目背景基准

本项目源于以下文件所定义的储能电站具身运维问题：

`docs/project_background/一种储能电站多模态异构数据的时空对齐与可信感知方法.docx`

初版论文归档于：

`paper/TMC_RAG_ICRA_style_zh_v2.pdf`

研究问题始终围绕：

> 面向储能电站运维任务规划，对多源异构证据进行可信检索与组织，并支撑结构化工单和具身动作计划生成。

---

## 1. 初版 TMC-RAG 阶段

第一个完整原型按数据来源组织检索，并显式编码了大量领域约束。

主要机制包括：

- 对规程、工单、状态和预测记录进行分源检索；
- 使用 event time 与 available time 实现双时间可见性；
- 设备 / 型号 / 版本适用性检查；
- 历史时间窗口与 freshness 规则；
- 规程 chunk 检索后恢复完整章节；
- 生成结构化工单和动作计划；
- 运行时校验，并最多进行一次受控修复。

该阶段证明了领域有效性约束确实重要，但 retrieval policy 本身高度依赖人工路由、quota 与规则。因此目前将其视为：

> **工程基线与历史前身，而不是最终算法创新点。**

---

## 2. 早期 TEF-RAG 迭代

项目随后从“规则驱动的多源分配”逐步转向“时序证据组织与 evidence-flow retrieval”。

v1-v4 的历史实现保留在仓库中，用于复现和追溯，但其具体做法不应被机械复制到后续版本。

这一阶段最重要的累积经验是：

> 把一条 path 当作原子检索单元，之后再通过 Top-k 截断，会造成结果不一致并破坏证据完整性。

尤其 v4 暴露了 path-prefix truncation 以及 trace 与最终结果不一致的问题，因此推动了后续集合级重构。

---

## 3. TEF-RAG v5 —— 查询条件化的集合级选择

v5 在硬时间 / 有效性约束内，引入独立的 set-level selector。

冻结 objective 联合考虑：

- semantic relevance；
- directed-chain evidence relations；
- query-conditioned evidence-role coverage；
- redundancy penalty。

核心问题从：

> “哪几条单独相关性最高？”

或：

> “应该先填哪条 path？”

转变为：

> **“对于当前 query，哪一个 Top-k evidence set 的联合效用最高？”**

v5 同时修复了旧版本 trace 不一致的问题，并保证未实际被选择的 path 节点不会贡献 chain score。

### v5 stress set 结果

新的冻结 stress set 包含：

- 4 个案例；
- 48 条记录；
- 16 个 query；
- 其中 8 个 `complex_chain`、4 个 `cutoff_sensitive`、4 个 `latest_control`。

复杂链 8 题上：

- Scoped Hybrid：Recall@5 `0.6750`，nDCG@5 `0.6841`，Complete@5 `0.2500`；
- TEF-RAG v5：Recall@5 `0.6750`，nDCG@5 `0.7074`，Complete@5 `0.1250`。

预登记的优势条件没有满足。v5 改善了部分排序表现，但没有提高 complex-chain 平均 Recall，Complete@5 反而下降。

该 16-query 数据集在分析后已经成为 **seen diagnostic set**，后续若对方法进行调整，就不能再将其作为 unbiased holdout。

---

## 4. TEF-RAG v5.1 —— 失败归因

v5.1 的目标不是提出新算法，而是判断：

> v5 的失败主要来自 Beam Search 近似，还是来自 representation / objective 本身？

新增内容包括：

- 在相同 candidate pool 上进行 exhaustive exact set search；
- Beam 与 Exact 共用同一 scoring callback；
- 逐 query 的 Beam-vs-Exact 诊断；
- 结构诊断指标；
- 确定性 failure taxonomy；
- Exact optimality 与 complementarity 相关测试。

### 主要结果

12 个 set-mode query 上：

- Beam set = Exact set：`12/12`；
- mean objective gap = `0`；
- max objective gap = `0`。

8 个 complex-chain query 上，Exact 与 Beam 完全相同，仍为：

`Recall / nDCG / Complete = 0.6750 / 0.7074 / 0.1250`

在 10 个 set-objective 失败 query 中：

- 10/10 都存在可行的 gold-complete Top-5；
- 但 Exact v5 objective 在 10/10 情况下都给一个不完整集合更高的分数；
- 不完整最优集相对最佳 gold-complete set 的平均诊断 margin 为 `0.0693`。

结论：

> **在当前小 candidate pool 上，search approximation 不是主要失败来源。**

剩余的不确定性主要来自两类因素：

1. query/profile/role/relation representation 或 projection 错误；
2. set objective 本身与真正的任务支持完整性不对齐。

---

## 5. `temporal_maintenance_dev_v2` 数据扩充阶段

随后归档了一个更大的合成开发数据集，包括：

- 48 台 target device；
- 192 条 authored chain；
- 1,152 个 query / 576 个 intent；
- provenance、authoring metadata、evaluation gold 与可复现脚本。

该数据集的目标是扩展时序运维场景覆盖，但后续 difficulty audit 表明：

> **样本数量看起来很大，但有效难度被明显高估。**

### 难度审计

核心结果：

- `RECENCY_ONLY`：`956/1152 = 82.99%`；
- temporal query：`768`；
- 可被 Latest-5 结构性解决的 temporal query：`572/768 = 74.48%`；
- 因此 `TEMPORAL_HARD_NOT_RECENCY_SOLVABLE` 只有 `196` 个；
- 这 196 个占 temporal query 的 `25.52%`，占全部 query 的 `17.01%`。

审计还发现，旧的 frozen TMC-RAG-v2 并没有在所有困难结构类型上稳定优于 Latest：

- 在 multi-episode disambiguation 与 similar-symptom/different-cause 上表现更清晰；
- 在 procedure versioning、cross-source、late-arrival 等 strata 上并不稳定。

结论：

> **旧 dev benchmark 被 recency-solvable 任务主导，不适合作为未来 v6 主要性能主张的验证 benchmark。**

---

## 6. 当前过渡阶段

### v5.2 Oracle Projection Attribution（2026-09-15）

在不改变 frozen v5 candidate、semantic score、Top-k、budget、Exact Search、`_score_set` 或评价的情况下，完成 Profile / Roles / Relations 的 2×2×2 离线归因。CCC 复现 v5.1；OOO 将 all-set Recall / nDCG / Complete 从 `0.7208 / 0.7291 / 0.1667` 提升至 `0.8625 / 0.8752 / 0.5000`，gross repair 4、regression 0、net gain +4，但仍有 6/10 个存在可行 gold-complete Top-5 的查询保持 incomplete。单因素 Profile / Roles / Relations 的 gross repair 为 `1 / 1 / 0`，regression 为 `0 / 1 / 0`，net gain 为 `+1 / 0 / 0`；关系收益主要在 oracle profile 条件下出现。

稳定结论：**projection / representation error 与 objective misalignment 共存。** Oracle metadata 只用于 offline analyzer，不进入正常 retrieval API；该结果来自已见诊断集，不是独立验证。

同期修复旧 difficulty audit 报告生成占位符和 TMC / TEF 命名，并导出 196-query `TEMPORAL_HARD_NOT_RECENCY_SOLVABLE` seen-dev diagnostic manifest；它不得包装为新 test。

### Temporal-Hard Benchmark Protocol 草案（2026-09-15）

完成双层 benchmark 预登记草案、机器可读 config、validator 与测试。草案围绕 canonical Temporal Evidence Flow，区分 telemetry 分布、运维事件结构与 RAG temporal difficulty，并预登记 split isolation、FlowComplete@5、Latest-5 `Complete@5 <= 0.40` 草案门槛、V1/V2/V3 规程版本和双时间规则。状态保持 `DRAFT_FOR_REVIEW`；未生成数据，等待用户 review/freeze。

第二轮小修订加入 structural recency gate、group-aware `FlowComplete@5`，以及 scenario/template family 与 Challenge Test asset split isolation；主 protocol 同步中文化。状态仍未冻结。

`FlowComplete@5` 语义进一步从逐边局部可满足收紧为存在全局一致的 group-to-evidence assignment。

在 v5.2 与数据难度审计之后，已经确认两个研究瓶颈：

1. **算法问题**：Search 基本被排除为主要原因；projection / representation error 与 objective misalignment 已确认共存。
2. **Benchmark 质量问题**：现有大 dev set 中 Latest 可解样本过多，需要重新设计独立 temporal-hard benchmark protocol。

当前向前推进的计划由 `CLAUDE.md` 维护，核心包括：

- 冻结独立 temporal-hard benchmark protocol；
- 预登记同时处理 flow representation 与 flow-completion selection 的 v6；
- 只在独立数据上做后续优势验证。

---

## 本文件维护规则

只记录：

- 已完成的重要阶段；
- 已稳定成立的结论；
- 对后续长期有价值的方法演进信息。

不要把本文件变成实验流水账。

临时 run、参数 sweep、短期假设、一次性失败日志应放在：

- `experiments/analyses/`；
- branch-specific notes；
- 对应实验报告。

当前任务与最新决策始终以 `CLAUDE.md` 为准。
