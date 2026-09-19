# TEF-RAG v6 Generation Evaluation Protocol v1

状态：**协议冻结（设计阶段）**。本文件只定义最终生成端的最小输出 schema、gold 标注协议、规范化和评价指标；本轮不生成 annotation、不写 generation runner、不调用 LLM、不运行实验、不访问 sealed test。

## 1. 评价边界与可见输入

生成器只接收当前 v6 的 deployment-visible 输入：

- query：`query_id`、`asset_id`、`asset_model`、`asset_context`、`query_text`、`query_time`、intent/layer 等公开字段；
- evidence：在 `event_time <= query_time` 且 `available_at <= query_time`、public scope 有效的记录；
- chain：公开的资产/链/场景元数据。

生成器不得读取 `required_groups`、`required_flow_edges`、任何方法 prediction 或 test gold。运行时不得使用 query cutoff 之后的 evidence。procedure evidence 只有在 `event_time <= query_time`、`available_at <= query_time`，且 `valid_from <= query_time < valid_to`（空边界表示无界）、`query_time < withdrawn_at`（空值表示未撤回）、非空 `model_scope` 与 query 的 `asset_model` 相容时，才可作为 applicable procedure 依据。

`required_groups`/`required_flow_edges` 可以在离线 annotation QA 中作为 coverage/flow 的辅助审计，但不能直接转换成 action、action dependency 或答案字段。

## 2. 最小输出 schema

输出必须是一个 JSON object，顶层只允许 `work_order` 和 `action_plan` 两个键。未知键、重复 ID、不可解析类型都使 Schema Validity 失败。以下字段是协议 v1 的最小字段；没有证据支持时使用规定的 `null`、空数组或 `not_available`，禁止臆造额外业务字段。

```json
{
  "work_order": {
    "asset_id": "string",
    "diagnosis": {
      "status": "confirmed|provisional|persistent_uncertainty|not_available",
      "concept": "canonical concept string|null",
      "supporting_evidence_ids": ["evidence_id", "..."]
    },
    "recommended_actions": ["action_id", "..."],
    "applicable_procedure": {
      "status": "applicable|superseded|uncertain|not_applicable",
      "procedure_version": "string|null",
      "supporting_evidence_ids": ["evidence_id", "..."]
    },
    "verification_or_uncertainty": {
      "status": "verified|pending|persistent_uncertainty|not_available",
      "statement": "canonical statement|null",
      "supporting_evidence_ids": ["evidence_id", "..."]
    },
    "supporting_evidence_ids": ["evidence_id", "..."]
  },
  "action_plan": [
    {
      "action_id": "A1",
      "action_type": "inspect|diagnose|isolate|adjust|repair|replace|verify|monitor|document|other",
      "target": "canonical target|null",
      "parameters": {
        "canonical_parameter": {"value": "number|string|range", "unit": "string|null"}
      },
      "depends_on": ["A0", "..."],
      "supporting_evidence_ids": ["evidence_id", "..."]
    }
  ]
}
```

### Schema semantics

1. `asset_id` 必须与 query 的资产一致；它不是从自由文本猜测的替代资产名。
2. `diagnosis.concept` 只记录 evidence 明确陈述的故障/原因/诊断概念；`diagnosis.supporting_evidence_ids` 只引用直接支持该 diagnosis 的记录。`status=provisional` 表示仍是阶段性假设；存在 unresolved 或持久不确定性时使用 `persistent_uncertainty`，不能强行选一个原因。
3. `recommended_actions` 是 `action_plan` 中 action IDs 的集合引用，不承担顺序语义；允许是 `action_plan` 的子集（`R ⊆ A`），但不得引用 plan 外 action。没有证据支持的动作不进入 gold；模型额外输出的 action 是 false positive。
4. `applicable_procedure` 只表示当前 cutoff 下存在的、适用且版本信息可由 evidence 支持的 procedure；其 `supporting_evidence_ids` 必须直接支持版本/适用性。没有 procedure evidence 时使用 `not_applicable`、`null` 和空引用。
5. `verification_or_uncertainty` 记录 evidence 明确的 verification 结论，或当前仍不能确认的状态；`statement` 不得添加 evidence 未给出的数值/条件，`supporting_evidence_ids` 必须直接支持该 statement/status。
6. `action_plan` 是动作节点集合。数组排列仅用于序列化，语义顺序完全由 `depends_on` 的有向无环图表示；允许多个无依赖动作并行。
7. `action_type` 只使用上面的有限动作类别；类别不足时使用 `other`，并把证据中的规范化短语放在 `target` 或 action 的 canonicalization sidecar 中，不扩展 schema。
8. `parameters` 只保存 evidence 或有效 procedure 明确给出的参数和值。没有明确参数时使用 `{}`；不能从常识补全单位、阈值或数值。
9. 每个 citation ID 必须存在于该 query 的可见 evidence；同一列表内唯一、顺序不影响语义。对象级 `supporting_evidence_ids` 表达字段/动作支持关系，不表达 dependency；顶层列表是所有对象级引用的去重并集。

