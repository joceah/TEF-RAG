# TEF-RAG v5

`QueryConditionedSetEvidenceRetrieverV5` 是独立开发版本。它继承 v4 的中性候选范围与 v3 的 prior→update 双时间边语义，但以固定集合目标直接选择 Top-k，不再按路径排序后截取路径前缀。

```python
from tef_rag_v5 import QueryConditionedSetEvidenceRetrieverV5

retriever = QueryConditionedSetEvidenceRetrieverV5(
    records,
    assets,
    relations,
    roles=record_role_projections,
    top_k=5,
)
result = retriever.retrieve(
    query,
    relevance,
    relation_scores=query_conditioned_pair_scores,
    query_profile={
        "selection_mode": "set",
        "role_demands": {"diagnosis": 1.0, "action": 1.0, "verification": 1.0},
        "relation_demands": {"verifies": 1.0, "resolves": 0.8},
    },
    redundancy_scores=pairwise_similarity,
)
```

`query_profile` 必须只由查询文本和查询元数据产生；`roles` 只看单条公开记录；关系和可选成对分数只看公开记录或通用表示。选择器不读取 gold，不按当前题目枚举关键词，不用查询词缩小候选。

核心输出：

- `evidence_ids`：最终实际返回顺序；
- `trace`：与 `evidence_ids` 一一对应的真实逐节点选择历史；
- `selected_edges`：两个端点都真实入选的有向边；
- `score_components`：语义、链覆盖、角色覆盖、冗余惩罚及总分；
- `query_profile` / `profile_source`：实际使用的归一化需求与来源；
- `rejected_edges`：违反关系类型或相应时钟方向的候选边。

固定目标与实验边界见 [DESIGN.md](DESIGN.md)；预登记见 `plans/TEF_RAG_v5集合级选择预登记_v1.md`。

## 当前验证状态

v5 已在独立冻结的纯合成小型 holdout 上完成检索验证：4 个案例、48 条记录、16 个问题。核心复杂链 8 题中，v5 与 Scoped Hybrid 的 Group Recall@5 同为 0.6750，binary nDCG@5 高 0.0233，但 Complete@5 由 0.2500 降至 0.1250；未满足预登记的优势判据。因此当前只能确认集合目标、Top-k 截断和可审计 trace 已实现，不能宣称形成通用检索优势。

v8 仍只作为开发诊断集，旧 98 题未重跑，最终回答生成尚未评价。完整结果与限制见 `experiments/analyses/tef_v5_holdout_eval_v1/report_zh.md`。
