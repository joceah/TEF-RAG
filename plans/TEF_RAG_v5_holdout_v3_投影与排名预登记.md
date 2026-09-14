# TEF-RAG v5 holdout v3：无gold投影与排名预登记

登记时间：2026-09-14。数据已经冻结，尚未运行任何检索或gold评分。

## Query-only evidence profile

每个资产的4条查询作为一次请求，只提供`query_id`、`query_time`和公开问题文本，不提供记录、关系、task标签、gold、答案或作者字段。模型输出：

- `selection_mode`：`set`或`latest`；只有问题明确需要单条最新业务状态时使用latest，其余使用set；
- `role_demands`：以下通用角色的非负软需求：`observation, hypothesis, diagnostic_check, diagnostic_clue, localization, action, verification, procedure, closure, context`；
- `relation_demands`：`follows, same_process, supports, verifies, refutes, supersedes, resolves`的非负软需求。

不编写当前16题的关键词规则，不读取候选记录来反推需求。每案一个主请求；schema失败最多一次完整修复。

## Public-record role and relation projection

每个资产的12条公开记录作为一次独立请求，只提供ID、双时间、kind、工单号和公开text，不提供查询、gold、答案、作者角色或作者逻辑边。模型同时输出每条记录对同一通用角色体系的`role_scores`，以及prior→update公开关系。过程关系按event_time，知识关系按available_at；非空且不相交工单之间不得仅凭日期用follows/same_process连接。每案一个主请求；schema失败最多一次完整修复。

## 固定排名

- 语义分数完全复用既有共享Hybrid的编码器、BM25+dense RRF与知识截止文本规范化；逐题所有方法共享同一8/12条可见候选和Top-5。
- v5使用已冻结的`0.45 semantic + 0.25 chain + 0.20 role - 0.10 redundancy`、beam width 64；冗余使用v5已登记的公开文本缺省Jaccard，不按结果提供人工成对分数。
- scoped Hybrid与scoped Latest不削弱；TA-RAG、TG-RAG使用此前固定官方提交和同一兼容层。若外部方法运行成本或接口再次失败，原样记录，不以弱化替代结果。
- 所有检索输出和哈希先封存，之后独立评价进程才读取gold。主要指标、分层与失败判据沿用`TEF_RAG_v5集合级选择预登记_v1.md`，不评价最终答案生成。