协议 v1 特意不加入当前 v6 evidence 无法稳定提供的工单号、状态、优先级、责任人、故障代码、动作安全许可或回滚字段。`target=null` 表示 evidence 未明确目标；它可通过 schema 校验，但不能在 Task Success 中被当作可执行的完整动作。

## 3. Gold annotation protocol

### 3.1 输入与标注原则

每个 query 独立标注。标注员读取原始 v6 query、公开 chain 元数据和按双时间 cutoff 筛选的 evidence 原文/结构化元数据；不得读取任何 method prediction、模型分数、排名、失败样例或 sealed artifact。Gold 必须是 evidence-grounded：每个非空 diagnosis、procedure、verification、action、parameter 和 dependency 都至少关联一个直接支持它的 evidence ID；dependency 的引用保存在 annotation sidecar，v1 prediction schema 不单独输出 edge citation。

`required_groups` 和 `required_flow_edges` 只用于事后 coverage/flow QA：它们可以提示是否遗漏了必要证据，但不能被机械地当作 action 或 action dependency。尤其，evidence-flow 的 `supports/refutes/verifies/supersedes` 不等于 action-to-action `depends_on`。

### 3.2 Work-order 标注

- `asset_id` 从 query 的 `asset_id` 复制；若 evidence 明确显示跨资产而 query 未要求，不新增跨资产工单。
- 从 evidence 明确的 diagnosis/hypothesis/localization 文本标注 `diagnosis.concept`、certainty status 和 `diagnosis.supporting_evidence_ids`。多个互斥假设都未被解决时保留 `persistent_uncertainty`，不要选最可能者。
- 先将 query 所要求且 evidence 明确支持的全部执行步骤形成 `action_plan`；仅把当前任务要求的实际处置/维护动作加入 `recommended_actions`。辅助检查、诊断、验证、监控和记录动作只有在它们本身属于 query 要求时才加入该子集；历史上出现但对当前问题不构成要求的并行记录不自动加入。
- procedure 仅在版本和适用时间/型号条件明确满足时标注，并填写 `applicable_procedure.supporting_evidence_ids`；旧版本被新版本替代时用 `superseded`，不把旧版本当当前适用 procedure。
- `verification_or_uncertainty` 按 cutoff 可见的 verification 或 uncertainty 记录标注，并填写对象级引用。未完成验证使用 `pending`，证据明确长期不确定使用 `persistent_uncertainty`。
- 顶层 `supporting_evidence_ids` 是上述字段和动作引用的去重并集；其顺序不计分。

### 3.3 Action-plan 标注

- 一个 action 必须是最小、可单独执行或验证的动作。并列动词在语义上独立时拆成多个 action；同一目标、同一参数、同一目的的一组不可分操作可保留为一个 action。
- 每个 action 标注 `action_type`、evidence-grounded `target` 和显式 `parameters`。目标或参数未在 evidence 中明确出现时分别置 `null`/`{}`，不能从资产型号或常识推断。
- `depends_on` 只记录 evidence 或业务语义明确支持的必要前置关系，例如“先隔离后检修”“先调整后验证”。单纯的 event-time 先后、同一工单号或同一 evidence-flow edge 不足以产生 dependency。
- 无直接依赖的动作允许并行；不能为了得到唯一线性序列而人为串联。Gold graph 必须无环。
- 为便于复现，gold action IDs 按拓扑层级排序；同层按规范化 `(action_type, target, parameters, supporting_evidence_ids)` 字典序分配 `A1...`。ID 本身不参与模型匹配。

### 3.4 标注质量与冻结

