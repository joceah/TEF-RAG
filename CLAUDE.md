# TEF-RAG Agent 核心上下文

> **这是编码 / 研究 Agent 的唯一核心工作上下文。** 每次开始任务先读本文件。本文件应保持简洁、当前、面向决策；历史迭代细节统一放在 `docs/DEVELOPMENT_HISTORY.md`。
>
> 更新时间：2026-09-15  
> 当前开发分支：`tef-rag-v6-benchmark-protocol`

## 1. 研究背景：后续迭代不得偏离

本项目最重要、最高优先级的背景文件是：

`docs/project_background/一种储能电站多模态异构数据的时空对齐与可信感知方法.docx`

**除非用户明确调整研究方向，否则后续所有方法、数据集与论文迭代都必须围绕该文件所定义的问题展开。** `paper/TMC_RAG_ICRA_style_zh_v2.pdf` 只用于理解初版论文与历史方法，不代表最终研究目标。

项目核心不是通用时序问答，也不是通用事故日志检索，而是：

> **面向储能电站具身运维任务规划，在设备、时间、规程适用性等硬约束下，从多源异构证据中检索并组织能够支撑当前任务的一组完整、可信、可审计证据，并最终支持结构化工单与具有依赖关系的具身动作计划生成。**

系统需要联合处理的证据包括但不限于：

- 非结构化规程、设备说明书、安全协议；
- 结构化历史工单、设备记录、告警与维护历史；
- BMS / SCADA 当前状态与时序监测记录；
- 在任务需要时，由专业模型产生的趋势、健康状态或预测类证据。

下游目标不只是自然语言回答，而应能够支撑：

- **结构化工单**；
- **可执行或部分有序的具身动作计划**。

原始背景中有四类长期有效的问题约束：

1. **上下文完整性**：规程步骤依赖章节上下文、前置条件和适用范围，不能只靠孤立片段理解。
2. **字段精确性**：设备 ID、时间戳、告警码等结构化字段不能被“语义近似”替代。
3. **时序 / 顺序正确性**：证据何时可见、不同记录如何演化、操作步骤之间的依赖关系都会影响任务正确性。
4. **预测性支持**：涉及健康趋势或未来风险时，应使用专业预测证据，不应让 LLM 自行臆测 SOH / RUL 等行为。

不要把项目简化成固定的：

`Observation -> Diagnosis -> Action -> Verification`

这种链条在部分场景中可能成立，但 TEF-RAG 更一般的目标是建模：

> **Temporal Evidence Flow（时间证据流）：在当前 query 与 query time 条件下，多源证据如何随时间产生、更新、修正、失效、相互支撑，并共同形成当前运维任务所需的证据结构。**

根据具体 query，一条完整证据流可能包含当前状态、历史先例、预测、适用规程、前置条件、动作支撑、后续更正 / 覆盖、验证或持续不确定性等不同角色。

---

# 2. 统一方法论：Temporal Evidence Flow 是核心范式

后续算法与论文叙事应围绕一个统一核心展开：

> **“时序性”不是一个孤立的额外特征，也不是只在某一个 scoring term 中出现；它应在确有必要的环节中贯穿 RAG 流程，用同一套 Temporal Evidence Flow 逻辑约束 query 理解、证据可见性、候选构建、证据关系、重排序 / 集合选择以及最终生成。**

这不意味着必须人为堆砌多个模块。统一框架的要求是：**所有新增机制都回答同一个问题——如何在查询时刻恢复并选择正确的任务支持证据流。**

可以考虑的技术落点包括：

- **Temporal Query Understanding**：识别目标设备、cutoff、时间跨度、版本条件、episode、是否涉及“最初—后续—最终”等演化关系；
- **Bitemporal Candidate Construction**：利用 `event_time` 与 `available_at` 构造查询时刻真实可见的 evidence snapshot；
- **Temporal-Semantic Matching**：相似度不能只看文本语义，还要考虑 query 所需的时间阶段、版本、episode 与更新关系；
- **Evidence Flow Induction**：建模 evidence 之间的 update / supersession / support / prerequisite / follow-up 等可审计关系；
- **Flow-aware Selection / Reranking**：在有限 Top-k / context budget 下优先选择属于同一任务支持结构、互补且完整的 evidence set；
- **Evidence-grounded Generation**：最终生成只基于当前时刻合法、已选中的 evidence flow，并保留必要的不确定性。

