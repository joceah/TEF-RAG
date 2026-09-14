"""Gold-free retrieval for the isolated temporal dev experiment."""
from __future__ import annotations
import hashlib
import json
import math
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.deps'))
import numpy as np

METHODS = ('bm25', 'bm25_time', 'dense_time', 'hybrid_time', 'time_rerank', 'full')
KS = (1, 3, 5, 10)
DATA = ROOT / 'data/generated/temporal_complex_dev_v1'
RUN = ROOT / 'experiments/runs/temporal_retrieval_dev_v1'
ANALYSIS = ROOT / 'experiments/analyses/temporal_retrieval_dev_v1'
FIGURES = ROOT / 'paper/figures/temporal_retrieval_dev_v1'
PLAN = ROOT / 'plans/时序检索dev实验预登记_v1.md'

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()

def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def lines(path):
    with Path(path).open(encoding='utf-8-sig') as f:
        return [json.loads(s) for s in f if s.strip()]

def write_lines(path, rows):
    with Path(path).open('w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')

def corpus():
    with sqlite3.connect(DATA.joinpath('store.sqlite').as_uri() + '?mode=ro', uri=True) as db:
        return [json.loads(x[0]) for x in db.execute('SELECT payload FROM evidence ORDER BY id')]

def tokens(text):
    result = []
    for part in re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]+', text.lower()):
        if '\u4e00' <= part[0] <= '\u9fff':
            result.extend(part)
            result.extend(part[i:i+2] for i in range(len(part)-1))
        else:
            result.append(part)
    return result

def visible(d, t):
    return (d['available_at'] <= t and d['event_time'] <= t
            and (d['kind'] != 'procedure' or
                 (d['valid_from'] <= t and (not d.get('valid_to') or t < d['valid_to']))))

def stamp(t):
    return datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp()

