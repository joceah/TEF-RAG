# TEF-RAG v5 集合选择机制烟测 v1

本烟测在 `plans/TEF_RAG_v5集合级选择预登记_v1.md` 完成后执行，只验证实现契约，不读取 gold，不计算 Recall/nDCG，不运行 v8、旧98题或任何外部基线。

## 结果

- 4条内存合成记录、2条公开 prior→update 关系、Top-3；实际选择为 `verification, action, observation`。
- trace恰好3步，与实际`evidence_ids`逐项一致；每条当步激活边的prior/update端点都已存在于该步`set_after`。
- `verifies`链在第二个端点实际入选后才产生正向链边际收益；重复观察记录未挤掉所需验证角色。
- 9项v5单元测试全部通过，覆盖查询条件化、角色边际收益、冗余、方向链、Top-k末槽、trace、可见性、字符预算、确定性和profile驱动的latest控制。
- LLM调用0次，token usage为0；没有密钥读取或输出。

## 失败尝试留痕

测试先于实现创建，首次运行因v5类尚不存在而在导入阶段失败，符合测试先行顺序。实现后的第一次运行通过8/9项；唯一失败的集合成员是正确的，但测试夹具把返回顺序写死为semantic anchor优先，同时profile却给verification更高需求。随后只把该契约中的两个角色需求改为等权，使其真正模拟“anchor先占一槽、末端更新竞争最后一槽”；没有修改预登记目标权重、beam、算法或生产输入。

## 结论边界

本结果仅支持H1-H5在最小合成条件下按代码契约实现。它不证明v5优于scoped Hybrid、TA-RAG或TG-RAG，也不支持论文创新声明。新holdout尚未生成；若继续，必须先生成约4个全新案例、只做结构和人工可读审查，待用户确认后再冻结与排名。
