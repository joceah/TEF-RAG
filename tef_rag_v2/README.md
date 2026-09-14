# TEF-RAG v2：关系类型决定时间时钟

v1把所有关系都按`event_time`定向，无法表达“报告描述较早事件、但较晚入库后更新当前判断”。v2保留v1的共享范围过滤、关系权重、beam search和回退逻辑，只修正边的时间语义：

- `follows`、`verifies`、`resolves`是业务过程边，要求目标`event_time`不早于来源；
- `supports`、`refutes`、`supersedes`、`same_process`是认知/主张关系，要求目标`available_at`不早于来源；
- 节点仍必须同时满足`event_time <= query_time`和`available_at <= query_time`，因此改变边时钟不会引入未来证据；
- 被拒边明确记录`clock`和原因，不自动反转。

该修正不是按gold调权重：问题是在候选数据生成的确定性时间审查中、任何排名运行之前发现。v1负面烟测继续保留，v2尚未跑检索成绩。
