"""Authorized provider calls. Never log credentials, request headers or env contents."""
import hashlib
import json
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
class ProviderError(RuntimeError): pass

def settings():
    values={}
    for line in (ROOT/'local.env').read_text(encoding='utf-8-sig').splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:continue
        key,value=line.split('=',1);values[key.strip()]=value.strip().strip('"').strip("'")
    endpoint=values.get('ENDPOINT','');model=values.get('MODEL','');key=values.get('API_KEY','')
    if not endpoint.startswith('https://') or not model or not key:raise ProviderError('Missing required provider configuration')
    return dict(endpoint=endpoint,model=model,key=key,thinking=values.get('THINKING','disabled'))

class Client:
    def __init__(self,folder):
        self.cfg=settings();self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True);self.lock=threading.Lock();self.stopped=False
    def call(self,system,user,max_tokens=1800):
        payload=dict(model=self.cfg['model'],messages=[dict(role='system',content=system),dict(role='user',content=user)],temperature=0,max_tokens=max_tokens,response_format={'type':'json_object'},thinking={'type':self.cfg['thinking']})
        raw=json.dumps(payload,ensure_ascii=False).encode('utf-8');key=hashlib.sha256(raw).hexdigest();path=self.folder/(key+'.json')
        if path.exists():return json.loads(path.read_text(encoding='utf-8'))['result']
        if self.stopped:raise ProviderError('Provider run stopped')
        begin=time.perf_counter()
        for attempt in range(3):
            try:
                req=urllib.request.Request(self.cfg['endpoint'],data=raw,headers={'Content-Type':'application/json','Authorization':'Bearer '+self.cfg['key']})
                with urllib.request.urlopen(req,timeout=180) as response:data=json.load(response)
                result=json.loads(data['choices'][0]['message']['content'])
                if not isinstance(result,dict):raise ValueError('JSON object required')
                record=dict(request_hash=key,request=payload,model=data.get('model',self.cfg['model']),usage=data.get('usage'),seconds=time.perf_counter()-begin,finish_reason=data['choices'][0].get('finish_reason'),result=result)
                with self.lock:path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
                return result
            except urllib.error.HTTPError as exc:
                if exc.code in (401,402,403):self.stopped=True;raise ProviderError('Provider HTTP '+str(exc.code)) from None
                if exc.code not in (429,500,502,503,504) or attempt==2:raise ProviderError('Provider HTTP '+str(exc.code)) from None
                time.sleep(2**attempt)
            except (urllib.error.URLError,TimeoutError):
                if attempt==2:raise ProviderError('Provider network failure') from None
                time.sleep(2**attempt)
            except (ValueError,KeyError,IndexError,TypeError):
                raise ProviderError('Provider response failed JSON validation') from None

if __name__=='__main__':
    try:
        c=Client(ROOT/'experiments/runs/formal_temporal_rag_v1/api_cache')
        result=c.call('Return a JSON object only.','Reply with {"ok":true}.',64)
        print(json.dumps(dict(ok=result.get('ok') is True,model=c.cfg['model'],provider_host=urlsplit(c.cfg['endpoint']).hostname)))
    except ProviderError as exc:print(str(exc));raise SystemExit(1)
