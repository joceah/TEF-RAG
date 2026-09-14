# tef_v5_holdout_v3

这是 TEF-RAG v5 的冻结小型纯合成 holdout：4 个案例、48 条记录、16 个查询。

- `assets.json`：资产元数据。
- `evidence.jsonl`：公开候选记录。
- `queries.jsonl`：查询文本与知识截止时点。
- `evaluation/gold.jsonl`：只供检索完成后的独立评分进程读取。
- `authoring/blueprints.jsonl`：生成来源留痕；检索器不得读取。
- `manifest.json`：生成接口、模型用量和文件哈希。

状态为 `self_generated_holdout_frozen_without_independent_review`。该数据未经独立人工审查，且排名结果已经可见，今后只能用于复现和失败诊断，不能在调参后继续作为独立优势验证集。

## 真实来源与适用边界

本数据覆盖 GIS、断路器、SVG 阀冷和 UPS，是单独生成的纯合成集合。现有生成 manifest/blueprint 没有保存可核验的逐题公开文档 source ID，因此不能事后把某份厂家手册或旧 v2 的 S01-S11 冒充为本数据的直接引用来源。记录中的设备编号、人员、时间、数值、阈值和处置过程均不代表真实现场，也不能作为厂家 SOP 或安全操作指令。

项目中有明确公开资料映射的是旧 [`temporal_maintenance_dev_v2`](../temporal_maintenance_dev_v2/)；它的真实参考来源、采用范围和许可边界见 [`../../../plans/时序运维资料与案例设计_v1/资料来源与适用边界.md`](../../../plans/时序运维资料与案例设计_v1/资料来源与适用边界.md)。两个数据集的角色对比见 [`../../README.md`](../../README.md)。
