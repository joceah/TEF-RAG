<div align="center">

# TEF-RAG: Temporal Evidence Flow Retrieval-Augmented Generation

**面向动态运维知识的时间感知、关系感知证据集合检索框架**

[![Paper](https://img.shields.io/badge/Paper-PDF-B31B1B?logo=adobeacrobatreader&logoColor=white)](paper/TEF-RAG.pdf)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![RAG](https://img.shields.io/badge/RAG-Temporal%20Evidence%20Flow-6A5ACD)
![Domain](https://img.shields.io/badge/Domain-Energy%20Storage%20O%26M-00897B)
![Benchmark](https://img.shields.io/badge/Benchmark-400%20chains%20%7C%202400%20queries-EF6C00)

[**English**](README.md) | [**中文**](README.zh-CN.md)

</div>

<p align="center">
  <img src="assets/tef_rag_overview.png" width="100%" alt="TEF-RAG 模型结构">
</p>

## 项目简介

TEF-RAG 面向动态运维场景中的检索增强生成。此类任务不仅需要找到与问题语义相关的记录，还需要保证证据在查询时刻已经可用，并且多条证据能够共同支撑从状态观测、诊断到处置和验证的完整过程。

TEF-RAG 不再仅对单条文档独立排序，而是构建**查询条件化的 Temporal Evidence Flow**，并通过非线性成对排序器直接选择**证据集合**。

| 时间可见性 | 证据流推理 | 集合级选择 |
| --- | --- | --- |
| 根据事件时间、可用时间、资产范围和规程适用性过滤证据。 | 对候选证据对进行筛选，并推断 support、update、qualification、supersession、verification 等有向关系。 | 综合角色互补性、关系一致性和流程完整性，对候选证据集合进行排序。 |

## 论文

**TEF-RAG: Temporal Evidence Flow Retrieval-Augmented Generation**  
Juxian Yin

[📄 阅读论文](paper/TEF-RAG.pdf)

仓库公开编译后的论文 PDF，不提供 LaTeX 源文件。

## Benchmark

<p align="center">
  <img src="assets/benchmark_design.png" width="95%" alt="TEF-RAG Benchmark 构建流程">
</p>

| 统计项 | 数量 |
| --- | ---: |
| O&M 事件链 | 400 |
| 证据记录 | 3,888 |
| 任务意图 | 1,200 |
| 查询 | 2,400 |
| 目标资产 | 100 |

该 benchmark 属于**基于公开资料约束、AI 辅助构建的合成数据**。公开产品资料和研究数据集用于约束设备与采样背景；事件链、运维场景及任务设计用于受控实验，不应被解释为真实电站的故障频率统计。

## 实验结果

### Retrieval

| Method | Recall@5 | nDCG@5 | Complete@5 | FlowComplete@5 |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 0.3791 | 0.3915 | 0.0563 | 0.0563 |
| BGE Reranker | 0.2916 | 0.3070 | 0.0417 | 0.0417 |
| Temporal-BM25 | 0.4591 | 0.4955 | 0.0792 | 0.0792 |
| TA-RAG | 0.2769 | 0.2907 | 0.0375 | 0.0375 |
| **TEF-RAG** | **0.7228** | **0.6231** | **0.3188** | **0.3146** |

### Structured generation

| Method | Field F1 | Action F1 | Citation F1 | Plan EM |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 0.4715 | 0.1372 | 0.0813 | 0.0167 |
| BGE Reranker | 0.4129 | 0.1198 | 0.0405 | 0.0146 |
| Temporal-BM25 | 0.5218 | 0.1637 | 0.1249 | 0.0167 |
| TA-RAG | 0.4059 | 0.1115 | 0.0379 | 0.0188 |
| **TEF-RAG** | **0.5345** | **0.2035** | **0.1585** | **0.0417** |

机器可读的汇总结果见 [results/](results/)。

## 快速开始

~~~bash
git clone https://github.com/joceah/TEF-RAG.git
cd TEF-RAG

python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows
# .venv\Scripts\activate

python -m pip install -e .
~~~

无需调用外部模型即可验证数据并复现公开的 retrieval 指标：

~~~bash
python -m scripts.validate_public_retrieval
python -m scripts.evaluate_public_retrieval
~~~

验证 structured-generation benchmark：

~~~bash
python -m scripts.validate_public_generation
~~~

评估你自己的 structured-generation 预测：

~~~bash
python -m scripts.evaluate_public_generation --predictions /path/to/predictions
~~~

## 仓库结构

~~~text
TEF-RAG/
├── assets/              # 模型结构图与 benchmark 图
├── data/
│   ├── retrieval/       # Retrieval benchmark 与公开预测
│   └── generation/      # 结构化生成参考答案与 schema
├── models/              # Pair proposal 与 set ranking 模型
├── paper/
│   └── TEF-RAG.pdf      # 论文
├── results/             # 汇总实验结果
├── scripts/             # 公开验证与评估入口
└── tef_rag/             # 核心实现
~~~

## 数据与复现

仓库包含公开测试 evaluator 和对应预测，可以在本地复现论文中的 retrieval 结果表。公开 manifest 保留关键测试文件的稳定哈希。API key、本地缓存、私有审核材料以及开发阶段的实验文件不包含在本分支中。

## Citation

~~~bibtex
@misc{yin2026tefrag,
  title  = {TEF-RAG: Temporal Evidence Flow Retrieval-Augmented Generation},
  author = {Yin, Juxian},
  year   = {2026},
  url    = {https://github.com/joceah/TEF-RAG}
}
~~~
