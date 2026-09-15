# TEF-RAG 项目交接

更新时间：2026-09-15；当前分支：`tef-rag-v6-benchmark-protocol`；当前阶段：v5.2 accounting 已收尾，Temporal-Hard Benchmark Protocol 为 `DRAFT_FOR_REVIEW`，核心定义与原 DRAFT 参数均已给出确定方案，等待最终 freeze。

## 一页结论

TEF-RAG v5 已完成一个通用、query-conditioned、集合级时序证据选择器。它直接联合优化语义相关性、有向更新链覆盖、新证据角色边际增益和集合冗余，修复了 v4 的路径前缀截断及 trace 与最终结果不一致问题。

工程机制已经验证；研究优势尚未成立。新冻结 holdout 的复杂链 8 题中，v5 与 Scoped Hybrid 的 Group Recall@5 都是 0.6750，v5 的 nDCG 高 0.0233，但 Complete@5 从 0.2500 降至 0.1250。预登记的优势条件没有满足。

v5.1 已完成 exhaustive exact-search 归因：12 个 set-mode 查询中 Beam 与 Exact 集合完全一致，match rate 为 1.0000，mean/max objective gap 均为 0；复杂链 Recall / nDCG / Complete 仍同为 0.6750 / 0.7074 / 0.1250。当前 seen diagnostic 上没有搜索近似导致下降的证据，主要问题转向现有 objective/profile/role/relation projection 对 coherent evidence flow 的表达。

v5.2 完成 Profile / Roles / Relations 的 2×2×2 exact counterfactual：CCC 为 0.7208 / 0.7291 / 0.1667，OOO 提升至 0.8625 / 0.8752 / 0.5000，gross repair 4、regression 0、net gain +4，但仍有 6/10 个可行 gold-complete 查询被 frozen objective 选成 incomplete。Oracle Roles 单独 gross repair 1、regression 1、net gain 0。结论是 projection error 与 objective misalignment 共存，后续两者都要处理。

新 benchmark protocol 已完成 FlowComplete 全局一致性修订，并进一步指定正式规模与执行参数：`400 chains / 1200 primary intents / 2400 query rows / 100 assets`；Realistic/Challenge 各 200 chains；split 为 60/20/20；Challenge 为 160 single-primary + 40 compositional-hard；major stratum 以 20 primary chains / 60 intents 为门槛且 recency-solvable ceiling 为 0.50。Telemetry 采用 280Ah-class LFP reference system，并严格区分公开资料支撑的 physical envelope 与 benchmark modeling choices。Protocol 仍保持 `DRAFT_FOR_REVIEW`，未生成任何正式 benchmark 数据。

由于项目没有可用储能运维领域专家，审核协议明确禁止宣称 expert-reviewed / field-certified。正式 benchmark 采用 100% deterministic validation + 100% public-source-grounded AI-assisted semantic review；validation/test 再进行第二轮独立 AI review。未解决条目标记 `REVIEW_UNRESOLVED`，不得进入 validation/test。该限制必须在论文中披露。

## 已完成

1. 在任何新数据生成或排名前写入 [`plans/TEF_RAG_v5集合级选择预登记_v1.md`](plans/TEF_RAG_v5集合级选择预登记_v1.md)。
2. 在独立目录 `tef_rag_v5/` 实现固定集合目标和 64 宽确定性 beam；没有覆盖 v1–v4。
3. 先完成不读 gold 的单元测试和合成烟测，覆盖 query conditioning、角色边际增益、冗余、方向链、Top-k、预算、可见性、确定性与 trace。
4. 生成并冻结独立小型 holdout：4 案、48 记录、16 题；v8 没有再次作为优势验证集。
5. 查询 profile、记录角色和关系投影均在检索前生成；检索侧不读 gold。
6. Scoped Hybrid、Scoped Latest、v5、TA-RAG 和 TG-RAG 使用逐题相同的 8/12 条候选范围与 Top-5。
7. 59 个检索结果/完成文件在 gold-aware 评分前二次哈希封存。
8. 全工作区历史回归为 150 项测试通过，旧 freeze 校验 `matched=true`；本 GitHub 精简包在 v5 handoff 时为 27 项，v5.1 归档旧 v2 数据测试后当前为 41 项测试及 v5 烟测通过。
9. v5.1 新增 exact set search、Beam-vs-Exact 逐题归因、结构诊断与 failure taxonomy；检索阶段不读 gold，离线诊断阶段才读取 gold/authoring，且没有调用 LLM。

