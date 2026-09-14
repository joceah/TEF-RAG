"""Generate isolated dev material from author-approved semantic prototypes.

This module never imports the old generator or retrieval code. Review-only labels
are projected into a separate evaluation directory, never the retrieval store.
"""
from __future__ import annotations
import hashlib
import json
import random
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = timezone(timedelta(hours=8))
DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')
EVIDENCE_FIELDS = {'id','kind','asset_id','event_time','available_at','text','is_synthetic',
                   'author_id','work_order_ids','valid_from','valid_to','model_scope','origin_record_id'}
KINDS = {'C01':'battery','C02':'battery','C03':'battery','C04':'battery','C05':'battery','C13':'battery',
         'C06':'inverter','C07':'inverter','C08':'inverter','C10':'inverter','C14':'inverter','C15':'inverter',
         'C09':'cabinet','C11':'cabinet','C12':'cabinet','C16':'cabinet'}

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def write_lines(path, rows):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')

def read_lines(path):
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8-sig').splitlines() if s.strip()]

def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''): digest.update(block)
    return digest.hexdigest()

def dt(value):
    return datetime.fromisoformat(value.replace('Z','+00:00'))

def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')

def visible(d, cutoff):
    return d['event_time']<=cutoff and d['available_at']<=cutoff

def ident(rng,prefix):
    return prefix+'-'+f'{rng.getrandbits(96):024x}'

class Transform:
    def __init__(self,case,rng,asset,neighbor):
        texts=[r[3] for r in case['records']]+[q[k] for q in case['queries'] for k in ('text','answer','alternative')]
        dates=sorted(set(DATE_RE.findall(' '.join(texts))) | {r[j][:10] for r in case['records'] for j in (1,2)} | {q['at'][:10] for q in case['queries']})
        day=datetime(2025,1,1)+timedelta(days=rng.randrange(330))
        self.dates={dates[0]:day.strftime('%Y-%m-%d')}
        for old,new in zip(dates,dates[1:]):
            gap=(datetime.fromisoformat(new)-datetime.fromisoformat(old)).days
            day+=timedelta(days=gap if gap<=2 else max(3,round(gap*rng.uniform(.65,1.35))))
            self.dates[new]=day.strftime('%Y-%m-%d')
        self.mapping={}
        assets=re.findall(r'SIM-[A-Z]+\d+',case['asset'])
        for i,old in enumerate(assets):
            replacement=asset['asset_id'] if i==0 else neighbor['asset_id']
            self.mapping[old]=replacement; self.mapping[old.removeprefix('SIM-')]=replacement
        for old in sorted(set(re.findall(r'WO-\d+|P-[AB]-v[12]',' '.join(texts)))):
            if old.startswith('WO'): self.mapping[old]='WO-'+str(rng.randrange(100000,999999))
        family='P-'+str(rng.randrange(100000,999999))
        for code in ('P-A-v1','P-A-v2','P-B-v1'): self.mapping[code]=code.replace('P-',family+'-')
        authors=rng.sample([f'记录员M{i:02d}' for i in range(1,13)],3)
        self.mapping.update(dict(zip(('人员甲','人员乙','人员丙'),authors)))
        self.mapping.update(dict(zip(('值班员甲','值班员乙','值班员丙'),authors)))

    def time(self,value):
        changed=self.dates[value[:10]]+value[10:]
        return iso(datetime.fromisoformat(changed).replace(tzinfo=LOCAL))

    def text(self,value):
        # One pass prevents replacement output from being transformed a second time.
        value=re.sub('|'.join(re.escape(k) for k in sorted(self.mapping,key=len,reverse=True)),lambda m:self.mapping[m[0]],value)
        value=DATE_RE.sub(lambda m:self.dates[m[0]],value)
        monthdays={f'{int(old[5:7])}月{int(old[8:10])}日':f'{int(new[5:7])}月{int(new[8:10])}日' for old,new in self.dates.items()}
        if monthdays: value=re.sub('|'.join(re.escape(k) for k in monthdays),lambda m:monthdays[m[0]],value)
        return value

def style_text(text,style):
    if style=='terse': return text
    if style=='standard': return '本次记录：'+text
    return '交接说明：'+text+' 请结合所附记录核对。'

