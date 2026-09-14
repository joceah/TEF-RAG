# TEF-RAG v5 holdout v2：生成接口修正

登记时间：2026-09-14，早于v2任何模型调用。

v1生成接口已失败并保留在`experiments/runs/tef_v5_holdout_v1_generation`。原因是基础提示中的旧`source/target/relation`结构与追加的`prior/update/update_relation`结构冲突，而且预登记必需边没有进入实际用户payload。主输出和一次修复都把自然语言关系说明写进`update_relation`枚举，确定性校验拒绝；未生成数据、未运行排名。两次响应共13478 tokens。

v2只修正生成接口，不改变科学内容：

- 完整复用v1在调用前固定的四个案例、48条记录角色、16题、query/gold必要组、时间表、工单范围和必需关系边；
- 使用一个无旧字段冲突的完整system prompt；
- 明确`update_relation`只能是`supports/refutes/verifies/resolves/supersedes/follows`之一；
- 在system prompt中逐案列出v1已经固定的必需边，弥补旧基础builder没有传递该字段的接口遗漏；
- 仍然每案只生成一个候选，确定性校验失败时最多一次修复；不根据任何检索结果修改或挑选案例。

新输出路径为`data/generated/tef_v5_holdout_v2`，新运行路径为`experiments/runs/tef_v5_holdout_v2_generation`。v1缓存与失败记录保持原样。
