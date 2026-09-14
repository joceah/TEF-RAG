# TEF-RAG v5 holdout v3：TG-RAG 外部失败处置

记录时间：2026-09-14。本文写于读取 gold 并计算评价指标之前；检索输出已经由各运行目录的 completion 文件及其逐题哈希固定。

## 事实

- TG-RAG 固定流程完成了 8 个候选快照和 16 个查询的落盘。
- 从 `tefv5h-q-03-02` 开始，图抽取调用持续返回 HTTP 402 `Insufficient Balance`。
- 受影响查询为 `tefv5h-q-03-02`、`tefv5h-q-04-00`、`tefv5h-q-04-01`、`tefv5h-q-04-02`、`tefv5h-q-04-03`，返回证据数均为 0；此前 11 个查询各返回 5 条。
- 这是外部依赖失败，不是共享候选范围或 Top-k 的协议变化。

## 评分前处置

1. 不删除、不覆盖、不补跑本次 TG-RAG 结果；原始失败结果和哈希全部保留。
2. 主公平比较只包含完整返回 Top-5 的 `scoped_hybrid`、`scoped_latest`、`tef_v5` 和 TA-RAG 兼容运行。
3. TG-RAG 仍计算描述性指标，但明确标记为 `invalid_external_failure`，不参与 v5 胜负或优势判断。
4. 不把 TG-RAG 的异常低分作为 v5 优势证据。
5. 不因本次结果修改候选集、Top-k、v5 权重、query profile、关系投影或 gold。

本处置不改变此前预登记的核心方法与指标，只防止把供应商余额失败误当成检索方法差异。
