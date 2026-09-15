# TEF-RAG Agent 核心上下文

> **这是编码 / 研究 Agent 的唯一核心工作上下文。** 每次开始任务先读本文件。本文件应保持简洁、当前、面向决策；历史迭代细节统一放在 `docs/DEVELOPMENT_HISTORY.md`。
>
> 更新时间：2026-09-15  
> 当前开发分支：`tef-rag-v5.1-failure-attribution`

## 1. 研究背景：后续迭代不得偏离

本项目最重要、最高优先级的背景文件是：

`docs/project_background/一种储能电站多模态异构数据的时空对齐与可信感知方法.docx`

**除非用户明确调整研究方向，否则后续所有方法、数据集与论文迭代都必须围绕该文件所定义的问题展开。** `paper/TMC_RAG_ICRA_style_zh_v2.pdf` 只用于理解初版论文与历史方法，不代表最终研究目标。

项目核心不是通用时序问答，也不是通用事故日志检索，而是：

> **面向储能电站具身运维任务规划，在设备、时间、规程适用性等硬约束下，从多源异构证据中检索并组织能够支撑当前任务的一组完整、可信、可审计证据，并最终支持结构化工单与具有依赖关系的具身动作计划生成。**

系统需要联合处理的证据包括但不限于：

- 非结构化规程、设备说明书、安全协议；
- 结构化历史工单、设备记录、告警与维护历史；
- BMS / SCADA 当前状态记录；
- 在任务需要时，由专业模型产生的预测类证据。

下游目标不只是自然语言回答，而应能够支撑：

- **结构化工单**；
- **可执行或部分有序的具身动作计划**。

原始背景中有四类长期有效的问题约束：

1. **上下文完整性**：规程步骤依赖章节上下文、前置条件和适用范围，不能只靠孤立片段理解。
2. **字段精确性**：设备 ID、时间戳、告警码等结构化字段不能被“语义近似”替代。
3. **时序 / 顺序正确性**：证据何时可见、操作步骤之间的依赖关系都会影响任务正确性，不允许不安全地任意重排。
4. **预测性支持**：涉及健康趋势或未来风险时，应使用专业预测证据，不应让 LLM 自行臆测 SOH / RUL 等行为。

不要把项目简化成固定的：

`Observation -> Diagnosis -> Action -> Verification`

这种链条在部分场景中可能成立，但 TEF-RAG 更一般的目标是建模：

> **query-conditioned task-support evidence flow（查询条件化的任务支持证据流）**。

根据具体 query，一条完整证据流可能包含当前状态、历史先例、预测、适用规程、前置条件、动作支撑、后续更正 / 覆盖、验证或持续不确定性等不同角色。

---

## 2. 必须区分：硬可行性约束 vs. 可学习 / 可优化的证据选择策略

项目的核心原则之一是：

> **把“哪些证据绝对不能用”与“合法证据中应该选哪些”严格分开。**

### 应保留为硬可行性约束

这些规则属于领域有效性边界，不是主要算法创新点：

- 目标设备 / 实体必须正确；
- 若存在事件时间，则必须满足 `event_time <= query_time`；
- 必须满足 `available_at <= query_time`；
- 规程型号、版本及有效期必须在查询时刻适用；
- retrieval 阶段绝不能读取 gold / reference 标签；
- 不得泄漏未来或查询时刻尚不可见的证据；
- authoring / gold 字段只能用于离线诊断和评价。

### 不要把旧工程规则固化成研究贡献

以下都属于可替换的实现策略，而不是不可改变的核心：

- 固定 task -> source 路由；
- 固定 source quota，例如 N 个规程、M 个工单、1 个状态、1 个预测；
- 固定使用 BM25、Dense 或某种简单融合；
- 固定 parent / 整节恢复策略；
- 手写的重要性规则；
- 手工固定的 evidence role 或 relation 启发式，只要能提出更合理、可审计的表示，就可以替换。

研究方向应逐渐转向：

> **在有限 Top-k / 上下文预算下，由算法决定哪一组合法证据最能共同支撑当前运维任务。**

---

# 3. 两条长期主线任务