**禁止为了“凑创新点”把方法写成互不相关的 A+B+C 模块。** 一个核心创新可以在多个环节有一致的技术体现；这些体现共同构成统一框架，而不是人为包装成互不相关的独立贡献。

## 2.1 多步检索：可选、条件触发，不是强制模块

长时间跨度、多 episode、诊断被后续证据修正、规程版本演进等 query 可能适合采用 Step-by-Step / multi-step retrieval：

`query -> temporal decomposition -> step retrieval -> intermediate state -> next step -> final evidence set`

但**不要默认所有 query 都做多步检索**。

- 简单 current/latest query 可以保持 single-step；
- 只有数据与诊断结果表明确实需要跨阶段恢复证据流时，才引入 adaptive temporal decomposition；
- 先由 benchmark 证明“单步检索不足”，再实现多步机制；
- 多步检索如果加入，也必须服务于同一个 Temporal Evidence Flow 目标，而不是成为额外堆叠模块。

可借鉴 Tree / hierarchical RAG “不要把证据视为完全独立 flat chunks”的思想，但本项目不需要为了类似 TreeRAG 而强行构造复杂树结构。TEF-RAG 的天然结构应以 **时间条件下的任务支持证据流** 为主。

---

# 3. 必须区分：硬可行性约束 vs. 可学习 / 可优化的证据选择策略

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

> **在有限 Top-k / 上下文预算下，由算法决定哪一组合法证据最能共同支撑当前运维任务，并尽量恢复正确的 Temporal Evidence Flow。**

---

# 4. 两条长期主线任务

除非用户明确调整方向，否则后续工作必须始终沿着以下 **数据** 与 **算法** 两条主线同时推进。不能只优化其中一条而长期忽略另一条。

## A. 数据主线：真实结构 + 真正 temporal-hard 的 benchmark

benchmark 必须真实测试 TEF-RAG 想解决的困难，而不能被 `同设备 + 最新若干条记录` 轻易解决。

### 4.1 必须区分三个不同层次

以后任何数据生成与报告都必须明确区分：

1. **底层数值时序分布**：电压、电流、温度、SOC 等 telemetry 的正常分布、波动范围、采样频率与极端异常比例；
2. **运维事件结构**：真实故障、诊断、工单、规程、修正、复核、恢复等业务过程如何发生；
3. **RAG 时序任务难度**：query 是否要求跨 cutoff、跨 episode、跨版本、跨 source 或恢复完整 evidence flow。

这三者不能混为一谈。

### 4.2 “异常数据”的专门定义

本项目中提到“异常数据”时，默认优先指 **数值型 telemetry 中明显不合理、极端偏离正常范围的异常点或异常片段**，例如电压 / 电流出现夸张跳变、传感器漂移、采集或通信系统性错误。

- 这类极端数值异常在真实场景中应当很少；
- 不要为了让 temporal RAG 任务更难而人为大量增加这种异常点；
- “设备真的发生故障”不等于“telemetry 是脏数据”；
- `LATE_ARRIVING_EVIDENCE`、`MULTI_EPISODE`、`PROCEDURE_VERSIONING` 等属于 RAG 结构难度，不属于这里说的“异常数据”。

数据生成应尽量使数值分布与正常 / 异常比例接近真实场景；如果无法高度拟真，**至少保证结构与逻辑符合真实运维过程**。

### 4.3 时序采样频率与 RAG evidence unit

BMS / SCADA 原始数据可能是秒级或分钟级，频率越高数据量越大。RAG 不应默认直接检索海量 raw points。

优先考虑：

`Raw time series -> 专业统计 / 异常检测 / 时序预测 -> 状态快照、趋势卡、事件记录 -> RAG evidence`

也就是说：

- 底层 raw telemetry 用于保持数据真实性和支持专业模型；
- RAG 主要检索面向运维语义的状态 / 趋势 / 事件 evidence；
- 具体采样频率根据场景设定，不要为了“时序性”盲目把所有高频点塞进上下文。

### 4.4 数据设计不变量

