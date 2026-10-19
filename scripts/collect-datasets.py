#!/usr/bin/env python3
"""Archive public OpenRouter Datasets with bounded, resumable requests (stdlib only)."""
import argparse, datetime as dt, gzip, hashlib, json, os, sys, time, copy
import urllib.request, urllib.error, urllib.parse
from decimal import Decimal, InvalidOperation
from pathlib import Path

BASE = 'https://openrouter.ai/api/v1/datasets/'
START = dt.date(2025, 1, 1)
APP_CATEGORIES = ['coding', 'creative', 'productivity', 'entertainment']
APP_SUBCATEGORIES = ['cli-agent','ide-extension','cloud-agent','programming-app','native-app-builder','creative-writing','video-gen','image-gen','audio-gen','roleplay','game','writing-assistant','general-chat','personal-agent','legal']
RANK_CATEGORIES = ['programming','roleplay','marketing','marketing/seo','technology','science','translation','legal','finance','health','trivia','academia']
EXACT = [('modality', v) for v in ['text','image','image_output','audio','tool_calling']] + [('context_bucket', v) for v in ['1K','10K','100K','1M','10M']]
WEEKLY = [('category',v) for v in RANK_CATEGORIES] + [('language_type',v) for v in ['natural','programming']]
MAX_DAILY_REQUESTS = 450  # 50 reserved for the existing annual refresh / manual calls.

def encoded(x): return json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
def digest(b): return hashlib.sha256(b).hexdigest()
def utcnow(): return dt.datetime.now(dt.timezone.utc)
def iso(t): return t.isoformat().replace('+00:00','Z')
def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_bytes(encoded(value) + b'\n'); tmp.replace(path)
def load_json(path, default): return json.loads(path.read_bytes()) if path.exists() else default

def validate(body, endpoint, params):
    if not isinstance(body,dict) or not isinstance(body.get('data'),list) or not isinstance(body.get('meta'),dict): raise ValueError('schema')
    meta=body['meta']
    for k in ('as_of','version'):
        if not isinstance(meta.get(k),str) or not meta[k]: raise ValueError('metadata')
    dt.datetime.fromisoformat(meta['as_of'].replace('Z','+00:00'))
    if endpoint=='session-cost':
        dt.date.fromisoformat(meta['window_end_date'])
        if not isinstance(meta.get('window_days'),int) or meta['window_days']<=0: raise ValueError('window')
    else:
        for k in ('start_date','end_date'):
            dt.date.fromisoformat(meta[k])
            if k in params and meta[k]!=params[k]: raise ValueError('resolved window mismatch')
    seen=set()
    for row in body['data']:
        if not isinstance(row,dict): raise ValueError('row')
        if endpoint=='app-rankings':
            if not isinstance(row.get('app_id'),int) or not isinstance(row.get('rank'),int) or row['rank']<1 or not isinstance(row.get('app_name'),str): raise ValueError('app identity')
            identity=(row['app_id'],); metric='total_tokens'
            requests=row.get('total_requests')
            if not isinstance(requests,int) or requests<0: raise ValueError('requests')
        else:
            if not isinstance(row.get('model_permaslug'),str) or not row['model_permaslug']: raise ValueError('model identity')
            if endpoint=='session-cost':
                if not isinstance(row.get('app_slug'),str) or not row['app_slug'] or row.get('turn_range') not in ['1-turn','2-9-turns','10-49-turns','50-plus-turns']: raise ValueError('session identity')
                identity=(row['app_slug'],row['model_permaslug'],row['turn_range']); metric='median_session_cost_usd'
            else:
                dt.date.fromisoformat(row['date']); identity=(row['date'],row['model_permaslug']); metric='total_tokens'
        if identity in seen: raise ValueError('duplicate identity')
        seen.add(identity)
        value=row.get(metric)
        if value is None or isinstance(value,bool): raise ValueError('missing metric')
        try: number=Decimal(str(value))
        except InvalidOperation: raise ValueError('metric')
        if not number.is_finite() or number<0: raise ValueError('metric')
    return seen