def scenario_pool(case,assets):
    pool=[a for a in assets if a['role']=='target' and a['kind']==KINDS[case['id']]]
    if case['id']=='C11': pool=[a for a in pool if a['model_scope']=='配置A']
    if case['id']=='C12': pool=[a for a in pool if a['model_scope']=='配置B']
    return pool

def make_assets(config):
    assets=[]
    for kind,count in config['targets_per_kind'].items():
        code={'battery':'BAT','inverter':'PCS','cabinet':'CAB'}[kind]
        for i in range(count):
            key=f'SYN-{code}-{i+1:03d}'
            model=('配置A' if i%2==0 else '配置B') if kind=='cabinet' else '合成-'+code
            for role,suffix in [('target',''),('context','-N')]:
                assets.append(dict(asset_id=key+suffix,kind=kind,role=role,model_scope=model,
                                   site_id=f'SYN-S{i%3+1:02d}',split_group=key,is_synthetic=True))
    return assets

def generate(config, prototypes):
    rng=random.Random(config['seed']); assets=make_assets(config)
    lookup={a['asset_id']:a for a in assets}; docs=[]; chains=[]; pending=[]
    coverage=Counter(); used_business_ids=set()
    for case in prototypes['cases']:
        for instance in range(config['instances_per_scenario']):
            pool=scenario_pool(case,assets)
            # Prefer unused assets, then unrestricted assignment yields unequal histories.
            unused=[a for a in pool if coverage[a['asset_id']]==0]
            asset=rng.choice(unused or pool); coverage[asset['asset_id']]+=1
            neighbor=lookup[asset['asset_id']+'-N']; tr=Transform(case,rng,asset,neighbor)
            # Collision checks keep independently sampled business identities separate.
            while used_business_ids & set(tr.mapping.get(k) for k in tr.mapping if k.startswith(('WO-','P-'))):
                tr=Transform(case,rng,asset,neighbor)
            used_business_ids.update(tr.mapping[k] for k in tr.mapping if k.startswith(('WO-','P-')))
            chain_id=ident(rng,'chain'); ids={r[0]:ident(rng,'doc') for r in case['records']}
            cutoffs=[tr.time(q['at']) for q in case['queries']]
            persistent=case['id'] in config['persistent_unknown_scenarios'] and instance in config['persistent_unknown_instances']
            local=[]; styles={}; copies={}
            for key,event,available,raw in case['records']:
                text=tr.text(raw)
                text=re.sub(r'\br\d+\b',lambda m:ids.get(m[0],m[0]),text)
                style=rng.choice(('terse','standard','conversational')); author=f'M{rng.randrange(1,13):02d}'
                record=dict(id=ids[key],asset_id=asset['asset_id'],event_time=tr.time(event),available_at=tr.time(available),
                            text=style_text(text,style),kind='procedure' if '合成试验规程' in raw else 'maintenance_record',
                            author_id=author,is_synthetic=True)
                names=re.findall(r'记录员(M\d+)',text)
                if names: record['author_id']=names[0]
                if 'WO-' in text: record['work_order_ids']=sorted(set(re.findall(r'WO-\d+',text)))
                if record['kind']=='procedure':
                    record['model_scope']='配置B' if 'P-B' in raw else '配置A'
                    if case['id']=='C11':
                        record['valid_from']=tr.time('2026-01-01 00:00' if key=='r1' else '2026-07-01 00:00')
                        record['valid_to']=tr.time('2026-07-01 00:00') if key=='r1' else None
                    else:
                        record['valid_from']=tr.time('2026-01-10 00:00' if key=='r1' else '2026-07-01 00:00')
                        record['valid_to']=None
                if persistent and not visible(record,cutoffs[0]):
                    record['available_at']=max(record['available_at'],iso(dt(cutoffs[1])+timedelta(days=rng.randrange(7,31))))
                local.append(record); styles[record['id']]=style
            if instance%3==0:
                origin=rng.choice([d for d in local if d['kind']!='procedure'])
                duplicate=dict(origin,id=ident(rng,'doc'),origin_record_id=origin['id'],text='归档副本：'+origin['text'],
                               available_at=iso(dt(origin['available_at'])+timedelta(minutes=5)))
                local.append(duplicate); copies[origin['id']]=duplicate['id']; styles[duplicate['id']]='archive_copy'
            for j in range(rng.randint(config['background_records_min'],config['background_records_max'])):
                event=iso(dt(cutoffs[0])-timedelta(days=j+1,hours=rng.randrange(1,6)))
                record=dict(id=ident(rng,'doc'),kind='routine_log',asset_id=asset['asset_id'],event_time=event,
                            available_at=iso(dt(event)+timedelta(minutes=rng.randrange(5,60))),author_id=f'M{rng.randrange(1,13):02d}',
                            text=f"{asset['asset_id']} 班次记录：设备号已核对，原始读数文件已归档；本条未记录技术诊断。",is_synthetic=True)
                local.append(record); styles[record['id']]='routine'
            event=iso(dt(cutoffs[0])-timedelta(hours=2))
            symptom={'battery':'电压或控制状态异常提示','inverter':'温度或监测异常提示','cabinet':'监测或资料状态异常提示'}[asset['kind']]
            distraction=dict(id=ident(rng,'doc'),kind='maintenance_record',asset_id=neighbor['asset_id'],event_time=event,
                             available_at=iso(dt(event)+timedelta(minutes=20)),author_id=f'M{rng.randrange(1,13):02d}',
                             text=f"{neighbor['asset_id']} 值班记录：运行显示{symptom}，具体类别待核对；此记录属于本设备。",is_synthetic=True)
            local.append(distraction); styles[distraction['id']]='terse'
            chains.append(dict(chain_id=chain_id,scenario=case['id'],theme=case['theme'],prototype_difficulty=case['difficulty'],
                               asset_id=asset['asset_id'],neighbor_asset_id=neighbor['asset_id'],split_group=asset['split_group'],
                               source_ids=case['sources'],persistent_unknown=persistent,record_ids=[d['id'] for d in local],
                               styles=styles,instance=instance,cutoffs=cutoffs,date_mapping=tr.dates))
            docs.extend(local)
            for qi,original in enumerate(case['queries']):
                q=case['queries'][0] if persistent and qi==1 else original
                intent_id=ident(rng,'intent'); cutoff=cutoffs[qi]
                query_text=tr.text(q['text'])
                if persistent and qi==1:
                    query_text='截至本次资料截止时刻，这项异常目前可以确认什么、仍不能确认什么？请说明所需的补充依据。'
                first_observation=min(d['event_time'] for d in local if d['id'] in ids.values() and d['kind']!='procedure')
                anchor=dt(first_observation).astimezone(LOCAL).strftime('%Y年%m月%d日 %H:%M')
                query_text=f'关注始于{anchor}（UTC+8）的记录事项。'+query_text
                groups=[]
                for key in q['required']:
                    group=[ids[key]]
                    if ids[key] in copies and visible(next(d for d in local if d['id']==copies[ids[key]]),cutoff): group.append(copies[ids[key]])
                    groups.append(group)
                required={x for g in groups for x in g}
                grades={d['id']:(3 if d['id'] in required else 2 if d['id'] in ids.values() else 1)
                        for d in local if visible(d,cutoff) and d['asset_id']==asset['asset_id']}
                pending.append(dict(intent_id=intent_id,chain_id=chain_id,asset_id=asset['asset_id'],cutoff=cutoff,text=query_text,
                                    task='temporal',reference=tr.text(q['answer']),alternative=tr.text(q['alternative']),
                                    required_evidence_groups=groups,grades=grades,
                                    unavailable_ids=[d['id'] for d in local if not visible(d,cutoff)],
                                    inapplicable_as_current=[ids[k] for k in q.get('inapplicable',[])],
                                    persistent_unknown=persistent,prototype_query=qi+1))
    assert len(coverage)==sum(config['targets_per_kind'].values()), 'all targets must be covered'
    # Ordinary queries deliberately consult all of the target's visible records.
    by_asset={a['asset_id']:[d for d in docs if d['asset_id']==a['asset_id']] for a in assets if a['role']=='target'}
    for chain in chains:
        cutoff=chain['cutoffs'][1]; candidates=[d for d in by_asset[chain['asset_id']] if visible(d,cutoff) and d['kind']!='procedure' and not d.get('origin_record_id')]
        latest=max(d['event_time'] for d in candidates); hits=[d for d in candidates if d['event_time']==latest]
        groups=[[d['id']]+[copy['id'] for copy in by_asset[chain['asset_id']] if copy.get('origin_record_id')==d['id'] and visible(copy,cutoff)] for d in hits]
        pending.append(dict(intent_id=ident(rng,'intent'),chain_id=chain['chain_id'],asset_id=chain['asset_id'],cutoff=cutoff,
                            text='按发生或形成时间，目标设备最近一条已入库业务记录写了什么？若时间并列，请分别列出，附记录时间和引用。',
                            task='ordinary',reference='；'.join(d['text'] for d in hits),alternative='允许保留相同事实的简明转述，不扩展技术诊断。',
                            required_evidence_groups=groups,grades={i:3 for group in groups for i in group},unavailable_ids=[],
                            inapplicable_as_current=[],persistent_unknown=False,prototype_query=None))
    queries=[]; gold=[]
    for p in pending:
        when=dt(p['cutoff']).astimezone(LOCAL).strftime('%Y年%m月%d日 %H:%M（UTC+8）')
        for variant in range(2):
            query_id=ident(rng,'query')
            text=(f"目标设备{p['asset_id']}，资料截止{when}。"+p['text'] if variant==0 else
                  p['text']+f" 请以{p['asset_id']}为对象，只依据截至{when}已知的资料说明，并列出依据。")
            queries.append(dict(query_id=query_id,text=text,asset_id=p['asset_id'],query_time=p['cutoff'],split='dev'))
            gold.append(dict(query_id=query_id,intent_id=p['intent_id'],chain_id=p['chain_id'],task=p['task'],
                             reference_answer=p['reference'],acceptable_alternative=p['alternative'],
                             required_evidence_groups=p['required_evidence_groups'],
                             relevance_judgments=[dict(evidence_id=k,grade=v) for k,v in sorted(p['grades'].items())],
                             local_unavailable_evidence_ids=p['unavailable_ids'],inapplicable_as_current=p['inapplicable_as_current'],
                             persistent_unknown=p['persistent_unknown'],prototype_query=p['prototype_query'],
                             annotation_status='programmatic_expansion_of_author_approved_prototypes',
                             unavailable_rule='event_time > query_time OR available_at > query_time applies corpus-wide',
                             equivalence_policy='one member per necessary group; copies must not be double-counted'))
    rng.shuffle(docs); rng.shuffle(queries); rng.shuffle(gold); rng.shuffle(chains)
    return assets,docs,queries,gold,chains