除非用户明确调整方向，否则后续工作必须始终沿着以下 **数据** 与 **算法** 两条主线同时推进。不能只优化其中一条而长期忽略另一条。

## A. 数据主线：构造真正需要时序证据推理的 benchmark

benchmark 必须真实测试 TEF-RAG 想解决的困难，而不能被 `同设备 + 最新若干条记录` 轻易解决。

### 数据设计不变量

- 难度规则必须在评估目标算法 **之前** 定义，不能因为某方法成功或失败再事后删题、挑题。
- 新 validation / test 必须独立于已经看过的 v5 / v5.1 诊断集。
- 与其生成数千条模板重复的简单改写，更优先少量真正困难、结构独立、经过人工复核的案例。
- 同一 intent 的两个改写不能被当作两个独立真实事件；统计时应按 intent / asset / authored chain 等合理独立单元聚类。
- 在比较新算法前，先冻结 benchmark 构造规则、难度标签规则和验收标准。
- `Latest-5` 必须作为强制难度审计基线。如果大部分 temporal query 能被 Latest-5 解决，该 benchmark 不适合作为主要验证集。
- 旧数据中基于已知结果筛出的 hard subset 只能用于 **开发诊断**，不能重新包装为独立 test。

### 必须长期保留和扩充的难度类型

新数据应包含以下难度及其组合：

- `MULTI_EPISODE_DISAMBIGUATION`
- `CUTOFF_SENSITIVE`
- `LATE_ARRIVING_EVIDENCE`
- `SUPERSEDED_DIAGNOSIS`
- `PROCEDURE_VERSIONING`
- `CROSS_SOURCE_REQUIRED`
- `SIMILAR_SYMPTOM_DIFFERENT_CAUSE`
- `PERSISTENT_UNCERTAINTY`

真正困难的样本应逐步加入：

- 更长的同设备历史；
- 多 episode 交织；
- 工单 reopen / correction / supersession；
- 真实风格的规程修订、撤回和版本替换；
- 多源证据缺失与相互依赖；
- “最新记录属于错误 branch / episode”的情况。

### 未来 annotation 目标

对于严肃的 v6 validation set，优先考虑显式标注：

> **canonical task-support evidence flow（标准任务支持证据流）**

或至少标注可解释的 support edges，而不是只提供必要 evidence ID 集合。

这样未来才能定义真正的 `FlowComplete@k` 一类指标，而不是继续依赖 projection-conditioned proxy。

---

## B. 算法主线：从硬编码检索策略走向 coherent task-support evidence selection

算法目标不是简单“加入更多时间权重”，而是：

> **在设备 / 时间 / 规程等硬有效性约束内，在 Top-k / context budget 下，检索出 query-conditioned、互补、连贯、可审计，且能够共同支撑当前运维任务的证据集合。**

预期研究演进主线是：

`硬规则 TMC-RAG -> 查询条件化集合选择 -> 正确的证据表示 / 图结构 -> 任务支持证据流闭合`

在归因清楚当前失败模式前，不要直接重新设计算法。必须实验性地区分：

- Search error；
- Representation / Projection error；
- Objective error。

---

# 4. 当前工作进度

## 4.1 初版 TMC-RAG / 论文阶段

初版 TMC-RAG 已证明一些领域约束确实有价值，包括：

- 分源检索；
- 双时间可见性；
- 设备 / 型号 / 版本过滤；
- 规程恢复；
- 结构化生成；
- 有界修复。

但其 retrieval policy 中大量逻辑由人工路由、quota 和硬规则指定，因此当前将其定位为：

> **工程基线 / 历史前身，而不是最终算法创新点。**

## 4.2 TEF-RAG v5

v5 将旧的 path-prefix filling 改造成 **query-conditioned set-level objective（查询条件化集合级目标）**：

`Semantic + DirectedChain + RoleCoverage - Redundancy`

权重在冻结的 v5 实现中固定。

它改善了部分排序行为，但没有在复杂链任务上证明相对 Scoped Hybrid 的稳定优势。

冻结的 16-query v5 stress set 上，复杂链 8 题：