def task(endpoint, params, family, *, refresh=False):
    identity = {'endpoint': endpoint, 'params': params}
    return dict(identity, id=digest(encoded(identity))[:24], family=family, refresh=refresh)

def plan(today):
    """Latest snapshots first, then finite historical queries; no filter Cartesian product."""
    end = today - dt.timedelta(days=1)
    if end < START: return []
    out = [task('session-cost', {}, 'session-cost', refresh=True)]
    app_filters = [{}] + [{'category':v} for v in APP_CATEGORIES] + [{'subcategory':v} for v in APP_SUBCATEGORIES]
    def apps(day):
        return [task('app-rankings', dict(start_date=str(day), end_date=str(day), sort=sort, **flt), 'app-rankings') for flt in app_filters for sort in ['popular','trending']]
    out.extend(apps(end))
    # Refresh a recent source window without replacing historical versions.
    recent = max(START, end - dt.timedelta(days=13))
    rank_filters = [('day', {})] + [('day', {k:v}) for k,v in EXACT] + [('week', {k:v}) for k,v in WEEKLY]
    for period, flt in rank_filters:
        out.append(task('rankings-daily',dict(start_date=str(recent),end_date=str(end),period=period,**flt),'rankings-'+period))
    # Yearly windows are at most 366 days; weekly output can extend beyond end_date.
    for year in range(today.year, 2024, -1):
        start = dt.date(year,1,1); stop = min(end,dt.date(year,12,31))
        if start > stop: continue
        for period, flt in rank_filters:
            out.append(task('rankings-daily',dict(start_date=str(start),end_date=str(stop),period=period,**flt),'rankings-'+period))
    # The first verified 2025 annual response omitted these dates. Probe exact days
    # separately under the normal budget; absence is never converted to zero.
    for missing in ['2025-06-15','2025-07-15']:
        if dt.date.fromisoformat(missing)<=end:
            out.append(task('rankings-daily',dict(start_date=missing,end_date=missing,period='day'),'rankings-gap-probe'))
    # Interleave all slices within each source date, newest historical dates first.
    for age in range(1,(end-START).days+1): out.extend(apps(end-dt.timedelta(days=age)))
    seen=set(); unique=[]
    for t in out:
        if t['id'] not in seen: seen.add(t['id']); unique.append(t)
    return unique

ACCOUNTS = ('account1','account2')
SHARD_VERSION = 'sha256-task-id-mod2-v1'
def owner(task_id): return ACCOUNTS[int(task_id,16)%2]
def migrate(state):
    if 'accounts' not in state:
        state['accounts']={'account1':{k:copy.deepcopy(state[k]) for k in ('budget','leases','not_before') if k in state},'account2':{'budget':{},'leases':{}}}
        state['version']=2; state['shard_version']=SHARD_VERSION
    if state.get('shard_version')!=SHARD_VERSION: raise ValueError('Unknown shard strategy')
    return state

def reserve(root, lease_id, today, requested, account=None):
    root=Path(root); state=load_json(root/'checkpoint.json',{'version':1,'tasks':{},'budget':{}})
    ledger=migrate(state)['accounts'][account] if account else state
    leases=ledger.setdefault('leases',{})
    if lease_id in leases: return leases[lease_id]['remaining']
    budget=ledger['budget'].setdefault(str(today),{'attempts':0,'reserved':0})
    grant=max(0,min(requested,MAX_DAILY_REQUESTS-budget.get('reserved',0)))
    budget['reserved']=budget.get('reserved',0)+grant
    leases[lease_id]={'day':str(today),'granted':grant,'remaining':grant}
    write_json(root/'checkpoint.json',state)
    return grant

def probe_plan(today):
    day=str(today-dt.timedelta(days=1))
    dates=dict(start_date=day,end_date=day)
    return [task('app-rankings',dict(dates,sort=s),'app-rankings') for s in ['popular','trending']] + [task('rankings-daily',dict(dates,period='day',**f),'rankings-day') for f in [{},{'modality':'image'},{'context_bucket':'1K'}]] + [task('rankings-daily',dict(dates,period='week',**f),'rankings-week') for f in [{'category':'programming'},{'language_type':'natural'}]] + [task('session-cost',{},'session-cost',refresh=True)]

