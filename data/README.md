# 数据说明与真实来源边界

本仓库保存多个用途不同的合成数据集。它们都不是现场真实工单或真实故障统计，真实公开资料只用于约束故障机理、记录结构、时间边界和写作形态。

## 数据集分层

| 数据集 | 规模 | 用途 | 是否可作为新测试集 |
|---|---:|---|---|
| `generated/tef_v5_holdout_v3/` | 4 案、48 条记录、16 个查询 | v5 冻结复现与 v5.1 失败归因 | 否；排名结果已见 |
| `generated/temporal_maintenance_dev_v2/` | 48 台目标设备、192 条链、1,575 条证据、1,152 个问题 | 数据生成扩充、来源映射和开发基线 | 否；这是已使用的 dev 集 |
| `generated/tef_v6_temporal_hard_benchmark_v1/` | 100 assets、400 chains、1,200 primary intents、2,400 query rows | Frozen Protocol 下的正式 candidate；等待 sealed semantic review | 尚未；状态为 `UNREVIEWED_CANDIDATE` |

因此，仓库不再只有 16 题小数据，但新增的 v2 数据不能替代未来独立、未见、人工复核的测试集。v5 的 16 题足够复现当前集合选择器和定位失败原因，不足以支持外部有效性、真实故障率或论文最终优势结论。

## 真实公开资料怎样被使用

旧 v2 数据对每条合成链保存了 `source_ids`。完整逐项来源、适用边界和许可状态见 [`../plans/时序运维资料与案例设计_v1/资料来源与适用边界.md`](../plans/时序运维资料与案例设计_v1/资料来源与适用边界.md)，机器可读映射见 [`generated/temporal_maintenance_dev_v2/provenance.json`](generated/temporal_maintenance_dev_v2/provenance.json)。核心来源包括：

- Victron Energy 的 Lithium NG 51.2V 与 Lithium SuperPack NG 厂家手册；
- SMA Sunny Island 与 Sunny Central Storage 厂家手册；
- EPRI 储能事故根因白皮书；
- Energy Safe Victoria 的 Victorian Big Battery 技术调查；
- Vistra 对 Moss Landing 事故的阶段性更新和后续调查结论；
- Zenodo 电池系统维护数据记录、MaintIE 维护文本语料论文及 UPC 电池数据候选入口。

这些资料支持“可以设计哪些故障判别维度、记录字段和知识截止时点”，不证明合成设备、人员、日期、工单过程、阈值或发生频率来自真实现场。特别是 S09 只读取了元数据，S10 只参考了记录风格，S11 当时未核验成功；不得将它们写成已经使用的原始测量数据。

## v5 小数据的来源声明

`tef_v5_holdout_v3` 是单独生成的纯合成冻结集，覆盖 GIS、断路器、SVG 阀冷和 UPS。其生成记录没有保存可核验的逐题公开文档 source ID，因此不能事后把 Victron 电池手册或旧 v2 的 S01-S11 冒充为 v5 的直接引用来源。该数据中的数值、阈值和处置文字只用于检索机制测试，不是厂家 SOP 或现场安全指令。

## 原始资料与再分发

第三方网页或 PDF “公开可读”不等于允许在 GitHub 重新托管。仓库保存官方链接、访问日期、适用段落、本地核验哈希和许可判断；只有项目自有材料或许可明确的材料才应提交全文。当前运维手册的处理说明见 [`docs/README.md`](docs/README.md)。