## 数据与实验状态

本仓库现在保留两层数据，角色不能混用：

- `data/generated/tef_v5_holdout_v3/`：4 个案例、48 条公开记录、16 个查询及冻结 gold；只供 v5 复现和 v5.1 失败归因。
- `data/generated/temporal_maintenance_dev_v2/`：48 台目标设备、192 条链、1,575 条证据和 1,152 个问题；配套 `provenance.json`、来源设计卡、生成配置/脚本/测试、统计报告和图均已归档，供后续扩充参考。
- 任务分层：8 个 `complex_chain`、4 个 `cutoff_sensitive`、4 个 `latest_control`。
- 候选范围：同资产，且 `event_time <= query_time`、`available_at <= query_time`；每题 8 或 12 条。
- 数据状态：`self_generated_holdout_frozen_without_independent_review`。

两个数据集都不是现场真实工单。旧 v2 的公开资料只用于故障机理、记录结构和时间边界约束；逐项真实来源和许可状态见 `data/README.md` 与 `plans/时序运维资料与案例设计_v1/资料来源与适用边界.md`。这 16 题和旧 v2 都是已见数据，不能在调参后继续宣称是独立验证。

## 主要指标

| 方法 | 全部16题 Recall / nDCG / Complete | 复杂链8题 Recall / nDCG / Complete |
|---|---:|---:|
| Scoped Hybrid | 0.7750 / 0.7757 / 0.5000 | 0.6750 / 0.6841 / 0.2500 |
| Scoped Latest | 0.5250 / 0.4752 / 0.2500 | 0.2687 / 0.2127 / 0.0000 |
| TEF-RAG v5 | 0.7906 / 0.7968 / 0.3750 | 0.6750 / 0.7074 / 0.1250 |
| TA-RAG 兼容运行 | 0.6969 / 0.6420 / 0.3125 | 0.5188 / 0.4928 / 0.0000 |

核心负面结论：集合目标改善了部分证据顺序与截止题覆盖，但没有提高复杂链平均 Recall，也降低了完整证据集合命中率。不要把全部 16 题上的小幅均值提升解释为通用优势。

## TEF-RAG v5.1 Failure Attribution

- 实现：`tef_rag_v5/exact_search.py` 逐一枚举相同候选池中所有可行 Top-k 集合；Beam 与 Exact 共享 `QueryConditionedSetEvidenceRetrieverV5._score_set`，没有复制 objective。
- 稳定性：Exact tie-break 为 total objective、semantic component、排序后的 record IDs；返回顺序再按相同 prefix-score 语义确定。
- 搜索结论：12/12 个 set-mode 查询 Beam 等于 Exact，objective gap 全为 0；10 个 Beam Complete 失败在 Exact 下全部持续，0 个由 Exact 修复。10 题都存在可行的 gold-complete Top-5，但 Exact optimum 对这些完整集合的 objective 平均高 0.0693（此比较只供离线诊断），直接说明当前 objective 更偏好不完整集合。
- 结构诊断：Exact 失败中 2 题表现为 role-complete but flow-incomplete，9 题表现为 relation-rich but flow-incomplete。taxonomy 是确定性规则生成的诊断候选，不是独立人工确认的因果真值。
- bridge/flow 边界：数据没有 canonical per-query gold chain edge list，因此 `required_bridge_miss_rate` 使用 projected-gold induced graph 的 articulation points，`flow_completion_rate` 使用该图的非单节点连通块；两者均是保守、projection-conditioned 指标。
- 结果入口：`experiments/analyses/tef_v5_1_failure_attribution_v1/report.md`、`results.json`、`per_query.csv`。
- 数据声明：这是 seen diagnostic set，只用于 failure attribution 和模型开发，不得作为新的 unbiased holdout 结果。

