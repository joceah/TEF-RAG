# TEF-RAG v1 开发原型

TemporalEvidenceFlowRetrieverV1(records, assets, relations).retrieve(query, relevance, relation_scores=None) 先复用v3的公开范围与可见性约束，再从公开关系投影形成的时间有向图中搜索证据路径。

- 内置关系置信度只是确定性参考；relation_scores 是后续轻量pair scorer的接口。
- 不可见端点、未知关系和时间倒流边不进入图。
- 没有可用关系时回退到共享scoped_hybrid；“最新记录”任务使用共享倒序控制。
- 包不读文件、gold、模型凭据或隐藏事件图，也不在内部调用LLM。
- 当前只完成算法与隔离契约，现有v3开发集上的烟测没有显示排序优势。

完整研究规格见 plans/TEF_RAG_v1_method_spec.md。