- Scoped Hybrid：Recall@5 `0.6750`，nDCG@5 `0.6841`，Complete@5 `0.2500`；
- TEF-RAG v5：Recall@5 `0.6750`，nDCG@5 `0.7074`，Complete@5 `0.1250`。

因此该数据集现在属于 **已见诊断集**，不能调参后继续当作独立验证结果。

## 4.3 TEF-RAG v5.1 失败归因 —— 已完成

v5.1 在完全不改变 frozen v5 `score_set` 的前提下加入 exhaustive exact set search。

核心结果：

- 12/12 个 set-mode query 中，Beam 与 Exact 选出的集合完全一致；
- mean / max objective gap 均为 `0`；
- complex-chain 仍为 `0.6750 / 0.7074 / 0.1250`；
- 10 个 set-objective 失败 query 中，全部存在可行的 gold-complete Top-5，但 Exact 仍然在 10/10 情况下选择 objective 更高的不完整集合；
- 不完整最优集相对最佳 gold-complete set 的平均 objective margin 为 `0.0693`（仅用于离线诊断）。

因此：

> **当前小候选池中，Beam Search 近似不是主要失败来源。**

但 v5.1 还没有把以下因素彻底拆开：

- query profile error；
- role projection error；
- relation / evidence-graph projection error；
- set-objective misalignment。

当前 taxonomy 强烈提示：**representation/projection 与 objective 可能同时有问题。**

因此不能从“search 不是问题”直接跳到“已经证明 objective 单独有问题”。

## 4.4 `temporal_maintenance_dev_v2` 难度审计 —— 已完成

该数据集当前只属于 development material，不是独立 test。

难度审计结论：

- 1,152 queries / 576 intents；
- 192 synthetic chains；
- 48 台 target devices；
- `RECENCY_ONLY`：956/1152 = `82.99%`；
- 768 个 temporal query 中，有 572 个被 Latest-5 结构性覆盖全部必要证据，即 `74.48%`；
- 因此真正的 `TEMPORAL_HARD_NOT_RECENCY_SOLVABLE` 只有 196 个，占 temporal query 的 `25.52%`，占全部 query 的 `17.01%`。

这意味着旧 dev set 被 recency-solvable 任务主导，不能作为未来 TEF-v6 的主要验证依据。

重要命名规范：

> 难度审计里覆盖 1,152 题的冻结结果来自 **TMC-RAG-v2**，不是 TEF-RAG-v5。后续报告中不要再简单标成 `TEF`。

当前 audit 还需要清理一个已知问题：修复报告中未渲染的 `{len(operational_hard)}` / percentage 占位符。

---

# 5. 立即下一步任务

## 算法任务：v5.2 Oracle Projection Attribution

在定义 v6 之前，先在 **已见诊断集** 上做一个小型离线 counterfactual attribution 实验。

以下内容全部保持不变：

- candidate pool；
- semantic score；
- Top-k；
- budget；
- Exact Search；
- frozen v5 objective。

只替换 profile / role / relation 表示，至少比较：

- current profile + current roles + current relations；
- oracle profile + current roles + current relations；
- current profile + oracle roles + current relations；
- current profile + current roles + oracle relations；
- oracle profile + oracle roles + oracle relations。

目标：区分失败究竟主要来自 representation/projection，还是即使表示正确，objective 仍偏好不完整集合。

任何 oracle 信息都不得进入真实 retrieval；Oracle variant **只允许离线诊断**。

v5.2 之后按结果决策：

- 若 oracle relation / representation 大幅修复失败：优先研究 evidence graph / relation induction；
- 若 oracle representation 已正确，但 Exact objective 仍偏好 incomplete set：优先研究 closure-/flow-completion-aware objective；
- 若两边都有贡献：v6 应同时解决 graph induction 与 flow-aware set selection。

禁止在这 16 个已见 query 上重新调 v5 权重。

## 数据任务：重构真正 temporal-hard 的 benchmark

与 v5.2 并行进行：

