# v4 第二轮修订核对

## 两份报告与上轮修改的核对结果

- 首次报告为 21%，第二次报告为 29%。高亮是检测工具对文本的标记，不是对作者来源的事实认定。
- 上一轮确实修改了首次报告未高亮的文字，范围过大。两个指定 skill 都实际读取并参考过，但“改得更简洁”不能推导出“检测值会降低”。上一轮没有将修改严格限定在高亮范围内。
- 第二份报告中，一些改写过的引言和方法接口段落新增了高亮；也有未作文字修改的内容新增高亮。例如 benchmark 末尾以 Public sources are used only 开头的段落，在上一轮前后相同，第二次却新增高亮。因此不能从这两次报告分离出全部 8 个百分点的原因。
- 第二份送检 PDF 出现多处 `[?]`、`??`，而第一次的相应引用已经解析。本文源文件中的引用键与参考文献未改动。重新编译时应运行到引用解析完成，再检查 PDF；不能据此断言引用未解析导致了检测分数变化。

| 内容 | 首次报告高亮情况 | 第二次报告变化 | 本轮处理 |
|---|---|---|---|
| 引言的相关方法、TEF-RAG 定位和生成接口 | 无高亮 | 上轮改写后的多处文字新增高亮（报告第 3 页） | 整个引言与相关工作恢复 v3 |
| 方法末尾的生成接口说明 | 无高亮 | 上轮改写后新增高亮（第 7 页） | 恢复 v3 |
| 附录 LLM/API 配置 | 无高亮 | 上轮改写后新增高亮（第 10 页） | 恢复 v3 |
| 附录规则评分 H 的开头说明 | 无高亮 | 上轮改写后新增高亮（第 11 页） | 恢复 v3 |
| 结果分析与局限 | 结果分析及局限无高亮，结尾 future work 句有高亮 | 上轮进行了额外润色 | 除 future work 一句外恢复 v3 |
| benchmark 末尾 Public sources 段 | 无高亮 | 文字未改但新增高亮（第 7 页） | 保留 v3 原文 |
| prompt 原文及 JSON 示例 | 两次均有部分高亮 | 高亮范围变化 | 仍逐字保留 |

## 本轮修改边界

本轮以 v3 源码为底稿，覆盖 v4 主文件和配套分节。只在第一次高亮范围涉及的叙述中进行局部修订；第二次新增高亮但首次未标记的段落以恢复 v3 为主，不再扩写。首尾只有部分文字被标记时，保留其余句子。专业词、关系名、指标名、公式、实验结果、表格及代码块不为检测而改动。

