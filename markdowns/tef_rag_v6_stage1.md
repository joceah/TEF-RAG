# TEF-RAG v6 Stage 1

## 1. Motivation

v6 将检索对象从独立 Top-k 文档改为与 `query_time` 一致的有类型 Temporal Evidence Flow。第一阶段目标是建立可运行、可解释、可消融的 deterministic baseline，而不是训练复杂神经模型。

## 2. Implemented pipeline

`BM25 candidate pool → asset/bitemporal/procedure hard constraints → node and typed-edge scoring → deterministic greedy flow search → structured prediction`

实现入口为 `tef_rag_v6/pipeline.py`，实验入口为 `python scripts/run_tef_rag_v6_stage1.py`。runner 只接受 `development`、`validation` 或 `both`，没有 test 运行选项。

## 3. Algorithm

- Candidate retrieval：同资产宽候选池，中文 unigram/bigram + Latin word BM25；资产长名称在 BM25 前移除，因为资产一致性已由 metadata 硬约束。
- Temporal eligibility：强制 `event_time <= query_time`、`available_at <= query_time`。procedure 额外强制 `valid_from <= query_time < valid_to`、`withdrawn_at` 和 `model_scope`。
- Node score：BM25 relevance、query-dependent recency、event-role compatibility 和 metadata compatibility 的加权和。
- Edge score：只使用 frozen taxonomy 中的 `supports / contrasts / updates / supersession / prerequisite / verification` 等实际类型；结合 metadata、时间方向、episode/chain coherence 与 lexical overlap。`supersedes` 显式生成 prior→replacement 的 `supersession` 边。
- Flow score：node sum + typed-edge utility + role coverage − redundancy − disconnected penalties。每个 target 只计最佳 incoming edge，避免 dense graph 虚增。
- Search：对 top-30 scoring nodes 做 deterministic greedy marginal selection，最多 5 个节点，同时序列化 retrieval rank、时间有序 flow、node/edge score 和 constraint rejection。
- Persistent uncertainty：若选中 unresolved uncertainty evidence，则输出 `persistent`；若后续明确 correction/verification resolve，则输出 `resolved`。该状态不强迫所有 query 收敛到唯一诊断。

关键参数集中在 `configs/tef_rag_v6_stage1.json`，seed 固定为 `20260916`。

## 4. Experiment setup

- Benchmark：`TEF_RAG_v6_temporal_hard_benchmark_v1`，状态 `FINAL_SEALED`，protocol commit `b0e6e004378e7d7f29cabece1efa6b2c30489e9b`。
- 使用范围：development 1,440 queries；validation 480 queries。只读取公开 dev/validation gold/canonical flow；test gold、sealed evaluator、private reviewer artifact 均未读取。
- Top-k：5。主指标按 frozen protocol 为 Recall@5、binary nDCG@5、Complete@5、FlowComplete@5；FlowComplete adapter 实现 existential、global-consistent required-group assignment。edge recall 为 secondary diagnostic。
- `bm25` 是无时间过滤的对照诊断，用来量化约束贡献；`bm25_temporal` 是可部署的 candidate + hard temporal filter baseline。

## 5. Development results

| method | Recall@5 | nDCG@5 | Complete@5 | FlowComplete@5 | edge recall | violation rate |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 0.3235 | 0.3413 | 0.0035 | 0.0035 | 0.0000 | 0.4321 |
| BM25 + temporal | 0.5262 | 0.5521 | 0.1007 | 0.0993 | 0.0000 | 0.0000 |
| v6 full | **0.5830** | **0.5977** | **0.1563** | **0.1514** | **0.2646** | 0.0000 |

## 6. Validation results

| method | Recall@5 | nDCG@5 | Complete@5 | FlowComplete@5 | edge recall | violation rate |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 0.4880 | 0.5031 | 0.0563 | 0.0563 | 0.0000 | 0.2562 |
| BM25 + temporal | 0.6292 | 0.6387 | 0.2000 | 0.2000 | 0.0000 | 0.0000 |
| v6 full | **0.6357** | **0.6460** | **0.2271** | **0.2208** | **0.3201** | 0.0000 |

v6 full 在 dev 和 validation 的四个 frozen primary metrics 上均优于 temporal baseline，但 validation 增益较小；第一阶段只主张可运行的结构化 baseline 和已观察到的增益，不主张已解决 flow retrieval。

## 7. Ablation

| method | dev Recall / FlowComplete | validation Recall / FlowComplete |
|---|---:|---:|
| v6 full | 0.5830 / 0.1514 | 0.6357 / 0.2208 |
| w/o temporal | 0.3589 / 0.0278 | 0.5360 / 0.0813 |
| w/o relation | 0.5425 / 0.0951 | 0.6338 / 0.2188 |
| w/o flow | 0.5262 / 0.0993 | 0.6292 / 0.2000 |

时间约束贡献最大；relation/flow 在 dev 提升明显，在 validation 的平均 Recall 增益有限，但产生了可评分 typed edges。

## 8. Failure analysis

validation 自动分类的主要失败为：flow search error 293、relation classification error 75、evidence redundancy 38、uncertainty handling error 21、procedure applicability retrieval error 20。代表 query IDs 保存在 `results/v6/stage1/failure_analysis_validation.json`。

## 9. Known limitations

- relation scorer 是规则/metadata baseline，尚未学习 query-conditioned relation likelihood；部分 taxonomy 关系混淆明显。
- greedy flow 容易被局部高分节点吸引，validation Hit@5 低于 temporal top-k，尽管 Recall/Complete 更高。
- BM25 缺少 dense semantic channel；paraphrase 与 cross-source role 对齐仍弱。
- `BENCHMARK_ISSUE_FOUND`：final-seal commit 中 `metadata/validation_second_blind_review.json` 实际 SHA256 为 `f219d3ebfe60782831c86f84c196a19df11aa3f88d9d28b4f52408158d1d1222`，manifest 声明为 `00dc11c5b178c4ba774194a59e563032199640be9e47fd35c3edf6c13e608046`。未修改 benchmark artifact 或 manifest。

## 10. Next-stage recommendation

1. 用 dev/validation flow edges 训练或校准 query-conditioned relation scorer，重点改善 `qualifies / governs / preserves_uncertainty`。
2. 用 beam search + explicit required-role hypotheses 替代单路径 greedy，保留高-relevance fallback 以恢复 Hit@5。
3. 加入本地 multilingual dense candidate channel，保持同一 deterministic temporal hard gate。