- 难度规则必须在评估目标算法 **之前** 定义，不能因为某方法成功或失败再事后删题、挑题；
- 新 validation / test 必须独立于已经看过的 v5 / v5.1 诊断集；
- 与其生成数千条模板重复的简单改写，更优先少量真正困难、结构独立、经过人工复核的案例；
- 同一 intent 的两个改写不能被当作两个独立真实事件；统计时应按 intent / asset / authored chain 等合理独立单元聚类；
- 在比较新算法前，先冻结 benchmark 构造规则、难度标签规则和验收标准；
- `Latest-5` 必须作为强制难度审计基线。如果大部分 temporal query 能被 Latest-5 解决，该 benchmark 不适合作为主要验证集；
- 旧数据中基于已知结果筛出的 hard subset 只能用于 **开发诊断**，不能重新包装为独立 test。

### 4.5 必须长期保留和扩充的难度类型

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
- 真实风格的规程 V1 / V2 / V3 修订、撤回、版本替换及明确生效时间；
- 多源证据缺失与相互依赖；
- “最新记录属于错误 branch / episode”的情况；
- 同一症状对应不同原因，必须依靠时间与上下文区分的情况。

### 4.6 评价集建议：真实性与难度分开

优先考虑两层评价，而不是要求一个数据集同时解决所有问题：

- **Realistic Distribution Set**：保留更接近真实业务的正常 / 异常数值比例、事件频率与样本分布，用于验证系统在部署型分布下是否稳定；
- **Temporal-Hard Challenge Set**：提高 multi-episode、late arrival、supersession、versioning、cross-source 等结构难题的比例，用于检验 Temporal Evidence Flow 机制本身是否有效。

两者用途不同，不能用真实分布集中的大量简单样本稀释 hard mechanism 的评价，也不能把 challenge set 的困难比例包装成真实业务发生率。

### 4.7 未来 annotation 目标

对于严肃的 v6 validation set，优先考虑显式标注：

> **canonical task-support evidence flow（标准任务支持证据流）**

或至少标注可解释的 support / update / supersession / prerequisite 等 edges，而不是只提供必要 evidence ID 集合。

这样未来才能定义真正的 `FlowComplete@k` 一类指标，而不是继续依赖 projection-conditioned proxy。

---

## B. 算法主线：建立统一的 Temporal Evidence Flow 框架

算法目标不是简单“加入更多时间权重”，也不是继续堆叠独立模块，而是：

> **在设备 / 时间 / 规程等硬有效性约束内，以 Temporal Evidence Flow 为统一范式，在 query understanding、evidence representation、retrieval / reranking 和 set selection 等必要环节持续利用时序结构，在 Top-k / context budget 下选出互补、连贯、可审计且能够共同支撑当前运维任务的证据集合。**

预期研究演进主线是：

`硬规则 TMC-RAG -> 查询条件化集合选择 -> Temporal Evidence Flow 表示 -> 统一的 flow-aware retrieval / reranking / selection`

当前仍然必须先归因清楚失败模式，实验性地区分：

- Search error；
- Query / Representation / Projection error；
- Objective error。

在这些问题尚未分清前，不要因为某个结果不好就临时堆叠新的 reranker、multi-step 模块或额外权重。

---

# 5. 当前工作进度

## 5.1 初版 TMC-RAG / 论文阶段

初版 TMC-RAG 已证明一些领域约束确实有价值，包括：

- 分源检索；
- 双时间可见性；
- 设备 / 型号 / 版本过滤；
- 规程恢复；
- 结构化生成；
- 有界修复。

但其 retrieval policy 中大量逻辑由人工路由、quota 和硬规则指定，因此当前将其定位为：

> **工程基线 / 历史前身，而不是最终算法创新点。**

## 5.2 TEF-RAG v5

v5 将旧的 path-prefix filling 改造成 **query-conditioned set-level objective（查询条件化集合级目标）**：

`Semantic + DirectedChain + RoleCoverage - Redundancy`

权重在冻结的 v5 实现中固定。

它改善了部分排序行为，但没有在复杂链任务上证明相对 Scoped Hybrid 的稳定优势。

冻结的 16-query v5 stress set 上，复杂链 8 题：

- Scoped Hybrid：Recall@5 `0.6750`，nDCG@5 `0.6841`，Complete@5 `0.2500`；
- TEF-RAG v5：Recall@5 `0.6750`，nDCG@5 `0.7074`，Complete@5 `0.1250`。

