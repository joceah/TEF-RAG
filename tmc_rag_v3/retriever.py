"""Development retriever: explicit scope, historical use and relevance-led selection."""
import re,calendar
from datetime import datetime,timedelta,timezone

UTC=timezone.utc
def dt(s):return datetime.fromisoformat(s.replace('Z','+00:00'))
def iso(t):return t.astimezone(UTC).isoformat(timespec='seconds').replace('+00:00','Z')
def visible(d,q):return d['event_time']<=q['query_time'] and d['available_at']<=q['query_time']
MONTHS={'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,'十一':11,'十二':12}

def parse_query(q):
    text=q['text'];cutoff=dt(q['query_time']);assumptions=[]
    # Remove only an explicitly labelled metadata cutoff, not historical questions.
    core=re.sub(r'资料(?:截止|截至)(?:时间)?\s*[:=：]?\s*\d{4}-\d{2}-\d{2}(?:T[\d:]+Z)?[；。]?','',text)
    orders=sorted(set(re.findall(r'WO-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*',core)))
    offset=re.search(r'UTC([+-]\d{1,2})',text)
    zone=timezone(timedelta(hours=int(offset[1]))) if offset else UTC
    year=cutoff.astimezone(zone).year;month=None;dates=[];windows=[]
    for m in re.finditer(r'(?:(\d{4})年)?(?:(\d{1,2})月)?(\d{1,2})日',core):
        y,mo,day=m.groups()
        if y:year=int(y)
        elif not dates:assumptions.append('year_from_query_cutoff')
        month=int(mo) if mo else month
        if month is None:continue
        dates.append(datetime(year,month,int(day),tzinfo=zone))
    for m in re.finditer(r'(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)',core):
        dates.append(datetime(*map(int,m.groups()),tzinfo=zone))
    if dates:
        if len(dates)>=2 and re.search(r'至|到|之间',core):windows=[(min(dates),max(dates)+timedelta(days=1))]
        elif len(dates)==1 and re.search(r'开始|始于|起至今|以来',core):windows=[(dates[0],cutoff+timedelta(seconds=1))]
        else:windows=[(d,d+timedelta(days=1)) for d in dates]
    else:
        for m in re.finditer(r'(?:(\d{4})年)?(十二|十一|十|[一二三四五六七八九]|\d{1,2})月(上旬|中旬|下旬)?',core):
            y,mo,part=m.groups();y=int(y) if y else cutoff.astimezone(zone).year
            if not m[1]:assumptions.append('year_from_query_cutoff')
            mo=int(mo) if mo.isdigit() else MONTHS[mo]
            first=1 if part!='中旬' and part!='下旬' else 11 if part=='中旬' else 21
            last=10 if part=='上旬' else 20 if part=='中旬' else calendar.monthrange(y,mo)[1]
            windows.append((datetime(y,mo,first,tzinfo=zone),datetime(y,mo,last,tzinfo=zone)+timedelta(days=1)))
        if len(windows)>=2 and re.search(r'至|到|之间',core):windows=[(min(a for a,b in windows),max(b for a,b in windows))]
    procedure=bool(re.search(r'规程|规定|版本|表单要求|归档要求',core))
    compare=bool(re.search(r'对比|比较|变化|两版|旧版.*新版|前后|两次|分别|与.*(?:不同|相同)',core))
    latest=bool(re.search(r'最新(?:一条)?(?:业务)?记录|最近(?:一条)?(?:业务)?记录|最后一条(?:业务)?记录',core)) and not orders and not windows and not procedure
    wanted=[]
    if re.search(r'检查|诊断|原因|排除|定位',core):wanted.append('check')
    if re.search(r'恢复|复测|完成依据|完成证据|正常间隔',core):wanted.append('recovery')
    if re.search(r'经过|过程|两次|前后',core):wanted.append('observation')
    return dict(orders=orders,windows=[(iso(a),iso(b)) for a,b in windows],procedure=procedure,compare=compare,latest=latest,wanted_roles=wanted,assumptions=sorted(set(assumptions)))

def role_group(role):
    if role in ('inspection','diagnosis','correction'):return 'check'
    if role in ('recovery','retest'):return 'recovery'
    return role

class TMCRetrieverV3:
    def __init__(self,records,assets,roles,top_k=10,budget=16000):
        self.records=list(records);self.assets={a['asset_id']:a for a in assets};self.roles=roles;self.top_k=top_k;self.budget=budget
    def current_applicable(self,d,q):
        return d.get('model_scope')==self.assets[q['asset_id']]['model_scope'] and d.get('valid_from','')<=q['query_time'] and (not d.get('valid_to') or q['query_time']<d['valid_to'])
    def scope(self,q):
        p=parse_query(q);candidates=[]
        for d in self.records:
            if not visible(d,q) or d['asset_id']!=q['asset_id']:continue
            if p['latest']:
                if d['kind']!='procedure':candidates.append(d)
                continue
            if d['kind']=='procedure':
                if not p['procedure'] or d.get('model_scope')!=self.assets[q['asset_id']]['model_scope']:continue
                if p['windows']:
                    if not any(d.get('valid_from','')<b and (not d.get('valid_to') or a<d['valid_to']) for a,b in p['windows']):continue
                elif not p['compare'] and not self.current_applicable(d,q):continue
            else:
                if p['orders'] and not set(p['orders'])&set(d.get('work_order_ids',[])):continue
                if p['windows'] and not any(a<=d['event_time']<b for a,b in p['windows']):continue
            candidates.append(d)
        return p,candidates
    def retrieve(self,q,relevance,mode='full'):
        if mode not in ('full','scoped_hybrid','scoped_latest'):raise ValueError('Unknown mode')
        p,candidates=self.scope(q);selected=[];trace=[];used=0;orders_seen=set();roles_seen=set()
        values=[float(relevance.get(d['id'],0)) for d in candidates];lo=min(values,default=0);hi=max(values,default=0)
        semantic=lambda d:(float(relevance.get(d['id'],0))-lo)/(hi-lo) if hi>lo else .5
        def merit(d):
            base=semantic(d)
            if mode!='full':return base
            codes=set(d.get('work_order_ids',[]))&set(p['orders'])
            coverage=.15 if len(p['orders'])>1 and codes-orders_seen else 0
            rg=role_group(self.roles.get(d['id'],{}).get('role','unknown'))
            role=.10 if rg in p['wanted_roles'] and rg not in roles_seen else 0
            return .75*base+coverage+role
        remaining=list(candidates)
        while remaining and len(selected)<self.top_k:
            if p['latest'] or mode=='scoped_latest':d=sorted(remaining,key=lambda d:(-dt(d['event_time']).timestamp(),d['id']))[0]
            else:d=sorted(remaining,key=lambda d:(-merit(d),-dt(d['event_time']).timestamp(),d['id']))[0]
            remaining.remove(d)
            if used+len(d['text'])>self.budget:continue
            selected.append(d['id']);used+=len(d['text']);orders_seen.update(d.get('work_order_ids',[]));roles_seen.add(role_group(self.roles.get(d['id'],{}).get('role','unknown')))
            applicable=self.current_applicable(d,q) if d['kind']=='procedure' else None
            trace.append(dict(id=d['id'],reason='explicit scope then '+('recency' if p['latest'] or mode=='scoped_latest' else mode),current_applicable=applicable,purpose=('current_reference' if applicable else 'historical_reference') if d['kind']=='procedure' else 'event_evidence'))
        return dict(evidence_ids=selected,trace=trace,characters=used,query_scope=p,candidate_count=len(candidates),status='ok' if candidates else 'no_visible_match')
