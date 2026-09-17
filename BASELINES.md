# TEF-RAG v6 Baseline Plan

本文件定义 TEF-RAG v6 正式 baseline suite、输入边界和冻结协议。目标不是复现大量复杂 RAG 系统，而是用少量、可解释、可公平复现的对照覆盖 lexical、semantic reranking、simple temporal retrieval 和近期 temporal-aware RAG 四条能力轴。

复杂的 MRAG、Temporal-GraphRAG、RAPTOR 等方法不进入 v6 正式主表；相关历史适配与 compatibility audit 保留在仓库历史中，仅作为 Related Work / 工程记录，不作为本轮必须完成的 baseline。

## 1. 正式主表

最终主比较固定为以下 5 个方法：

1. **BM25**
2. **BM25 + BGE-Reranker**
3. **Temporal-BM25**
4. **TA-RAG**
5. **TEF-RAG v6**

本轮只实现和冻结 baseline；TEF-RAG 内部 ablation 后续单独进行，不与 baseline reproduction 混在一起。

---

## 2. 统一公平性协议

所有方法从同一 deployment-visible corpus 开始。对查询 `q`，先构造 query-time safe snapshot：

```text
K(q) = { e | event_time(e) <= query_time(q)
             and available_at(e) <= query_time(q)
             and public scope is valid }
```

统一要求：

- baseline 只能读取 query text、`query_time` 和部署时可见的 evidence text / metadata；
- 禁止读取 `required_groups`、`required_flow_edges`、`allowed_endpoint_pairs`、FlowComplete label、`chain_id`、difficulty、answer-side metadata 或 private test artifact；
- 不共享 TEF-RAG 内部 Top-30 candidate pool；各 baseline 必须从相同 visible corpus 独立完成自己的 retrieval/reranking；
- 不允许先用未来语料建立 summary/index/embedding/graph，再仅在最终输出阶段过滤未来 evidence；
- 所有方法最终输出 **Top-5 original evidence IDs**；
- provenance mapping 必须 deterministic、去重、gold-free；
- 候选不足 5 条时允许少于 5 条；
- test 只在所有方法配置冻结后首次运行，不根据 test 结果修改 baseline。

统一主指标：

- Recall@5
- Hit@5
- nDCG@5
- Complete@5
- FlowComplete@5
- Edge Recall

---

## 3. BM25

### 目的

提供最基础 lexical retrieval 下限，回答：不显式建模语义重排、时间相关性或 evidence flow 时能做到多少。

### 实现

优先复用仓库现有 BM25 / v6 candidate retrieval 代码，不重复实现新的 tokenizer/scorer。

流程：

```text
visible corpus -> BM25(query, evidence text) -> Top-5
```

要求：

- 只共享统一 visibility snapshot；
- 不使用 TEF-RAG relation / pair proposal / set scorer；
- 参数若已有冻结实现则直接复用；若必须选择参数，只在 development 上完成并 freeze。

状态：`TO_REPRODUCE_V6`

---

## 4. BM25 + BGE-Reranker

### 目的

提供强通用 semantic reranking baseline，回答：TEF-RAG 的收益是否仅来自更强的语义相关性模型。

### 实现

固定为：

```text
visible corpus
-> BM25 Top-30
-> BAAI/bge-reranker-v2-m3
-> Top-5
```

要求：

- BGE 只做 query-document relevance reranking；
- 不输入 `event_time`、关系标签、flow feature 或 gold；
- 记录准确模型 revision / hash；
- 不在 validation/test 上调 candidate size、batch size 之外会改变排名语义的参数；
- candidate depth 固定为 30，与 TEF-RAG 的 first-stage candidate budget 对齐，但候选由该 baseline 自己的 BM25 从完整 visible corpus 产生。

状态：`TO_IMPLEMENT`

---

## 5. Temporal-BM25

### 目的

提供透明、轻量的 simple temporal baseline，回答：仅在 lexical relevance 上加入时间相关性，是否已经足以解决任务。

### 定义

先计算 BM25 score，再加入 query-conditioned temporal score：

```text
score(e,q) = lambda * normalized_BM25(e,q)
           + (1-lambda) * temporal_score(e,q)
```

要求：

- 基础 visibility 条件 `event_time <= query_time` 且 `available_at <= query_time` 对所有方法共享，不计为该 baseline 的额外优势；
- `temporal_score` 只能使用 query text、`query_time` 和 evidence `event_time` 等 deployment-visible 信息；
- 不使用 gold temporal intent；
- 时间需求从 query text 通过固定规则或冻结解析逻辑获得；实现必须简单、透明、可审计；
- `lambda` 只允许在 development 上从一个很小的预定义集合中选择一次，例如 `{0.25, 0.5, 0.75}`；选择后 freeze；
- 无明确时间偏好的 query 应退化为语义主导排序，不能人为注入 gold 时间窗口。