因此该数据集现在属于 **已见诊断集**，不能调参后继续当作独立验证结果。

## 5.3 TEF-RAG v5.1 失败归因 —— 已完成

v5.1 在完全不改变 frozen v5 `score_set` 的前提下加入 exhaustive exact set search。

核心结果：

- 12/12 个 set-mode query 中，Beam 与 Exact 选出的集合完全一致；
- mean / max objective gap 均为 `0`；
- complex-chain 仍为 `0.6750 / 0.7074 / 0.1250`；
- 10 个 set-objective 失败 query 中，全部存在可行的 gold-complete Top-5，但 Exact 仍然在 10/10 情况下选择 objective 更高的不完整集合；
- 不完整最优集相对最佳 gold-complete set 的平均 objective margin 为 `0.0693`（仅用于离线诊断）。

因此：

> **当前小候选池中，Beam Search 近似不是主要失败来源。**

## 5.4 TEF-RAG v5.2 Oracle Projection Attribution —— 已完成

v5.2 在 12 个已见 set-mode query 上完成 Profile / Roles / Relations 的完整 2×2×2 离线 counterfactual。所有条件保持 candidate、visibility、semantic score、Top-k、budget、Exact Search、`_score_set` 与评价不变；oracle metadata 只存在于 analyzer。

- CCC 完整复现 v5.1：Recall / nDCG / Complete = `0.7208 / 0.7291 / 0.1667`；
- 单独 oracle Profile / Roles / Relations 的 gross repair 分别为 `1 / 1 / 0`，regressed success 为 `0 / 1 / 0`，net Complete gain 为 `+1 / 0 / 0`；
- Oracle Profile + Oracle Roles 修复 `3` 个；
- OOO 为 `0.8625 / 0.8752 / 0.5000`，修复 `4/10` 个原失败；
- OOO 仍有 `6/10` 个原失败保持 incomplete，而这些题均存在可行 gold-complete Top-5。

结论：

> **Projection/representation 改善确实有效，但 frozen objective 在 oracle 表示下仍大量偏好不完整集合；两类问题共存。**

Relations 单独没有修复，只有和 oracle Profile 联合时才产生额外收益，说明 relation utility 明显受 query demand/profile 条件制约。下一代方法应同时研究 query-conditioned evidence-flow representation 与 flow-completion-aware selection，不能只改图或只扩搜索。

## 5.5 `temporal_maintenance_dev_v2` 难度审计 —— 已完成

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

报告生成占位符与 TMC / TEF 命名已修复；196-query 清单已经导出，但明确是 **seen development diagnostic subset，NOT independent validation/test**。

---

# 6. 立即下一步任务

## 6.1 当前状态：benchmark protocol 等待用户 review/freeze

v5.2 accounting 已正式收尾。Benchmark Protocol Draft 已完成第二轮 definition refinement：Latest-5 difficulty 同时包含 structural `RECENCY_SOLVABLE_AT_5` gate 与 performance gate；`FlowComplete@5` 已收紧为 group-aware、globally consistent group-to-evidence assignment constraint；`scenario_family_id` / `template_family_id` isolation 与 Challenge Test exact asset-disjoint 已机器化；主 Markdown 已中文化。Protocol 仍为 `DRAFT_FOR_REVIEW`，尚未冻结，也没有据此生成数据。下一步等待用户最终 review；只有用户明确批准后，才能在后续 commit 将其改为 `FROZEN BEFORE DATA GENERATION`。

根据 v5.2，未来 v6 必须同时覆盖：

1. query-conditioned role / relation / flow representation；
2. 对完整 task-support flow 更一致的 selection / reranking objective。

禁止在这 16 个已见 query 上重新调 v5 权重，也不要把 oracle graph 包装成真实 retrieval 能获得的图。

## 6.2 数据任务：重构真正 temporal-hard 的 benchmark

旧 audit 收尾已完成；protocol freeze 后的数据任务是：

1. 用户明确批准后，先将 protocol 独立 commit 为 `FROZEN BEFORE DATA GENERATION`；
2. 在评估方法前预先定义 Latest-5 难度验收标准；
3. 优先增加独立 scenario diversity，而不是继续堆模板 / paraphrase 数量；
4. 对电压、电流、温度等数值生成规则加入合理范围、采样频率和极少量极端异常点约束；
5. 继续保留并加强规程 V1 / V2 / V3、时效时间戳及修订 / 撤回链；
6. 加入人工复核，并在可行时增加 canonical task-support flow annotation。