development/validation 每条 query 至少两名独立标注员按本协议标注；冲突由第三方 adjudication，保留冲突原因和最终选择。冻结前运行 schema、可见性、evidence provenance、DAG、procedure validity 和 required-group/flow QA。只有完成 adjudication 的 canonical object 才进入 generation gold。若证据不足，gold 应明确 `not_available`/`persistent_uncertainty`，而不是补写外部知识。

## 4. Canonicalization 与 matching

所有 metric 在比较前执行同一 `generation-canonical-v1` 规范化；规范化表和 alias registry 必须在 annotation 开始前冻结，不能按模型输出临时扩展。

### 4.1 通用文本与概念

- Unicode NFKC、大小写折叠、全角/半角统一、空白与中文/英文标点规范化。
- diagnosis 和 action 的同义表达只有在冻结 alias registry 明确映射到同一 canonical concept/action type 时才视为相同；例如“端子接触不良”与其注册别名可相等，未注册的近义词不做 embedding/LLM 模糊匹配。
- 否定、阶段性词和不确定性词不被删除；它们分别影响 `status`。`confirmed`、`provisional`、`persistent_uncertainty`、`not_available` 不互相等价。
- 未能映射到 registry 的短语使用规范化原文作为 `other` 概念；不根据词面相似度自动合并。

### 4.2 Target 与 parameter

- target 仅在同一 evidence entity/asset/component 的冻结 alias 下匹配；`null` 只匹配 `null`，部分字符串重叠不算匹配。
- parameter 名称使用冻结 registry；数值转为统一 SI 单位，十进制表示去除无意义尾零，转换后相等（绝对误差不超过 `1e-6` 的规范化数值）才匹配。区间保留 lower/upper 边界；一个标量落在区间内不自动等于整个区间。
- 缺少 gold 必需参数、增加 evidence 不支持的额外参数或单位不一致，均使该 action 的参数 tuple 不匹配。`{}` 只与 `{}` 匹配。

### 4.3 Action one-to-one matching

先按规范化 `(action_type, target, parameters)` 建立候选边，再做最大基数的一对一匹配；同基数时按 action canonical tuple 字典序打破平局。一个预测 action 只能匹配一个 gold action，重复动作不能重复计分。`action_id` 和数组位置不参与匹配。

### 4.4 Partial-order matching

`depends_on=[B]` 表示有向边 `B -> A`。对 gold 和 prediction 都计算 DAG 的传递闭包；因此显式写出一个传递边或仅写其直接前置边，在闭包上具有相同语义。比较的是匹配 action IDs 上的闭包边集合，不比较 action 数组顺序。环、未知 action ID 或指向未匹配 action 的边使该 prediction 的 order validity 失败。

## 5. Frozen metrics

所有指标先逐 query 计算，再按 validation/development query macro-average；除明确说明外，不以检索 Top-k 分数替代 generation 分数。

### Schema Validity

通过率。输出必须满足严格 JSON schema、只含允许键、类型/枚举正确、action IDs 唯一、引用 evidence 对该 query 可见且唯一、依赖图无环，且 `recommended_actions` 中每个 ID 都存在于 `action_plan`（`R ⊆ A`，允许严格子集）。任何一项失败即该 query 为 0。

### Field Macro-F1

对非 citation 的固定字段集合分别计算 slot-level exact correctness，再对字段取 macro 平均：`asset_id`、`diagnosis.status`、`diagnosis.concept`、`applicable_procedure.status`、`applicable_procedure.procedure_version`、`verification_or_uncertainty.status`、`verification_or_uncertainty.statement`。这些 scalar slot 只有 canonical exact match 才记为正确（TP=1，否则按缺失/错误计 FN/FP）；不使用 token overlap 或模糊文本 F1。真正的多值字段才使用集合 precision/recall/F1；action 集合单独由 Action F1 评价。标注为 gold N/A 的 procedure/verification slot 不进入该 slot 的分母，模型在 N/A slot 输出值计为 false positive。

### Work-Order EM (Work-Order Joint EM)

严格的语义 exact match。先按 4.3 的 one-to-one semantic action matching 将 prediction action IDs 映射到 gold action IDs，再在映射空间比较 `recommended_actions` 集合；不比较原始 action ID。随后，canonicalized 后的 `asset_id`、diagnosis 对象、procedure 对象和 verification/uncertainty 对象必须全部相等。为避免与 citation metric 重复，顶层和嵌套 `supporting_evidence_ids` 不纳入 Joint EM，但 Schema Validity 仍检查其合法性。