1. 修复 difficulty audit 中的占位符 bug，并统一 TMC / TEF 命名；
2. 导出 196 个 `TEMPORAL_HARD_NOT_RECENCY_SOLVABLE` query，作为 **dev diagnostic manifest**；
3. 在生成 / 评分前先写新的独立 temporal-hard benchmark protocol；
4. 在评估方法前预先定义 Latest-5 难度验收标准；
5. 优先增加独立 scenario diversity，而不是继续堆模板 / paraphrase 数量；
6. 加入人工复核，并在可行时增加 canonical task-support flow annotation。

不要把旧 dev set 里根据结果筛出来的 hard query 重新包装成“新的 test set”。

---

# 6. v6 允许演化成什么

在以下两件事完成前，不要正式实现 v6：

- v5.2 attribution；
- 新 benchmark protocol 书面冻结。

当前较可能的 v6 方向包括：

- query-conditioned evidence graph / relation induction；
- closure-aware / flow-completion-aware set scoring；
- 显式奖励属于同一 coherent task-support structure 的证据，而不是仅仅 role 齐全或 relation 数量多但结构碎片化。

最终 Top-k 仍然可以输出 **set**。Path / Flow 可以只是 latent scoring structure。

不要重新引入 v4 的旧问题：

> 把 path 当作原子检索单元，最后再按 Top-k 做 prefix truncation。

任何 v6 objective、权重、success criteria 与 validation protocol，都必须在评估新的独立 holdout 之前预登记 / 冻结。

---

# 7. 评价纪律

始终把 retrieval 和 downstream generation 分开报告。

当前 retrieval 指标包括：

- Recall@k；
- nDCG@k；
- Complete@k。

未来如果数据有 flow annotation，应增加显式 flow-completeness 指标。

以下内容不能混为一谈：

- query paraphrase ≠ 独立事件；
- protocol compliance ≠ task correctness；
- citation ID 存在 ≠ semantic support；
- projected-graph flow diagnostic ≠ canonical ground truth；
- 在简单 benchmark 上的 aggregate improvement ≠ temporal reasoning advantage。

始终保留简单但重要的 baseline / control：

- `Latest`；
- 合理情况下的 BM25 / lexical；
- Hybrid；
- 能够正确运行的最强外部基线。

外部 baseline 如果只是 compatibility run 或存在失败，必须明确标注，不能包装成正式公平比较。

---

# 8. Agent 执行规则

- 每次任务先读本文件；只有需要历史背景时才读 `docs/DEVELOPMENT_HISTORY.md`。
- 做重大研究方向调整前，必须重新阅读背景 DOCX。
- 尽量复用现有代码路径和统一 scoring logic，不要另起一套会静默漂移的平行实现。
- retrieval 阶段永远不能使用 gold / authoring 字段。
- 不得静默修改已冻结的数据、objective 权重或评价定义。
- 不得调用外部在线商业 LLM API。若实验确实需要 LLM，优先使用项目已有的本地 OpenAI-compatible 配置与环境变量；绝不能提交凭证。
- 本地目录包含很多历史实验时，只提交本任务必要文件。
- 禁止使用 `git add .`、`git add -A`、force push、`git reset --hard` 或破坏性 clean。
- 更新 `CLAUDE.md` 时应 **直接覆写“当前状态 / 当前任务”**，不要持续追加流水账。
- 已完成且仍有长期价值的阶段性结论，转移到 `docs/DEVELOPMENT_HISTORY.md`。

---

# 9. 推荐阅读顺序

绝大多数任务只需要按以下顺序读取：

1. `CLAUDE.md` —— 当前研究契约、核心原则与任务状态；
2. `docs/project_background/一种储能电站多模态异构数据的时空对齐与可信感知方法.docx` —— 最高优先级项目背景；
3. 当前实现，尤其是 `tef_rag_v5/` 与当前分析脚本；
4. `experiments/analyses/` 下与当前任务直接相关的诊断报告；
5. 只有需要历史演进时才读 `docs/DEVELOPMENT_HISTORY.md`；
6. `paper/TMC_RAG_ICRA_style_zh_v2.pdf` 仅用于理解初版论文，不代表当前最终方法。

如果未来某个方法设计与背景问题定义或“数据 / 算法”两条长期主线发生冲突，应暂停实现，并先明确说明为什么需要调整研究方向。