## 外部基线状态

TA-RAG 固定提交 `9e5e28a9e7ddad7d6d022c4d3533dbca2aff03b9`。官方时间解析器此前返回空结果，本次运行使用固定的“无事件区间、全语义检索”兼容分支，时间机制没有激活。

TG-RAG 固定提交 `58a57e0bc173064fa0ad7ccf595cf6e266523619`。前 11 题各返回 5 条；随后服务持续 HTTP 402，最后 5 题返回 0 条。本次 TG 结果标记为 `invalid_external_failure`，只保留诊断，不参与 v5 优势判断，也不得静默补写。

第三方官方源码未复制进仓库；位置与安装边界见 [`BASELINES.md`](BASELINES.md)。

## 模型调用与审计

- 选入数据生成：5 个响应、30,683 tokens；全部生成尝试：7 个响应、44,161 tokens。
- 选入 profile/角色/关系投影：12 个响应、31,075 tokens；含投影失败缓存：14 个响应、37,905 tokens。
- 可精确计量的选入生成与投影合计：17 个响应、61,758 tokens。
- TA 本轮新增 LLM 调用为 0。
- TG 的 8 个快照有 161 个缓存条目，但官方路径不提供精确 token usage。
- 没有上传 API key、`local.env`、请求头或环境内容。

## 可靠文件入口

按以下最小范围阅读即可：

1. 本文件。
2. [`plans/TEF_RAG_v6_temporal_hard_benchmark_protocol_v1.md`](plans/TEF_RAG_v6_temporal_hard_benchmark_protocol_v1.md) 与 [`configs/temporal_hard_benchmark_protocol_v1.json`](configs/temporal_hard_benchmark_protocol_v1.json)。
3. [`tef_rag_v5/DESIGN.md`](tef_rag_v5/DESIGN.md) 与 [`tef_rag_v5/retriever.py`](tef_rag_v5/retriever.py)。
4. [`experiments/analyses/tef_v5_1_failure_attribution_v1/report.md`](experiments/analyses/tef_v5_1_failure_attribution_v1/report.md) 与 [`experiments/analyses/tef_v5_holdout_eval_v1/report_zh.md`](experiments/analyses/tef_v5_holdout_eval_v1/report_zh.md)。

数据生成扩充时，再读 [`data/README.md`](data/README.md)、[`experiments/analyses/temporal_maintenance_dataset_v2/report_zh.md`](experiments/analyses/temporal_maintenance_dataset_v2/report_zh.md) 和 [`plans/时序运维资料与案例设计_v1/资料来源与适用边界.md`](plans/时序运维资料与案例设计_v1/资料来源与适用边界.md)。项目背景见 `docs/project_background/`；初代论文见 `paper/TMC_RAG_ICRA_style_zh_v2.pdf`，但论文尚未同步 v5/v5.1。

不要从旧 TMC 历史重新遍历项目，也不要运行旧 98 题。

## 下一步边界

Protocol 的关键定义与此前 DRAFT 参数现已指定，但整体状态仍是 `DRAFT_FOR_REVIEW`。下一步只做最终一致性/source audit 与用户确认；确认后用独立 commit 标记 `FROZEN BEFORE DATA GENERATION`，再开始正式 benchmark 生成。当前仍不得实现 v6，也不得根据目标算法结果改变 benchmark 构造规则。

审核阶段采用 public-source-grounded AI-assisted review，而不是领域专家认证。任何物理/规程事实若公开资料不足，应标记不确定或作为 modeling choice，不得伪装成现场标准。

最终回答生成评价是独立未完成任务，不应混入当前检索指标。论文也尚未因 v5 更新。
