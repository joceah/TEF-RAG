# 基线代码与复现边界

本仓库上传的是项目实际使用的适配器和运行封装，不重新分发第三方官方仓库。

## Scoped Hybrid / Scoped Latest

这两个内部基线与 v5 共享完全相同的逐题候选 ID 和 Top-5。

- Hybrid/可见性实现：`scripts/run_tef_shared_complex_v1.py`
- v5 共享运行入口：`scripts/run_tef_v5_holdout_shared_v1.py`
- 查询文本规范化：`baseline_adapters/query_text_v2.py`
- 已冻结逐题输出：`experiments/runs/tef_v5_holdout_shared_v1/queries/`

## TA-RAG

- 上游仓库：[kwunhang/TA-RAG](https://github.com/kwunhang/TA-RAG)
- 固定提交：`9e5e28a9e7ddad7d6d022c4d3533dbca2aff03b9`
- 本项目封装：`scripts/run_ta_rag_complex_v1.py`、`scripts/run_ta_rag_complex_v2.py`、`scripts/run_ta_rag_v5_holdout_v1.py`
- 共享输入适配：`baseline_adapters/ta_tg_v1.py`
- 冻结结果：`experiments/runs/ta_rag_v5_holdout_v1/`

复现时将上游固定提交放到 `experiments/runtime/ta_rag_v1/`，另行安装其 FAISS、NCLS 等依赖。本次官方 LLM 时间解析没有成功，实际结果属于已披露的无事件区间语义兼容分支，不能视为完整激活 TA-RAG 时间机制。

## TG-RAG / Temporal-GraphRAG

- 上游仓库：[hanjiale/Temporal-GraphRAG](https://github.com/hanjiale/Temporal-GraphRAG)
- 固定提交：`58a57e0bc173064fa0ad7ccf595cf6e266523619`
- 本项目封装：`scripts/run_tg_rag_complex_v1.py`、`scripts/run_tg_rag_complex_v2.py`、`scripts/run_tg_rag_v5_holdout_v1.py`
- 来源恢复适配：`baseline_adapters/tg_rag_source_v2.py`
- 精选冻结结果：`experiments/runs/tg_rag_v5_holdout_v1/`

复现时将上游固定提交放到 `experiments/runtime/tg_rag_v1/` 并按上游说明安装依赖。本地检出的上游快照没有许可证文件，因此本仓库没有复制其源码，只保留自己的兼容层和上游链接。

本次 TG-RAG 前 11 题完成，后 5 题因供应商 HTTP 402 余额不足返回 0 条；这些输出原样保留，但已在评分前声明为外部失败，不进入主公平胜负比较。36MB 图缓存和模型响应缓存没有上传。

## TEF-RAG v6 待复现外部时序基线

以下两项已确定为 v6 正式外部时序对照候选。当前仅完成方法与适配可行性核验，尚未在 v6 benchmark 上生成正式结果；在首次 sealed test 前应固定上游版本、适配协议、输入字段和 Top-5 输出映射。

### MRAG（待复现）

- 论文：Siyue Zhang et al., *MRAG: A Modular Retrieval Framework for Time-Sensitive Question Answering*, Findings of EMNLP 2025.
- 官方代码：[siyue-zhang/MRAG](https://github.com/siyue-zhang/MRAG)
- 方法性质：training-free temporal retrieval framework。
- 核心机制：将查询拆分为语义内容与时间约束；对召回证据进行细粒度处理/摘要；分别计算语义相关性与时间相关性并进行混合排序。
- v6 适配原则：使用部署可见的 query text、`query_time`、evidence text、`event_time` / `available_at`；不得读取 required groups、flow gold、chain construction metadata 或 test private artifact。
- 输出统一为原始 evidence ID 的 Top-5；若 MRAG 中间产生摘要/细粒度片段，必须使用预先冻结的 provenance 映射回原始 evidence ID。
- 公平性要求：与 TEF-RAG 共享同一 query-time visibility snapshot，不允许通过先构建全时段摘要再在输出端过滤的方式利用未来信息。
- 上游审计提交：`19f3bcf9a365f9379e12edc13bec96c9ec557e1a`（2026-09-17 的 `master` HEAD）。
- License：MIT。
- 依赖：Contriever/一阶段召回、PyTorch/CUDA、`vllm`、NLTK、SciPy、Transformers/SentenceTransformers 或 FlagEmbedding reranker、NV-Embed-v2，以及 Llama 3.1 8B/70B 类关键词提取与 query-focused summarization 模型。
- 计划适配：先按 `query_time` 构造无未来信息 snapshot；原始 evidence ID 作为 passage/sentence/summary 的不可变 provenance；最终按官方 sentence hybrid rank 顺序去重并截断 Top-5。
- 已知限制：论文要求 LLM question decomposition，但公开实现读取 TempRAGEval 的 `time_relation` 注释，没有通用官方解析入口；v6 不能使用构造元数据补该字段。摘要是正式核心流程，不能删去或用 BM25+time-decay 冒充。
- 状态：`BLOCKED`。在冻结通用 decomposition 协议并完成官方 GPU/LLM/reranker end-to-end smoke 前，不进入正式 v6 reproduction。

### TA-RAG（待完整复现）

- 论文：Kwun Hang Lau et al., *Reading Between the Timelines: RAG for Answering Diachronic Questions*, 2025, arXiv:2507.22917.
- 官方代码：[kwunhang/TA-RAG](https://github.com/kwunhang/TA-RAG)
- v5 历史适配见上文；v5 结果未完整激活官方 LLM 时间解析，因此不得直接作为 v6 正式外部基线结果。
- 核心机制：将查询拆分为主题语义与时间窗口，并在检索中联合语义相关性与时间相关性，形成覆盖目标时间范围的时间一致证据集合。
- v6 复现要求：优先完整激活官方 temporal parsing / interval logic；若官方模块仍无法稳定运行，必须单独标记为兼容分支，不得称为完整 TA-RAG。
- v6 适配原则：使用部署可见的 query/evidence 字段，统一 query-time visibility snapshot，最终输出原始 evidence ID Top-5。
- 上游固定/当前提交：`9e5e28a9e7ddad7d6d022c4d3533dbca2aff03b9`（审计时 upstream HEAD 未变化）。
- License：CC BY-NC-SA 4.0。
- 依赖：FAISS、NCLS、NumPy、pandas、PyTorch、Transformers/SentenceTransformers、`nomic-ai/nomic-embed-text-v1.5`（768d），以及 OpenAI-compatible LLM endpoint；公开配置使用 `meta-llama/Llama-3.3-70B-Instruct`。
- 计划适配：每个 query-time snapshot 独立构建 FAISS/NCLS；point `event_time` 映射为一秒区间；相对时间以 `query_time` 而非机器当前日期解释；`corpus_uid` 直接保留 original evidence ID，去重后返回 Top-5。
- 已知限制：没有预建 v6 index/权重；需要下载 embedding model 并配置 LLM。v5 注入空 temporal decomposition，并替换为 MiniLM/NumPy/线性 interval 兼容实现，因此不是完整 TA-RAG。
- 状态：`READY_WITH_ADAPTATION`。完成上述有限 adapter 与依赖冻结后，可进入正式 v6 reproduction。

这两个方法承担与 BM25 / temporal-filter 等基础对照不同的角色：BM25 类基线用于刻画普通检索下限，MRAG 与 TA-RAG 用于比较近期 temporal-aware RAG。正式 v6 结果只在适配协议冻结后产生，不根据 TEF-RAG 的 test 表现反向修改基线。

## 公平性约束

所有方法逐题共享：

- 同一个资产范围；
- `event_time` 与 `available_at` 均不晚于 `query_time`；
- 相同的 8 或 12 条候选记录；
- Top-k 固定为 5。

候选映射保存在 `experiments/runs/ta_tg_input_v5_holdout_v1/snapshot_mapping.json`，检索输出哈希保存在 `experiments/analyses/tef_v5_holdout_retrieval_freeze_v1/retrieval_freeze_manifest.json`。
