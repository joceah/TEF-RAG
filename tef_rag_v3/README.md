# TEF-RAG v3：显式“旧状态—更新证据”关系

v2已经按关系类型选择`event_time`或`available_at`，但沿用`source/target`容易把语言中的施事方向与知识演化方向混在一起。例如“迟到频谱支持早期定位”常被抽成“频谱→定位”，而证据流需要表达“早期定位被后来可知的频谱更新”。

v3的首选关系格式为：

```json
{
  "prior_id": "early_localization",
  "update_id": "late_spectrum",
  "update_relation": "supports",
  "confidence": 0.9
}
```

`update_relation`始终说明`update_id`如何作用于`prior_id`，遍历固定为`prior_id → update_id`。过程关系`follows/verifies/resolves`仍用事件时间检查顺序；知识更新关系`supports/refutes/supersedes/same_process`用入库时间检查顺序。节点本身仍须通过查询截止时刻的双时间可见性过滤。

旧`source_id/target_id/relation`格式仅为读取既有实验而兼容。该版本是语义契约修正，不构成性能优势声明，尚未运行排名。