### Action F1

在 one-to-one action matching 后，以匹配 action 数计算 micro precision/recall/F1。匹配要求 action type、target 和完整 parameter tuple 全部 canonical 相等；多余或缺失 action 分别是 false positive/false negative。gold/pred 都无 action 时 F1=1。

### Dependency F1

将匹配后的 gold/pred dependency DAG 转为传递闭包，对闭包有向边集合计算 micro precision/recall/F1。gold/pred 都无边时为 1；gold 无边而 prediction 有边时为 0。未匹配 action 上的预测边不计为正确边，并使 Schema/Order 约束同时受罚。

### Order Validity

通过率而非线性排序分数。一个 prediction 只有在依赖图无环、所有边引用匹配 action，且不存在与 gold 闭包相反的边（`A -> B` 与 gold 的 `B -> A` 冲突）时为 valid。遗漏 gold edge 不使 Order Validity 失败，但由 Dependency F1 惩罚；这允许合法并行和不完整但不矛盾的 partial order。

### Plan EM

严格语义 exact match。完成 action matching 并把 prediction IDs 映射到 matched gold IDs 后，必须：全部 gold action 恰好匹配且无额外 action；映射后的 `recommended_actions` 集合一致；canonical action tuples 一致；依赖传递闭包完全一致。原始 action IDs、数组排列和 supporting evidence IDs 不参与 Plan EM（后者由 citation metric 评价）。空计划仅在双方均为空时 exact。

### Evidence Support / Citation Accuracy

future gold 为每个非空语义 claim/field/action 标注允许的 supporting evidence ID 集合（必要时精确 span）。dependency 的支持证据可以在 gold sidecar 中记录用于审计；由于 v1 输出 schema 没有 edge-level citation 字段，正式 v1 分数不把 dependency citation 单独计为 prediction link，而只评价其端点 action 的 citations。

- Evidence Support Recall：gold 必需 claim/action 中，prediction 至少给出一个允许且可见 supporting evidence ID 的比例。
- Citation Accuracy：以 `(canonical claim key, evidence_id)` 链接做 micro precision/recall/F1；引用不可见 evidence、不能直接支持 claim 的 evidence 或多余引用为 false positive。

`required_groups`/`acceptable_evidence_ids` 只能作为 group-level admissibility 的辅助上界检查，不能替代 claim-level mapping，也不能把 flow edge 当引用关系。

### End-to-End EM / Task Success

- **End-to-End EM**：Work-Order EM、Plan EM 和所有必需的 schema/visibility 条件同时成立；citation IDs 不进入语义 EM，但必须没有非法/不可见引用。
- **Task Success**：通过一个冻结的 checklist：schema 有效；diagnosis/status 与 gold 一致；全部 required actions 被 exact-match 且无额外 action；verification/uncertainty 一致；dependency closure 与 gold 一致且 order valid；所有必需 claims 至少有一个有效 citation。任一 required 条件失败即 0。该指标不能通过检索 Recall/FlowComplete 代理。

## 6. Split 与封存策略

- development/validation generation gold 可随协议版本公开，用于开发、调试、annotation QA 和模型选择；必须包含 gold/schema/canonicalization/annotation manifest 的 hash。
- generation gold 必须独立 author/seal：标注上下文不得访问任何 method prediction、五个 retrieval sealed-test prediction、retrieval test metrics、item-level retrieval gold、sealed evaluator、private blind-review artifact 或 adjudication reasoning。此前已经揭示的 retrieval aggregate 结果不应被传给 generation annotator；generation gold 的 provenance 应明确记录为 “authored and sealed independently without access to method predictions or item-level retrieval test gold”。
- test generation gold 生成后私有封存，由独立 evaluator 读取；方法阶段只能看到公开 query/evidence/部署元数据和 schema，不得看到 test generation gold、item-level rubric 或 task-success verdict。
- protocol、alias registry、parameter registry 和 gold schema version 在第一次 generation evaluation 前冻结。任何修改都产生新 protocol version，不得覆盖已评分结果。

## 7. 非目标

本协议不定义新的检索方法、动作规划方法、LLM prompt、模型训练、repair runner 或新的 benchmark 内容；本轮也不生成任何 generation gold。