参考规则：[anti-defensive-writing](https://github.com/Kiterlin/anti-defensive-writing/blob/main/SKILL.md) 的局部修改、减少重复铺垫、保留必要限定；[academic-humanizer](https://github.com/AIScientists-Dev/academic-humanizer/blob/main/SKILL.md) 的中性学术表达、保留数据和引用、避免套话。没有随机换词、添加口语或改动数据。

本轮共 38 个局部替换点。下表中的页码均为首次报告的 PDF 页码（包括封面和概览）。

| # | 文件与行 | 首次报告页码 | 修改理由 |
|---|---|---|---|
| 1 | [02_problem_definition.tex:56](D:/TEF-RAG/paper/sections_en_v4/02_problem_definition.tex:56) | 5 | 保留大小约束，减少对 at most five 的重复解释 |
| 2 | [02_problem_definition.tex:58](D:/TEF-RAG/paper/sections_en_v4/02_problem_definition.tex:58) | 5 | 去除 not X / instead Y 式铺垫 |
| 3 | [02_problem_definition.tex:67](D:/TEF-RAG/paper/sections_en_v4/02_problem_definition.tex:67) | 5 | 公式后直接解释函数与候选空间 |
| 4 | [03_method_outline.tex:63](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:63) | 7 | 明确源、目标和关系，不重复 points to / through |
| 5 | [03_method_outline.tex:66](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:66) | 7 | 保留全部十类关系，简化结构说明 |
| 6 | [03_method_outline.tex:68](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:68) | 7 | 去除与静态图的重复对比；下一句合法性边界不动 |
| 7 | [03_method_outline.tex:78](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:78) | 7 | 用具体特征数量替代泛指引导 |
| 8 | [03_method_outline.tex:80](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:80) | 7 | 保留特征含义和列表结构 |
| 9 | [03_method_outline.tex:81](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:81) | 7 | 把压缩术语写清楚，保留时间概念 |
| 10 | [03_method_outline.tex:82](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:82) | 7 | 简化名词堆叠 |
| 11 | [03_method_outline.tex:83](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:83) | 7 | 明确 coverage 与 uncertainty 的对象 |
| 12 | [03_method_outline.tex:84](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:84) | 7 | 减少模板化 including 结构 |
| 13 | [03_method_outline.tex:85](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:85) | 7 | 交代特征来自哪一评分环节 |
| 14 | [03_method_outline.tex:87](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:87) | 7 | 用已列特征解释集合比较，去除笼统总结 |
| 15 | [03_method_outline.tex:100](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:100) | 7 | 减少 candidate set 的重复，保留正负样本定义 |
| 16 | [03_method_outline.tex:104](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:104) | 7 | 直接引出损失函数 |
| 17 | [03_method_outline.tex:116](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:116) | 7 | 简洁交代优化目标 |
| 18 | [03_method_outline.tex:125](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:125) | 7 | 避免重复定义 |
| 19 | [03_method_outline.tex:128](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:128) | 7 | 以负样本选择的实际机制组织段落，保留评分项及多样性采样 |
| 20 | [03_method_outline.tex:130](D:/TEF-RAG/paper/sections_en_v4/03_method_outline.tex:130) | 7 | 修复 rescoring 语法问题，减少反复解释 hard negatives |
| 21 | [04_benchmark.tex:10](D:/TEF-RAG/paper/sections_en_v4/04_benchmark.tex:10) | 8 | 仅改首次高亮部分；保留该段前两句数据来源及 AI 辅助声明 |
| 22 | [04_benchmark.tex:12](D:/TEF-RAG/paper/sections_en_v4/04_benchmark.tex:12) | 8 | 保留构造层级与两个参考对象，减少流水式 first / then 叙述 |
| 23 | [04_benchmark.tex:22](D:/TEF-RAG/paper/sections_en_v4/04_benchmark.tex:22) | 8 | 保留 chain / evidence / intent / query 层级 |
| 24 | [04_benchmark.tex:24](D:/TEF-RAG/paper/sections_en_v4/04_benchmark.tex:24) | 8 | 说明等价证据如何评价，去除否定后转折 |
| 25 | [04_benchmark.tex:44](D:/TEF-RAG/paper/sections_en_v4/04_benchmark.tex:44) | 8 | 只修改高亮的规模句；后面的按链划分说明不动 |
| 26 | [04_benchmark.tex:70](D:/TEF-RAG/paper/sections_en_v4/04_benchmark.tex:70) | 8 | 保留检查方法与生成参考的对应关系 |
| 27 | [04_benchmark.tex:72](D:/TEF-RAG/paper/sections_en_v4/04_benchmark.tex:72) | 8 | 保留所有数量及其对应 split；后面的输出结构说明不动 |
| 28 | [05_remaining_outline.tex:121](D:/TEF-RAG/paper/sections_en_v4/05_remaining_outline.tex:121) | 11 | 仅改首次高亮的最后一句；其余结果、局限和结论恢复 v3 |
| 29 | [07_appendix.tex:50](D:/TEF-RAG/paper/sections_en_v4/07_appendix.tex:50) | 12 | 只解释常数项，不改公式或前面的参数说明 |
| 30 | [07_appendix.tex:80](D:/TEF-RAG/paper/sections_en_v4/07_appendix.tex:80) | 12 | 仅改首次高亮的第二轮说明 |
| 31 | [07_appendix.tex:85](D:/TEF-RAG/paper/sections_en_v4/07_appendix.tex:85) | 12 | 只改 prompt 外说明 |
| 32 | [07_appendix.tex:140](D:/TEF-RAG/paper/sections_en_v4/07_appendix.tex:140) | 13 | 只改 JSON 示例前的说明 |
| 33 | [07_appendix.tex:161](D:/TEF-RAG/paper/sections_en_v4/07_appendix.tex:161) | 13 | 只改 prompt 前说明 |
| 34 | [07_appendix.tex:205](D:/TEF-RAG/paper/sections_en_v4/07_appendix.tex:205) | 13 | 只改请求结构说明 |
| 35 | [07_appendix.tex:216](D:/TEF-RAG/paper/sections_en_v4/07_appendix.tex:216) | 13 | 保留一次修复与触发条件 |
| 36 | [07_appendix.tex:223](D:/TEF-RAG/paper/sections_en_v4/07_appendix.tex:223) | 13 | 保留修复请求的所有约束 |
| 37 | [TEF_RAG_ICRA_style_en_v4.tex:50](D:/TEF-RAG/paper/TEF_RAG_ICRA_style_en_v4.tex:50) | 3 | 只改高亮的背景句，说明记录在维护流程中的具体作用 |
| 38 | [TEF_RAG_ICRA_style_en_v4.tex:53](D:/TEF-RAG/paper/TEF_RAG_ICRA_style_en_v4.tex:53) | 3 | 只改高亮的双约束句；其余摘要恢复 v3 |

## 已做的验证

- 18 个 equation 环境、1 个 align 环境、6 个表格、5 个 lstlisting 块与 v3 原文一致。
- 引用键、交叉引用、标签、图像路径与 v3 一致；参考文献文件逐字一致。
- 全部实验数值和参数保持不变。特征数量 62 只增加了一次文字重复说明，数值本身未改。
- 引言和相关工作分节文件与 v3 字节一致。所有 v4 输入路径指向独立的 sections_en_v4。
- 已检查花括号和环境配对，未编译，未重新运行 AI 检测，不能声称新分数已降低。

覆盖前的 v4 副本保存在 tmp/v4_second_pass/before_second_revision，可用于比较第二份报告所对应的文字。