def eligible(t, previous, today):
    if not previous: return True
    if previous.get('retry_on','9999') <= str(today): return True
    if t['refresh'] and previous.get('checked_date') != str(today): return True
    return previous.get('status') not in ('complete','source_empty','pagination_cap','source_error','deferred_error','invalid_response')

def prioritize(tasks, state, today):
    """Current observations first; unseen historical slices cannot be starved by retries."""
    latest=str(today-dt.timedelta(days=1))
    def priority(t):
        if t['endpoint']=='session-cost' or t['params'].get('end_date')==latest: return 0
        previous=state.get(t['id'])
        if not previous or previous.get('status')=='pending': return 1
        return 2
    return sorted(tasks,key=priority)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an Authorization header to a redirected destination.
        return None

class Collector:
    def __init__(self, root, key, *, now=utcnow, transport=None, limit=MAX_DAILY_REQUESTS, lease=None, probe=False, sleep=time.sleep, account=None):
        self.root=Path(root); self.key=key; self.now=now; self.transport=transport or self.http
        self.limit=min(MAX_DAILY_REQUESTS,max(0,limit)); self.today=self.now().date()
        self.state=load_json(self.root/'checkpoint.json',{'version':1,'tasks':{},'budget':{}})
        self.account=account
        if account:
            if account not in ACCOUNTS: raise ValueError('Invalid account')
            ledger=migrate(self.state)['accounts'][account]
            for k in ('budget','leases','not_before'):
                self.state.pop(k,None)
                if k in ledger: self.state[k]=copy.deepcopy(ledger[k])
        self.checkpoint_path=self.root/('worker-state/'+account+'.json' if account else 'checkpoint.json')
        self.run={'account':account,'shard_version':SHARD_VERSION if account else None,'started_at':iso(self.now()),'requests':0,'outcomes':{},'blocked':None}
        self.stop=False; self.lease=lease; self.probe=probe; self.sleep=sleep; self.last_request=None
    def save(self): write_json(self.checkpoint_path,self.state)
    def http(self,url):
        req=urllib.request.Request(url, headers={'Authorization':'Bearer '+self.key,'Accept':'application/json','User-Agent':'OpenRouter-public-datasets-archive/1.0'})
        try:
            with urllib.request.build_opener(NoRedirect()).open(req,timeout=90) as r: return r.status,dict(r.headers),r.read()
        except urllib.error.HTTPError as e: return e.code,dict(e.headers),e.read()
    def request(self,t,params):
        day=str(self.now().date())
        # Stop at the UTC boundary; the next invocation uses a new source date and budget.
        if day != str(self.today): self.stop=True; self.run['blocked']='utc_boundary'; return None
        budget=self.state['budget'].setdefault(day,{'attempts':0})
        if budget['attempts'] >= self.limit:
            self.stop=True; self.run['blocked']='daily_budget'; return None
        if self.state.get('not_before') and iso(self.now()) < self.state['not_before']:
            self.stop=True; self.run['blocked']='retry_after'; return None
        if self.lease:
            lease=self.state.get('leases',{}).get(self.lease,{})
            if lease.get('day')!=day or lease.get('remaining',0)<=0:
                self.stop=True; self.run['blocked']='lease_exhausted'; return None
            lease['remaining']-=1
        budget['attempts']+=1; self.run['requests']+=1; self.save() # Remote lease was committed before starting.
        url=BASE+t['endpoint']+'?'+urllib.parse.urlencode(sorted(params.items()))
        if self.last_request is not None: self.sleep(max(0,2.2-(time.monotonic()-self.last_request)))
        self.last_request=time.monotonic()
        stamp=iso(self.now())
        try: status,headers,raw=self.transport(url)
        except (OSError,TimeoutError): status,headers,raw=0,{},b''
        record={'account':self.account,'requested_at':stamp,'endpoint':t['endpoint'],'params':params,'http_status':status,'response_sha256':digest(raw),'bytes':len(raw)}
        record_path=self.root/'attempts'/(self.account or 'legacy')/day/(f"{budget['attempts']:04d}.json")
        if status==429:
            retry=next((v for k,v in headers.items() if k.lower()=='retry-after'),None)
            delay=max(1,int((dt.datetime.combine(self.today+dt.timedelta(days=1),dt.time(),tzinfo=dt.timezone.utc)-self.now()).total_seconds()))
            if retry:
                try: delay=max(delay,int(retry))
                except ValueError:
                    from email.utils import parsedate_to_datetime
                    try: delay=max(delay,int((parsedate_to_datetime(retry)-self.now()).total_seconds()))
                    except (ValueError,TypeError): pass
            self.state['not_before']=iso(self.now()+dt.timedelta(seconds=delay)); self.stop=True; self.run['blocked']='http_429'
            record['retry_at']=self.state['not_before']
        if status in (401,403): self.stop=True; self.run['blocked']='authentication_or_access'
        if status==200:
            try:
                body=json.loads(raw)
                validate(body,t['endpoint'],params)
                # Public aggregation endpoints only. Reject accidental private row identifiers.
                forbidden={'clerk_user_id','api_key','authorization','session_id'}
                def check(x):
                    if isinstance(x,dict):
                        if forbidden.intersection(k.lower() for k in x): raise ValueError('private field')
                        for v in x.values(): check(v)
                    elif isinstance(x,list):
                        for v in x: check(v)
                check(body)
                path=Path('raw')/t['endpoint']/day/(digest(raw)+'.json.gz')
                target=self.root/path; target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists(): target.write_bytes(gzip.compress(raw,mtime=0))
                record.update(raw_path=str(path),gzip_sha256=digest(target.read_bytes()),rows=len(body['data']),meta=body.get('meta'))
            except (ValueError,UnicodeError,AttributeError,KeyError,TypeError):
                record['validation']='invalid_or_unsafe_response'; body=None
        else: body=None
        # Do not persist untrusted error body or response headers that might echo credentials.
        write_json(record_path,record); self.save()
        return record,body,str(record_path.relative_to(self.root))
    def collect(self,t):
        if self.account and owner(t['id'])!=self.account: raise ValueError('Wrong account partition')
        previous=self.state['tasks'].get(t['id'],{})
        # Resume partial pagination only for the same UTC fetch day. A new day restarts,
        # avoiding combining pages from distinct weekly session snapshots.
        pages=previous.get('pages',[]) if previous.get('checked_date')==str(self.today) and previous.get('status')=='pending' else []
        endpoint=t['endpoint']; paged=endpoint in ('app-rankings','session-cost')
        size=100 if endpoint=='app-rankings' else 500
        cap=100 if endpoint=='app-rankings' else 5000
        offset=len(pages)*size
        outcome=dict(endpoint=endpoint,params=t['params'],family=t['family'],checked_date=str(self.today),pages=pages,status='pending',meta=previous.get('meta') if pages else None)
        self.state['tasks'][t['id']]=outcome
        while True:
            params=dict(t['params'])
            if paged: params.update(limit=size,offset=offset)
            result=self.request(t,params)
            if result is None: self.save(); return
            record,body,record_path=result
            if body is None:
                status=record['http_status']
                outcome.update(status='source_error' if status in (400,404,422) else 'invalid_response' if status==200 else 'deferred_error',retry_on=str(self.today+dt.timedelta(days=7 if status in (400,404,422) else 1)),last_attempt=record_path)
                break
            # Enforce stable source metadata over all pages; retain inconsistent raw but
            # never label a mixed-snapshot result complete.
            if pages and endpoint=='session-cost' and record.get('meta') != outcome.get('meta'):
                outcome.update(status='invalid_response',retry_on=str(self.today+dt.timedelta(days=1)),reason='snapshot_changed_during_pagination',last_attempt=record_path); break
            current_ids=validate(body,endpoint,params)
            prior_ids=set()
            for page in pages:
                audit=load_json(self.root/page,{})
                earlier=json.loads(gzip.decompress((self.root/audit['raw_path']).read_bytes()))
                prior_ids.update(validate(earlier,endpoint,audit['params']))
            if prior_ids.intersection(current_ids):
                outcome.update(status='invalid_response',retry_on=str(self.today+dt.timedelta(days=1)),reason='duplicate_identity_across_pages',last_attempt=record_path); break
            outcome['meta']=record.get('meta'); pages.append(record_path)
            outcome['rows']=sum(load_json(self.root/p,{})['rows'] for p in pages)
            if not paged or len(body['data'])<size:
                outcome['status']='complete' if outcome['rows'] else 'source_empty'
                if not outcome['rows']:
                    source_end=t['params'].get('end_date',str(self.today))
                    old=dt.date.fromisoformat(source_end)<self.today-dt.timedelta(days=30)
                    outcome['retry_on']=str(self.today+dt.timedelta(days=90 if old else 14))
                break
            if offset>=cap:
                outcome.update(status='pagination_cap',reason='last_allowed_page_full; completeness_not_proven'); break
            offset+=size; self.save()
            if self.stop: break
        self.run['outcomes'][outcome['status']]=self.run['outcomes'].get(outcome['status'],0)+1
        self.save()
    def execute(self):
        tasks=probe_plan(self.today) if self.probe and not self.account else plan(self.today)
        if self.account: tasks=[t for t in tasks if owner(t['id'])==self.account]
        for t in prioritize(tasks,self.state['tasks'],self.today):
            if eligible(t,self.state['tasks'].get(t['id']),self.today): self.collect(t)
            if self.stop: break
        self.run['source_states']={s:sum(v.get('status')==s for v in self.state['tasks'].values()) for s in sorted({v.get('status','unknown') for v in self.state['tasks'].values()})}
        self.run.update(finished_at=iso(self.now()),planned_tasks=len(tasks),pending_tasks=sum(eligible(t,self.state['tasks'].get(t['id']),self.today) for t in tasks),daily_requests=self.state['budget'].get(str(self.today),{}).get('attempts',0),daily_limit=self.limit,reserved_requests=500-self.limit,scope='Documented public dataset slices; not all platform traffic; historical session-cost unavailable')
        write_json(self.root/'reports'/(self.account or 'legacy')/(iso(self.now()).replace(':','-')+'.json'),self.run)
        write_json(self.root/('latest-report-'+self.account+'.json' if self.account else 'latest-report.json'),self.run)
        self.save()
        return self.run

