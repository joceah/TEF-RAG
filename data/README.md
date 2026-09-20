# 数据说明与真实来源边界

本仓库包含多个用途不同的合成数据集。它们都不是现场真实工单或真实故障统计；公开资料只用于约束可核验的设备参考边界、时间/记录结构与来源先例，未被公开来源直接支撑的运维因果链、阈值和处置逻辑必须标记为 synthetic modeling choice。

## 数据集分层

| 数据集 | 规模 | 用途 | 新测试集资格 |
|---|---:|---|---|
| `generated/tef_v5_holdout_v3/` | 4 案、48 条记录、16 个查询 | v5 冻结复现与 v5.1/v5.2 失败归因 | 否；已见结果 |
| `generated/temporal_maintenance_dev_v2/` | 192 chains、1,152 queries | 数据生成扩充、难度审计和开发基线 | 否；dev diagnostic |
| `generated/tef_v6_authoring_pilot_v1/` | 16 chains、32 queries | semantic authoring pilot | 否；pilot 已被正式 benchmark 替代 |
| `generated/tef_v6_temporal_hard_benchmark_v1/` | 100 assets、400 chains、1,200 primary intents、2,400 query rows | Frozen Protocol 下的 TEF-RAG v6 Semantic Benchmark v1 | 是；`FINAL_SEALED` |

## v6 semantic benchmark

- Frozen Protocol: `b0e6e004378e7d7f29cabece1efa6b2c30489e9b`。
- Validation 与 test 的 protocol-required blind second semantic review 均已完成；test 为 80/80 PASS、0 unresolved、0 disagreement。
- Development / validation 的 gold 与 canonical flow 可公开用于开发/模型选择；test evaluator 在正式评估期间保持 sealed，完成冻结后已公开原始 evaluator bytes；item-level review reasoning 仍不公开。
- Test evaluator 与 test second-pass item-level review artifact 在正式评估期间单独 sealed；正式 predictions/results 冻结后，历史 test evaluator 已按原始字节发布以支持复现。item-level review artifact 仍不公开。
- 尚未运行 TEF-RAG v6、reranker、multi-step retriever 或任何目标方法，因此数据没有按目标算法表现筛选。
- 正确定位：**public-source-grounded, AI-assisted synthetic benchmark**；不宣称 expert-reviewed、field-certified 或 real-world benchmark。

## 来源边界

v6 benchmark 的逐来源支持范围见 `generated/tef_v6_temporal_hard_benchmark_v1/metadata/source_registry.json`。HiTHIUM / REPT 只用于产品参考与厂家明确规格边界；RWTH M5BAT 只作为秒级 BESS field-data sampling precedent；synthetic procedure、故障演化、工单内容和因果链若无公开来源逐项支撑，统一作为 modeling choice。

第三方网页/PDF“公开可读”不等于允许重新托管。仓库只保存必要的来源元数据、链接、支持边界与生成数据，不重新分发无明确许可的第三方全文。
