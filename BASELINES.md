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

## 公平性约束

所有方法逐题共享：

- 同一个资产范围；
- `event_time` 与 `available_at` 均不晚于 `query_time`；
- 相同的 8 或 12 条候选记录；
- Top-k 固定为 5。

候选映射保存在 `experiments/runs/ta_tg_input_v5_holdout_v1/snapshot_mapping.json`，检索输出哈希保存在 `experiments/analyses/tef_v5_holdout_retrieval_freeze_v1/retrieval_freeze_manifest.json`。