class Encoder:
    """Local ONNX inference; never imports the old cache-writing encoder."""
    def __init__(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.path = ROOT / 'data/models/multilingual_minilm'
        self.tokenizer = Tokenizer.from_file(str(self.path / 'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=128)
        self.tokenizer.enable_padding(pad_id=self.tokenizer.token_to_id('<pad>') or 0, pad_token='<pad>')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        self.session = ort.InferenceSession(str(self.path / 'model_quantized.onnx'), sess_options=options,
                                           providers=['CPUExecutionProvider'])
        self.inputs = {v.name for v in self.session.get_inputs()}
        self.outputs = [v.name for v in self.session.get_outputs()]

    def encode(self, texts):
        vectors = []
        for start in range(0, len(texts), 16):
            batch = self.tokenizer.encode_batch(texts[start:start+16])
            arrays = {'input_ids': np.array([e.ids for e in batch], dtype=np.int64),
                      'attention_mask': np.array([e.attention_mask for e in batch], dtype=np.int64),
                      'token_type_ids': np.array([e.type_ids for e in batch], dtype=np.int64)}
            out = self.session.run(None, {k:v for k,v in arrays.items() if k in self.inputs})
            hidden = out[self.outputs.index('last_hidden_state')] if 'last_hidden_state' in self.outputs else out[0]
            mask = arrays['attention_mask'][:,:,None]
            vec = (hidden*mask).sum(1)/np.maximum(mask.sum(1),1) if hidden.ndim == 3 else hidden
            vectors.append((vec/np.maximum(np.linalg.norm(vec,axis=1,keepdims=True),1e-12)).astype(np.float32))
        return np.vstack(vectors)

class Retriever:
    def __init__(self, docs, embeddings):
        self.docs, self.embeddings = docs, embeddings
        counts = [Counter(tokens(d['text'])) for d in docs]
        df = Counter(t for c in counts for t in c)
        length = np.array([sum(c.values()) for c in counts])
        norm = 1.5*(0.25+0.75*length/max(float(length.mean()),1))
        self.postings = {}
        for t, freq in df.items():
            tf = np.array([c[t] for c in counts])
            self.postings[t] = math.log(1+(len(docs)-freq+0.5)/(freq+0.5))*tf*2.5/(tf+norm)

    def rank(self, query, vector):
        # Intentionally discard every input field other than the public interface.
        q = {k:query[k] for k in ('text','asset_id','query_time')}
        docs = self.docs
        bm = sum((self.postings[t] for t in tokens(q['text']) if t in self.postings), np.zeros(len(docs)))
        dense = self.embeddings @ vector
        def order(scores, pool):
            return sorted(pool, key=lambda i: (-float(scores[i]), docs[i]['id']))
        all_ids = list(range(len(docs)))
        pool = [i for i,d in enumerate(docs) if visible(d,q['query_time'])]
        b, d = order(bm,pool), order(dense,pool)
        hybrid = np.zeros(len(docs))
        for ranking in (b,d):
            for pos,i in enumerate(ranking,1):
                hybrid[i] += 1/(60+pos)
        rerank = 0.8*hybrid/(2/61)
        for i in pool:
            age = max(0,(stamp(q['query_time'])-stamp(docs[i]['event_time']))/86400)
            rerank[i] += 0.2*(1 if docs[i]['kind']=='procedure' else math.exp(-age/30))
        ranked = order(rerank,pool)
        full = self.organize(q, ranked)
        indices = (order(bm,all_ids), b, d, order(hybrid,pool), ranked, full)
        return {m:[docs[i]['id'] for i in ids[:10]] for m,ids in zip(METHODS,indices)}

    def organize(self,q,ranked):
        docs = self.docs
        pool = [i for i in ranked if docs[i].get('asset_id') in (None,q['asset_id'])]
        latest = {}
        for i in pool:
            x = docs[i]
            if x['kind']=='work_order':
                key = x['work_order_id']
                if key not in latest or (x['event_time'],x['version'],x['id']) > (docs[latest[key]]['event_time'],docs[latest[key]]['version'],docs[latest[key]]['id']):
                    latest[key]=i
        if not latest:
            return []
        current = max(latest.values(),key=lambda i:(docs[i]['event_time'],docs[i]['id']))
        event = docs[current].get('episode_id')
        # A record without event linkage cannot license linking unrelated null-event rows.
        same = [i for i in pool if event is not None and docs[i].get('episode_id')==event
                and (docs[i]['kind']!='work_order' or i in latest.values())]
        selected = [current]
        states = [i for i in same if docs[i]['kind']=='state']
        if states:
            selected.append(max(states,key=lambda i:(docs[i]['event_time'],docs[i]['id'])))
        fault = docs[current].get('fault_code')
        procs = [i for i in pool if docs[i]['kind']=='procedure' and fault and docs[i].get('fault_code')==fault]
        if procs:
            selected.append(procs[0])
        notes = [i for i in same if docs[i]['kind']=='inspection_note']
        if notes:
            selected.append(notes[0])
        if any(t in q['text'] for t in ('复发','再次','上次','结案')):
            past = [i for i in latest.values() if i!=current and fault and docs[i].get('fault_code')==fault and docs[i].get('status')=='closed']
            if past:
                selected.append(max(past,key=lambda i:(docs[i]['event_time'],docs[i]['id'])))
        return selected + [i for i in same if i not in selected]

def metric_pairs(ids,q,g,lookup):
    grades = {r['evidence_id']:r['grade'] for r in g['relevance_judgments']}
    relevant = {i for i,v in grades.items() if v>0}
    dcg = sum((2**grades.get(i,0)-1)/math.log2(p+2) for p,i in enumerate(ids))
    ideal = sum((2**v-1)/math.log2(p+2) for p,v in enumerate(sorted(grades.values(),reverse=True)[:len(ids)]))
    # IDCG uses the requested cutoff, supplied by the caller when short output occurs.
    chosen = [lookup[i] for i in ids]
    work = [d for d in chosen if d['kind']=='work_order']
    procs = [d for d in chosen if d['kind']=='procedure']
    devices = [d for d in chosen if d.get('asset_id') is not None]
    return {'recall':[len(set(ids)&relevant),len(relevant)],
            'mrr':[next((1/(p+1) for p,i in enumerate(ids) if grades.get(i)==3),0),1],
            'ndcg_raw':[dcg,ideal],
            'current_event':[int(bool(work) and work[0].get('episode_id')==g['episode_id']),1],
            'procedure_correct':[int(g['correct_procedure_id'] in ids and all(visible(d,q['query_time']) for d in procs)),1],
            'procedure_valid':[sum(visible(d,q['query_time']) for d in procs),len(procs)],
            'future_leak':[sum(d['available_at']>q['query_time'] or d['event_time']>q['query_time'] for d in chosen),len(chosen)],
            'wrong_device':[sum(d['asset_id']!=q['asset_id'] for d in devices),len(devices)],
            'necessary_complete':[int(set(g['required_evidence_ids'])<=set(ids)),1]}

def evaluate(ids,q,g,lookup,k):
    pairs = metric_pairs(ids[:k],q,g,lookup)
    dcg = pairs.pop('ndcg_raw')[0]
    ideal = sum((2**v-1)/math.log2(p+2) for p,v in enumerate(sorted([r['grade'] for r in g['relevance_judgments']],reverse=True)[:k]))
    pairs['ndcg'] = [dcg/ideal if ideal else 0,1]
    return pairs

def bootstrap(values, draws):
    """values: event x method x (numerator, denominator); paired event resampling."""
    total = values.sum(axis=0)
    samples = values[draws].sum(axis=1)
    point = np.divide(total[:,0],total[:,1],out=np.full(len(total),np.nan),where=total[:,1]!=0)
    sampled = np.divide(samples[:,:,0],samples[:,:,1],out=np.full(samples.shape[:2],np.nan),where=samples[:,:,1]!=0)
    return total, point, sampled
