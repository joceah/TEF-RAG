# TEF-RAG v5：query-conditioned 集合级时序证据选择器

## 目标

v5 只替换 v4 的路径排序和 Top-k 填充。候选范围继续保持中性：同一资产，且 `event_time` 与 `available_at` 都不晚于查询时点。关系仍是公开记录上的有向 prior→update 投影；v5 不读取 gold、必要证据组、案例标签或人工事件图。

选择目标是一个固定容量集合，而不是若干路径前缀：

`F(S) = 0.45 Semantic(S) + 0.25 Chain(S|q) + 0.20 Role(S|q) - 0.10 Redundancy(S)`

- `Semantic`：候选池内归一化查询相关性之和除以 `top_k`。
- `Chain`：只统计两个端点都在集合中的、符合双时间方向的 prior→update 边。每类关系按 query-only profile 给出的需求权重聚合，并以 `1-exp(-x)` 饱和；每条边再由两个端点的查询相关性门控，避免仅因属于同一流程就获得足额奖励。
- `Role`：query-only profile 给出所需证据角色的软分布；单记录角色投影给出记录对角色的软归属。使用概率覆盖 `1-product(1-p)`，同角色重复证据的边际收益自然递减。
- `Redundancy`：记录对相似度的累计惩罚，以 `top_k` 的最大成对数归一化。优先使用调用方提供的通用相似度；缺省使用字符二元组与英文数字词元的 Jaccard，相同记录角色本身不被硬编码为冗余。

固定权重不是按 v8 成绩调整的结果；在任何新 holdout 生成或排名之前登记为 `0.45/0.25/0.20/0.10`。v8 只提供了“路径级目标与实际 Top-k 集合不一致”这一开发诊断，不用于选择这些数值。

## Query-conditioned evidence profile

检索接口接受只由查询文本和查询元数据产生的通用 profile：

```json
{
  "selection_mode": "set",
  "role_demands": {"observation": 0.8, "diagnosis": 1.0, "action": 1.0, "verification": 0.9},
  "relation_demands": {"follows": 0.5, "verifies": 1.0, "resolves": 0.9}
}
```

角色名不是按本轮题目枚举的触发词；它们是投影器可扩展的字符串标签。选择器不从中文关键词路由 objective，也不把查询词用于候选过滤。正式实验中的 profile 必须在检索前由只看查询的固定投影产生并缓存；记录角色只看单条公开记录；关系投影只看公开记录对。任一投影均不得读取 gold。

`selection_mode=latest` 是明确的简单最近记录控制。缺少 profile 时，v5 使用公开标记的 `neutral_default`：无角色需求、所有已知关系等权；不会偷偷退回旧关键词 objective。此兼容分支不作为“通用意图建模已经生效”的证据。

## 集合搜索与 Top-k

v5 对集合做确定性 beam search。每层只增加一个实际候选节点，按完整集合目标保留最多 64 个不同集合，直到达到 `top_k` 或字符预算不允许继续。最终选择达到最大可行深度的最高分集合，并保留产生该集合的真实加入顺序。

这有三个直接结果：

1. 路径不再作为不可分割的填充单元；剩余一个槽位时会重新比较所有可行单节点的集合边际收益，不存在 `novel[:remaining]` 路径前缀截断。
2. 方向链奖励只在 prior 与 update 都实际入选后激活；query-agnostic 的 `follows` 还要经过 query profile、端点相关性和集合冗余共同约束。
3. trace 每个条目对应一个真实入选节点，记录该步各目标分量的边际变化、当步激活且两端均已入选的边，以及精确的 `set_after`。不再记录未进入最终结果的整条路径。

## v5.1 Exact search 诊断

`search_strategy="exact"` 在完全相同的可见候选池、profile、role/relation projection、权重和字符预算上枚举所有可行 Top-k 组合。Beam 与 Exact 都只调用 `_score_set`，Exact 不读取 gold，也不加入 heuristic。若字符预算使 Top-k 不可行，则与 Beam 一样选择最大可行深度。

Exact 的集合 tie-break 依次为 total objective、semantic component、按字典序排序的 record IDs；集合内返回顺序按 prefix objective 最大化并以 sequence 字典序稳定化。冻结 seen diagnostic 的 12 个 set-mode 查询中，Beam/Exact set match rate 为 1.0000，mean/max objective gap 均为 0；复杂链 Complete@5 都是 0.1250。10 个不完整查询都存在可行的 gold-complete Top-5，但 Exact optimum 的 objective 均更高，平均 margin 为 0.0693（gold-dependent、仅离线诊断）。因此这批小候选池的失败不能归因于 beam approximation，现有 objective 确实偏好这些不完整集合。

完整逐题证据和结构指标见 `experiments/analyses/tef_v5_1_failure_attribution_v1/`。其中 gold-dependent bridge、flow 和 taxonomy 只存在于离线诊断脚本，不进入 retriever。

## 创新边界

这是一个待验证的工程设计，不在本阶段宣称论文创新或优势。集合覆盖、饱和收益、冗余惩罚和 beam search 都是常见思想；这里的研究问题仅是：把 query-only 证据需求、双时间有向更新边和实际 Top-k 集合放进同一个可审计目标，是否能修复已观察到的选择失配。

v5 不改关系抽取，不补查询关键词，不扩大候选过滤，不使用 gold，不评价最终回答生成，也不声称 TA-RAG/TG-RAG 的作者环境已被完整复现。