不要把旧 dev set 里根据结果筛出来的 hard query 重新包装成“新的 test set”。

---

# 7. v6 允许演化成什么

在新 benchmark protocol 经用户 review 并书面冻结前，不要生成数据，也不要正式实现 v6。

v6 的总原则不是“给 v5 objective 再加一个 term”，而是：

> **以 Temporal Evidence Flow 为统一框架，根据 v5.2 与新数据诊断结果，只在真正需要的环节实现时序机制。**

可能的技术落点包括：

- temporal query understanding / adaptive decomposition；
- query-conditioned evidence graph / relation induction；
- temporal-semantic similarity；
- temporal-aware reranking；
- closure / flow-completion-aware set scoring；
- 对属于同一 coherent task-support structure 的证据给予更合理的联合奖励。

**这些不是必须全部实现。** 最终选择哪些环节，必须由数据与归因实验决定。

最终 Top-k 仍然可以输出 **set**。Path / Flow 可以只是 latent scoring structure。

不要重新引入 v4 的旧问题：

> 把 path 当作原子检索单元，最后再按 Top-k 做 prefix truncation。

任何 v6 objective、权重、success criteria 与 validation protocol，都必须在评估新的独立 holdout 之前预登记 / 冻结。

---

# 8. 评价纪律

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
- 在简单 benchmark 上的 aggregate improvement ≠ temporal reasoning advantage；
- telemetry 极端异常比例 ≠ temporal-hard query 比例。

始终保留简单但重要的 baseline / control：

- `Latest`；
- 合理情况下的 BM25 / lexical；
- Hybrid；
- 能够正确运行的最强外部基线。

外部 baseline 如果只是 compatibility run 或存在失败，必须明确标注，不能包装成正式公平比较。

最终生成模型可以使用较强模型以减少“retrieval 正确但 generator 太弱”的噪声，但 generator 不是本项目核心创新。不同 retrieval 方法必须尽可能共享相同 generator 与生成协议。

---

# 9. Agent 执行规则

- 每次任务先读本文件；只有需要历史背景时才读 `docs/DEVELOPMENT_HISTORY.md`；
- 做重大研究方向调整前，必须重新阅读背景 DOCX；
- 新增模块前先回答：**它是否服务于统一的 Temporal Evidence Flow？数据是否证明它有必要？** 如果答案是否定的，不要实现；
- 尽量复用现有代码路径和统一 scoring logic，不要另起一套会静默漂移的平行实现；
- retrieval 阶段永远不能使用 gold / authoring 字段；
- 不得静默修改已冻结的数据、objective 权重或评价定义；
- 不得调用外部在线商业 LLM API。若实验确实需要 LLM，优先使用项目已有的本地 OpenAI-compatible 配置与环境变量；绝不能提交凭证；
- 本地目录包含很多历史实验时，只提交本任务必要文件；
- 禁止使用 `git add .`、`git add -A`、force push、`git reset --hard` 或破坏性 clean；
- 更新 `CLAUDE.md` 时应 **直接覆写“当前状态 / 当前任务”**，不要持续追加流水账；
- 已完成且仍有长期价值的阶段性结论，转移到 `docs/DEVELOPMENT_HISTORY.md`。

---

# 10. 推荐阅读顺序

绝大多数任务只需要按以下顺序读取：

1. `CLAUDE.md` —— 当前研究契约、核心原则与任务状态；
2. `docs/project_background/一种储能电站多模态异构数据的时空对齐与可信感知方法.docx` —— 最高优先级项目背景；
3. 当前实现，尤其是 `tef_rag_v5/` 与当前分析脚本；
4. `experiments/analyses/` 下与当前任务直接相关的诊断报告；
5. 只有需要历史演进时才读 `docs/DEVELOPMENT_HISTORY.md`；
6. `paper/TMC_RAG_ICRA_style_zh_v2.pdf` 仅用于理解初版论文，不代表当前最终方法。

如果未来某个方法设计与背景问题定义、Temporal Evidence Flow 统一范式或“数据 / 算法”两条长期主线发生冲突，应暂停实现，并先明确说明为什么需要调整研究方向。