def audit(assets,docs,queries,gold,chains):
    lookup={d['id']:d for d in docs}; qs={q['query_id']:q for q in queries}; gs={g['query_id']:g for g in gold}
    assert len(lookup)==len(docs) and len(qs)==len(queries) and len(gs)==len(gold) and qs.keys()==gs.keys()
    assert all(set(d)<=EVIDENCE_FIELDS for d in docs)
    assert all(d['event_time']<=d['available_at'] for d in docs)
    assert all(q['split']=='dev' and set(q)=={'query_id','text','asset_id','query_time','split'} for q in queries)
    for g in gold:
        cutoff=qs[g['query_id']]['query_time']
        for group in g['required_evidence_groups']:
            assert group and len(group)==len(set(group))
            assert all(i in lookup and visible(lookup[i],cutoff) for i in group)
        assert all(not visible(lookup[i],cutoff) for i in g['local_unavailable_evidence_ids'])
        assert all(visible(lookup[i],cutoff) for i in g['inapplicable_as_current'])
        assert all(visible(lookup[j['evidence_id']],cutoff) and j['grade'] in (1,2,3) for j in g['relevance_judgments'])
    assert all(len(v)==2 for v in _groups(gold,'intent_id').values())
    return dict(assets=len(assets),targets=sum(a['role']=='target' for a in assets),context_assets=sum(a['role']=='context' for a in assets),
                chains=len(chains),evidence=len(docs),queries=len(queries),intents=len(_groups(gold,'intent_id')),
                persistent_unknown_chains=sum(c['persistent_unknown'] for c in chains),
                target_chain_counts=dict(sorted(Counter(c['asset_id'] for c in chains).items())),
                scenario_counts=dict(sorted(Counter(c['scenario'] for c in chains).items())),
                task_query_counts=dict(Counter(g['task'] for g in gold)),
                style_counts=dict(Counter(s for c in chains for s in c['styles'].values())),
                evidence_per_chain=[len(c['record_ids']) for c in chains],
                ingestion_delay_minutes=[(dt(d['available_at'])-dt(d['event_time'])).total_seconds()/60 for d in docs],
                first_event=min(d['event_time'] for d in docs),last_event=max(d['event_time'] for d in docs),
                latest_available=max(d['available_at'] for d in docs),checks_passed=True)