def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',default='data/datasets'); p.add_argument('--plan',action='store_true'); p.add_argument('--limit',type=int,default=MAX_DAILY_REQUESTS); p.add_argument('--reserve',action='store_true'); p.add_argument('--lease'); p.add_argument('--probe',action='store_true'); p.add_argument('--account',choices=ACCOUNTS); args=p.parse_args()
    if args.plan:
        tasks=plan(utcnow().date()); print(json.dumps({'tasks':len(tasks),'by_family':{f:sum(t['family']==f for t in tasks) for f in sorted(set(t['family'] for t in tasks))}},indent=2)); return
    if args.reserve:
        if not args.lease: raise SystemExit('--lease required')
        print(reserve(args.root,args.lease,utcnow().date(),args.limit,account=args.account)); return
    if not args.lease: raise SystemExit('Production requests require a remotely committed --lease')
    key=os.environ.get('OPENROUTER_API_KEY')
    if not key: raise SystemExit('OPENROUTER_API_KEY is not configured')
    collector=Collector(args.root,key,limit=MAX_DAILY_REQUESTS,lease=args.lease,probe=args.probe,account=args.account); report=collector.execute(); print(json.dumps(report,indent=2))
    if report['blocked'] in ('authentication_or_access',): raise SystemExit(1)
    if any(report['outcomes'].get(s,0) for s in ('invalid_response','source_error','deferred_error')) and report['blocked']!='http_429': raise SystemExit(1)
if __name__=='__main__': main()
