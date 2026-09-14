"""Audit only the new synthetic dev dataset; no retrieval or model calls."""
import json
import sqlite3
import statistics
from collections import Counter
from temporal_maintenance_dataset_v2_lib import ROOT, read, read_lines, write, sha, audit, visible

DATA=ROOT/'data/generated/temporal_maintenance_dev_v2'
OUT=ROOT/'experiments/analyses/temporal_maintenance_dataset_v2'

def main():
    assets=read(DATA/'assets.json'); docs=read_lines(DATA/'evidence.jsonl')
    queries=read_lines(DATA/'queries.jsonl'); gold=read_lines(DATA/'evaluation/gold.jsonl'); chains=read_lines(DATA/'evaluation/chains.jsonl')
    summary=audit(assets,docs,queries,gold,chains)
    manifest=read(DATA/'manifest.json')
    assert all(sha(DATA/p)==h for p,h in manifest['output_hashes'].items())
    assert all(sha(p)==h for p,h in manifest['input_hashes'].items())
    db=sqlite3.connect(f'{(DATA/"store.sqlite").as_uri()}?mode=ro',uri=True)
    try:
        assert {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}=={'assets','evidence'}
        assert {r[0]:json.loads(r[1]) for r in db.execute('SELECT id,payload FROM evidence')}=={d['id']:d for d in docs}
    finally: db.close()
    counts=list(summary['target_chain_counts'].values()); delays=sorted(summary['ingestion_delay_minutes'])
    summary['chain_count_per_target']={'min':min(counts),'median':statistics.median(counts),'max':max(counts)}
    summary['delay_minutes_summary']={'median':statistics.median(delays),'p95':delays[round(.95*(len(delays)-1))],'max':max(delays),'over_60_minutes':sum(x>60 for x in delays)}
    summary['source_chain_counts']=dict(Counter(s for c in chains for s in c['source_ids']))
    summary['record_kind_counts']=dict(Counter(d['kind'] for d in docs))
    summary['archive_copies']=sum('origin_record_id' in d for d in docs)
    summary['exact_unique_record_texts']=len({d['text'] for d in docs})
    qs={q['query_id']:q for q in queries}; ds={d['id']:d for d in docs}
    summary['query_visibility']=[dict(query_id=q['query_id'],visible=sum(visible(d,q['query_time']) for d in docs),invisible=sum(not visible(d,q['query_time']) for d in docs)) for q in queries]
    summary['all_hashes_match']=True
    write(OUT/'statistics.json',summary)
    lines=['# 实际生成案例分层抽查包','', '每场景选1条实际扩展链；优先展示持续证据不足变体。以下是机器整理、供人工复核，不等于16条新增案例已获人工通过。所有时刻为UTC（Z）；查询文字明确UTC+8。','']
    for scenario in sorted(summary['scenario_counts']):
        choices=[c for c in chains if c['scenario']==scenario]
        c=sorted(choices,key=lambda c:(not c['persistent_unknown'],c['instance']))[0]
        lines.extend([f"## {scenario} · {c['theme']}",'',f"链：{c['chain_id']}；设备：{c['asset_id']}；持续不足：{c['persistent_unknown']}；来源：{', '.join(c['source_ids'])}",''])
        for d in sorted((ds[i] for i in c['record_ids']),key=lambda d:d['event_time']):
            lines.extend([f"- `{d['id']}`｜发生 {d['event_time']}｜入库 {d['available_at']}｜{d['text']}"])
        seen=set()
        for g in sorted((g for g in gold if g['chain_id']==c['chain_id']),key=lambda g:(g['task'],g['prototype_query'] or 0)):
            if g['intent_id'] in seen: continue
            seen.add(g['intent_id']); q=qs[g['query_id']]
            lines.extend(['',f"**{g['task']} 查询**：{q['text']}",'',f"参考回答：{g['reference_answer']}",'',f"允许替代：{g['acceptable_alternative']}",'',f"必要证据组：{json.dumps(g['required_evidence_groups'],ensure_ascii=False)}",''])
    (OUT/'实际扩展案例_16例.md').write_text('\n'.join(lines),encoding='utf-8')
    report=f'''# 时序运维合成开发集 v2：生成与质量报告

作者于2026-09-12批准阶段1小样的自然性与技术合理性，本阶段完成独立dev生成，不运行模型实验。

## 数据规模

{summary['targets']}台目标设备及48台专属邻机，{summary['chains']}条事件链，{summary['evidence']}条证据，{summary['queries']}个问题，对应{summary['intents']}个意图。每意图两种确定性表达，不应作为独立统计样本。每目标设备链数最小/中位/最大为{min(counts)}/{statistics.median(counts)}/{max(counts)}。

时序查询768条，普通记录查询384条；24条链在后期仍缺必要检查。归档副本{summary['archive_copies']}条，按等价证据组评价，不重复计分。16场景各12链是设计配额，不是真实发生率。普通日志也是合成背景。

事件时间跨度：{summary['first_event']}至{summary['last_event']}；最晚入库：{summary['latest_available']}。入库延迟中位数{statistics.median(delays):g}分钟，95%分位{summary['delay_minutes_summary']['p95']:g}分钟，最大{max(delays):g}分钟；超过1小时{summary['delay_minutes_summary']['over_60_minutes']}条。这些是合成时间分布，未经真实工单分布拟合。

## 检查及评价边界

全部查询与gold一一对应；必要证据均在查询时可见，不可见清单均不可见；两种改写共享意图；设备覆盖及非等量历史通过。数据输入/输出SHA-256一致，SQLite只有assets/evidence两表，逐行内容与公开证据一致。逐查询全库可见/不可见计数见statistics.json。

检索入口限定store.sqlite与queries.jsonl；evaluation仅供评测，不可用于构建索引、图、摘要或选参。程序分级相关性是初版标注；错误设备附件、旧规程可能用于解释错误或版本差异，不能仅凭ID认定回答错误。普通查询按全库目标设备最近业务记录标注。未来实验区间应至少按设备聚类，不能将同链改写当作独立样本。

## 真实性与来源

来源及适用边界保留在数据provenance.json和[阶段1资料来源](../../../plans/时序运维资料与案例设计_v1/资料来源与适用边界.md)，逐链source_ids可回溯。公开厂家资料和事故报告用于约束故障现象、检查证据与认知边界，不提供本合成集的真实发生频率。待核验来源不能作为已证实证据。C11/C12为合成资料核对规则，不是实际作业SOP。

本版为16个已审语义模板的参数化扩展：更换设备、人员、日期、工单编号，组合跨期记录、延迟信息和邻机干扰。三种记录风格只是有限包装，未采用自由生成，不代表丰富自然语言改写；独立文本{summary['exact_unique_record_texts']}条也不等于独立语义。未生成数值传感器轨迹，不声称数值分布、故障率或自然语言泛化已贴近现场。随机叠加多链后仍需人工检查可能的跨链冲突；机器一致性不能替代技术审核。

实际扩展案例_16例.md提供每场景一条实例，覆盖8类持续不足变体；这里的人工通过仅指原小样，不扩大到全部扩展行。源文件、旧数据和论文保持冻结；测试与冻结日志单独保留。

## 下一阶段

阶段3预登记时序专门方法与公平对照、排序及生成评价，再决定模型调用。该dev已用于设计，未来validation/test须独立新建。不能把本版重划为未见测试集。
'''
    (OUT/'report_zh.md').write_text(report,encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ('chains','evidence','queries','chain_count_per_target','delay_minutes_summary','all_hashes_match')},ensure_ascii=False))

if __name__=='__main__': main()