def _groups(rows,key):
    groups={}
    for row in rows: groups.setdefault(row[key],[]).append(row)
    return groups

def build(output,config,config_path=None):
    output=Path(output)
    if output.exists() and any(output.iterdir()): raise FileExistsError(f'Refusing non-empty output: {output}')
    prototypes=read(ROOT/config['scenario_review_path'])
    assets,docs,queries,gold,chains=generate(config,prototypes)
    summary=audit(assets,docs,queries,gold,chains)
    output.mkdir(parents=True,exist_ok=True)
    write(output/'assets.json',assets)
    write_lines(output/'evidence.jsonl',docs); write_lines(output/'queries.jsonl',queries)
    write_lines(output/'evaluation/gold.jsonl',gold); write_lines(output/'evaluation/chains.jsonl',chains)
    write(output/'evaluation/split_groups.json',{a['asset_id']:[a['asset_id'],a['asset_id']+'-N'] for a in assets if a['role']=='target'})
    with sqlite3.connect(output/'store.sqlite') as db:
        db.executescript('CREATE TABLE assets(asset_id TEXT PRIMARY KEY,payload TEXT); CREATE TABLE evidence(id TEXT PRIMARY KEY,asset_id TEXT,event_time TEXT,available_at TEXT,kind TEXT,payload TEXT); CREATE INDEX evidence_visible ON evidence(asset_id,available_at);')
        for a in assets:
            payload={k:v for k,v in a.items() if k not in ('role','split_group')}
            db.execute('INSERT INTO assets VALUES(?,?)',(a['asset_id'],json.dumps(payload,ensure_ascii=False)))
        for d in docs: db.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?)',(d['id'],d['asset_id'],d['event_time'],d['available_at'],d['kind'],json.dumps(d,ensure_ascii=False)))
    db.close()
    write(output/'summary.json',summary)
    write(output/'provenance.json',dict(sources=prototypes['sources'],author_approval=config['author_approval'],
                                      expanded_rows_human_reviewed=False,field_data=False,model_calls=0))
    (output/'README.md').write_text(f"# 时序运维合成开发集 v2\n\n{summary['chains']}条链，{summary['evidence']}条证据，{summary['queries']}条dev问题（{summary['intents']}意图，每意图2种表达）。48台目标设备及48台上下文邻机。\n\n源资料支撑的16个小样已获作者自然性与技术合理性认可；扩展行尚未逐条人工审核，不是专家数据或真实工单。人员、设备和时间变化为参数化合成，不支持自然语言泛化或真实故障率结论。\n\n检索只读取store.sqlite的assets/evidence及queries.jsonl；evaluation目录仅供评测，禁止用于索引、摘要、图、路由和参数选择。可见性与规程适用性分别判断；误挂设备附件按引用用途评价。\n\n普通记录查询占三分之一；24条链在后期仍缺必要检查。仅dev，未来测试须另建独立数据，不能把已见链重新划作test。\n\nC11/C12只含合成资料核对规定，不是厂家SOP或现场安全操作要求；无SOH/RUL、视觉多模态或机器人闭环验证。\n",encoding='utf-8')
    inputs=[Path(__file__),ROOT/config['scenario_review_path'],ROOT/'plans/时序运维数据v2生成协议.md']
    if config_path: inputs.append(Path(config_path))
    inputs.append(ROOT/'scripts/build_temporal_maintenance_dev_v2.py')
    write(output/'manifest.json',dict(dataset_id=config['dataset_id'],counts={k:summary[k] for k in ('assets','targets','chains','evidence','queries','intents')},
                                    input_hashes={str(p.resolve()):sha(p) for p in inputs},
                                    output_hashes={str(p.relative_to(output)):sha(p) for p in sorted(output.rglob('*')) if p.is_file()},
                                    gold_isolation='evaluation files excluded from retrieval SQLite',split='dev'))
    return summary