该方法是本项目自定义 baseline，论文中命名为 **Temporal-BM25**，不得冒充 MRAG 或其他已有方法。

状态：`TO_IMPLEMENT`

---

## 6. TA-RAG

### 目的

作为唯一正式 external temporal-aware RAG baseline，回答：与近期专门面向 diachronic / temporal retrieval 的方法相比，TEF-RAG 是否仍有额外收益。

### 上游

- Repository: `https://github.com/kwunhang/TA-RAG`
- Frozen upstream commit: `9e5e28a9e7ddad7d6d022c4d3533dbca2aff03b9`
- License: CC BY-NC-SA 4.0

### 正式 v6 复现要求

必须使用官方核心 temporal mechanism：

```text
query
-> official temporal_process_sentence()
-> temporal decomposition / intervals
-> NCLS temporal filtering
-> Nomic embedding + FAISS semantic retrieval
-> Top-5 original evidence IDs
```

依赖包括：

- FAISS
- NCLS
- NumPy / pandas
- PyTorch
- SentenceTransformers
- `nomic-ai/nomic-embed-text-v1.5` (768d)
- OpenAI-compatible LLM endpoint

适配边界：

- 每个 query 只基于该 query 的 safe snapshot 建立或加载 index；
- 相对时间表达以 benchmark `query_time` 为 reference date，而不是运行机器的 `date.today()`；
- TEF 的 point `event_time` 为适配 interval index，可确定性表示为一个极短的 half-open interval；这是 **TEF compatibility adaptation**，不是声称 TA-RAG 官方规定点事件必须如此表示；
- `corpus_uid` / provenance 始终保留 original evidence ID；
- 不允许使用 v5 的 `NoEventIntervalParser` compatibility branch 作为正式 v6 TA-RAG；
- 若官方 temporal parser / Nomic / FAISS / NCLS 栈无法稳定运行，必须报告失败，不能悄悄退化成简化版本仍称 TA-RAG。

状态：`READY_WITH_ADAPTATION`

---

## 7. TEF-RAG v6

正式方法使用当前冻结 Stage3D：

- learned pair proposal；
- query-conditioned relation graph；
- nonlinear RankNet set utility；
- one-round model hard-negative mining；
- final output Top-5 original evidence IDs。

在 baseline reproduction 阶段禁止继续修改 TEF-RAG 方法或超参数。

当前正式方法分支 / commit 应在 baseline freeze manifest 中记录，而不是依赖浮动 branch HEAD。

---

## 8. 数据使用与冻结顺序

### Development

允许：

- 调通 baseline adapter；
- Temporal-BM25 选择 `lambda`；
- 确认模型/index/runtime 参数；
- 修复 implementation bug；
- 生成 baseline freeze manifest。

### Validation

仅运行 development-frozen 配置，用于一次确认。

禁止：

- 根据 validation 改 `lambda`；
- 改 BGE candidate depth；
- 修改 TA-RAG parser/index 逻辑；
- 选择对 TEF-RAG 更有利的 baseline variant。

### Test

所有方法完全冻结后第一次正式运行：

```text
BM25
BM25 + BGE-Reranker
Temporal-BM25
TA-RAG
TEF-RAG
```

不得根据 test 结果继续调参或更换 baseline。

---

## 9. Reproducibility requirements

正式 baseline freeze 至少记录：

- TEF-RAG method commit；
- benchmark seal commit；
- baseline code commit；
- BM25 config；
- BGE model name + revision/hash；
- Temporal-BM25 formula + lambda；
- TA-RAG upstream commit；
- TA-RAG embedding model revision；
- TA-RAG LLM endpoint/model alias；
- dependency versions；
- random seeds；
- development/validation run hashes；
- output schema；
- Top-k = 5。

第三方源码、模型权重、LLM cache、API key 和 private test artifact 不提交到本仓库。

---

## 10. Deferred experiments

以下内容不属于当前 baseline reproduction：

- TEF-RAG ablation；
- MRAG reproduction；
- Temporal-GraphRAG / GraphRAG；
- RAPTOR；
- Re3；
- 额外 dense retriever sweep；
- 更多 reranker/model sweep。

这些项目只有在主 baseline suite 完成后、且确有论文必要时才考虑；默认不继续扩展。
