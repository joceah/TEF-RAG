# TEF-RAG

Stage reports: [v6 Stage 2B constrained beam search](markdowns/tef_rag_v6_stage2b_beam_search.md), [Stage 2B.1 corrected comparison/oracles](markdowns/tef_rag_v6_stage2b1_correction.md), [Stage 2C bottleneck attribution](markdowns/tef_rag_v6_stage2c_bottleneck_attribution.md), [Stage 3A learned pair proposal](markdowns/tef_rag_v6_stage3a_learned_pair_proposal.md), and [Stage 3B learned set scorer](markdowns/tef_rag_v6_stage3b_learned_set_scorer.md).

TEF-RAG（Temporal Evidence Flow RAG）是面向运维记录的时序证据检索原型。v6 Stage 1 在 candidate retrieval 后执行确定性双时间/procedure 约束并构造 typed Temporal Evidence Flow；Stage 2A-1 在冻结其余 pipeline 的条件下增加 query-conditioned LLM relation scoring。详见 [`markdowns/tef_rag_v6_stage1.md`](markdowns/tef_rag_v6_stage1.md) 和 [`markdowns/tef_rag_v6_stage2a_llm_relation.md`](markdowns/tef_rag_v6_stage2a_llm_relation.md)。

> 当前状态（2026-09-16）：v6 Stage 2A-1 已在 sealed benchmark 的 development/validation 上完成受控 relation 实验，尚未运行 test。请把本仓库视为可复现的研究开发快照，不是已验证的生产系统。

## v5 做了什么

v5 在同资产、事件时间和入库时间均可见的中性候选池中，联合优化：

`F(S) = 0.45 Semantic + 0.25 DirectedChain + 0.20 RoleCoverage - 0.10 Redundancy`

- 语义相关性：候选与当前查询的匹配程度。
- 有向时序链：只奖励两个端点都真实入选、满足 prior→update 双时间方向且与查询需求相关的边。
- 角色边际增益：优先补齐观察、诊断、操作、验证等尚未覆盖的证据需求。
- 集合冗余：抑制内容高度相似的重复记录。
- 实际轨迹：trace 与最终 `evidence_ids` 一一对应，不记录未进入结果的路径。

算法边界和接口见 [`tef_rag_v5/DESIGN.md`](tef_rag_v5/DESIGN.md) 与 [`tef_rag_v5/README.md`](tef_rag_v5/README.md)。

## 当前结果

冻结 holdout 包含 4 个纯合成案例、48 条记录、16 个问题；没有使用旧 98 题，v8 只作为开发失败诊断集。仓库另归档了较大的 `temporal_maintenance_dev_v2`（192 条链、1,575 条证据、1,152 个问题）供来源映射和后续数据扩充参考，但它是已经使用过的 synthetic dev，不是新的独立测试集。

| 复杂链 8 题 | Group Recall@5 | binary nDCG@5 | Complete@5 |
|---|---:|---:|---:|
| Scoped Hybrid | 0.6750 | 0.6841 | 0.2500 |
| TEF-RAG v5 | 0.6750 | 0.7074 | 0.1250 |
| TA-RAG 兼容运行 | 0.5188 | 0.4928 | 0.0000 |

v5 对 Hybrid 的 Recall 为 1 胜、6 平、1 负，未满足“平均 Recall 严格更高且胜多于负”的预登记条件；虽然 nDCG 略高，但集合完整性更低，因此不能宣称通用优势。完整结果见 [`experiments/analyses/tef_v5_holdout_eval_v1/report_zh.md`](experiments/analyses/tef_v5_holdout_eval_v1/report_zh.md)。

## 快速开始

核心选择器只依赖 Python 标准库；建议 Python 3.11+。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
python -m pip install -e ".[test]"
python -m pytest -q
python -m scripts.smoke_tef_rag_v5
```

语义复现实验还需要 `numpy`、`onnxruntime`、`tokenizers` 和一个兼容的 384 维 multilingual MiniLM ONNX 模型：

```bash
python -m pip install -e ".[semantic]"
```

原本地模型文件和任何服务凭据都没有上传。冻结后的嵌入、检索输出和评分结果已保留，足以审计本次报告。

## 仓库结构

- `tef_rag_v5/`：当前集合级选择器。
- `tef_rag_v6/`：v6 candidate、temporal constraint、typed relation、LLM relation client 与 flow selector。
- `tef_rag_v1/`–`tef_rag_v4/`、`tmc_rag_v3/`：v5 仍调用的兼容依赖与历史接口，不代表需要重新运行旧实验。
- `baseline_adapters/`：Scoped、TA-RAG、TG-RAG 的查询/来源恢复适配代码。
- `scripts/`：v5 烟测、共享候选运行、外部基线封装、封存和 gold-aware 评分脚本。
- `tests/`：TEF v1–v5 与必要适配器的测试。
- [`data/README.md`](data/README.md)：数据集分层、真实参考来源和再分发边界。
- `data/generated/tef_v5_holdout_v3/`：本次冻结小型数据及评价 gold。
- `data/generated/temporal_maintenance_dev_v2/`：旧 v2 合成开发集及逐链来源映射，配套配置、生成脚本、测试和分析报告已归档。
- `experiments/`：精选投影、逐题检索输出、冻结清单和最终分析；未包含大型图缓存。
- `plans/`：v5 预登记，以及旧 v2 的数据设计、真实资料来源和生成协议。
- [`docs/project_background/`](docs/project_background/)：项目背景 DOCX 的去元数据公开副本。
- [`paper/`](paper/)：初代中文论文 PDF 和历史实验图。
- [`PROJECT_HANDOFF.md`](PROJECT_HANDOFF.md)：给新接手者的当前状态、可靠结论和下一步边界。
- [`BASELINES.md`](BASELINES.md)：外部基线位置、固定提交和复现限制。

## 研究边界

- 数据是自生成且未经独立人工审查的小样本，只能做机制验证。
- 旧 v2 虽然规模更大并有公开资料约束，仍是合成且已见的 dev；真实公开资料不等于真实工单或真实故障频率。
- 不根据本 holdout 分数继续调整 v5 后再把同一数据称作独立验证。
- TG-RAG 后 5 题因外部模型 HTTP 402 失败，原结果保留但不进入主胜负比较。
- 最终回答生成质量尚未评价；本仓库报告的是检索机制。
- 没有上传密钥、本地环境文件、模型权重、第三方仓库或大型图缓存。未确认允许再分发的第三方手册只保留官方链接、哈希和引用边界，不镜像全文。
