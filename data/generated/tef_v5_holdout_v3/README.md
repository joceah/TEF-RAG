# tef_v5_holdout_v3

这是 TEF-RAG v5 的冻结小型纯合成 holdout：4 个案例、48 条记录、16 个查询。

- `assets.json`：资产元数据。
- `evidence.jsonl`：公开候选记录。
- `queries.jsonl`：查询文本与知识截止时点。
- `evaluation/gold.jsonl`：只供检索完成后的独立评分进程读取。
- `authoring/blueprints.jsonl`：生成来源留痕；检索器不得读取。
- `manifest.json`：生成接口、模型用量和文件哈希。

状态为 `self_generated_holdout_frozen_without_independent_review`。该数据未经独立人工审查，且排名结果已经可见，今后只能用于复现和失败诊断，不能在调参后继续作为独立优势验证集。
