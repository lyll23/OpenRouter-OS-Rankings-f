#!/usr/bin/env python3
"""Package worker deltas and validate/merge isolated account results (no API calls)."""
import argparse, copy, gzip, hashlib, importlib.util, json, shutil, subprocess
from pathlib import Path
spec=importlib.util.spec_from_file_location('collector',Path(__file__).with_name('collect-datasets.py'))
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

def safe_path(name):
    p=Path(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name: raise ValueError('unsafe path')
    return p

def package(root, account, output):
    root=Path(root);out=Path(output);out.mkdir(parents=True,exist_ok=True)
    changed=subprocess.check_output(['git','ls-files','--modified','--others','--exclude-standard','--',str(root)],text=True).splitlines()
    files=[]
    for name in sorted(set(changed)):
        src=Path(name)
        if not src.is_file(): continue
        rel=src.relative_to(root).as_posix()
        if rel=='checkpoint.json': continue
        target=out/'files'/safe_path(rel);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
        files.append({'path':rel,'sha256':c.digest(src.read_bytes()),'bytes':src.stat().st_size})
    c.write_json(out/'manifest.json',{'account':account,'shard_version':c.SHARD_VERSION,'files':files})

def validate_payload(root, payload, account, base):
    root=Path(root);payload=Path(payload)
    manifest=c.load_json(payload/'manifest.json',{})
    if manifest.get('account')!=account or manifest.get('shard_version')!=c.SHARD_VERSION: raise ValueError('account/shard mismatch')
    files={}
    for entry in manifest['files']:
        name=entry['path'];safe_path(name)
        allowed=(name.startswith(('raw/',f'attempts/{account}/',f'reports/{account}/')) or name in (f'worker-state/{account}.json',f'latest-report-{account}.json'))
        if not allowed or name in files: raise ValueError('unexpected/duplicate artifact path')
        src=payload/'files'/name;b=src.read_bytes()
        if len(b)!=entry['bytes'] or c.digest(b)!=entry['sha256']: raise ValueError('artifact digest mismatch')
        if (root/name).exists() and name.startswith(('raw/','attempts/','reports/')) and (root/name).read_bytes()!=b: raise ValueError('immutable file conflict')
        files[name]=src
    worker=c.load_json(files[f'worker-state/{account}.json'],{})
    if worker.get('shard_version')!=c.SHARD_VERSION: raise ValueError('worker shard mismatch')
    ledger=base['accounts'][account]
    if set(worker.get('budget',{}))!=set(ledger.get('budget',{})) or set(worker.get('leases',{}))!=set(ledger.get('leases',{})): raise ValueError('ledger history keys mismatch')
    for day,budget in worker['budget'].items():
        original=ledger['budget'].get(day,{})
        if budget.get('reserved',0)!=original.get('reserved',0) or not original.get('attempts',0)<=budget['attempts']<=budget.get('reserved',0)<=450: raise ValueError('budget mismatch')
    for key,lease in worker.get('leases',{}).items():
        original=ledger['leases'][key]
        if lease['granted']!=original['granted'] or lease['day']!=original['day'] or not 0<=lease['remaining']<=original['remaining']: raise ValueError('lease mismatch')
    def read(name): return (files.get(name) or root/safe_path(name)).read_bytes()
    for name,src in files.items():
        if not name.startswith('attempts/'): continue
        a=json.loads(src.read_bytes())
        params={k:v for k,v in a['params'].items() if k not in ('limit','offset')}
        if a.get('account')!=account or c.owner(c.task(a['endpoint'],params,'')['id'])!=account: raise ValueError('request on wrong shard')
        if 'raw_path' in a:
            compressed=read(a['raw_path']);raw=gzip.decompress(compressed)
            if c.digest(compressed)!=a['gzip_sha256'] or c.digest(raw)!=a['response_sha256'] or len(raw)!=a['bytes']: raise ValueError('raw digest mismatch')
            body=json.loads(raw);c.validate(body,a['endpoint'],a['params'])
            if len(body['data'])!=a['rows'] or body['meta']!=a['meta']: raise ValueError('raw/audit mismatch')
    updates={}
    for tid,t in worker['tasks'].items():
        if c.owner(tid)!=account: continue
        if c.task(t['endpoint'],t['params'],'')['id']!=tid: raise ValueError('task identity mismatch')
        for page in t.get('pages',[]):
            a=json.loads(read(page));raw=gzip.decompress(read(a['raw_path']))
            if c.digest(raw)!=a['response_sha256']: raise ValueError('task raw mismatch')
        updates[tid]=t
    return files,worker,updates

def merge(root, payload_root):
    root=Path(root);state=c.migrate(c.load_json(root/'checkpoint.json',{}));results={};failed=False
    for account in c.ACCOUNTS:
        payload=Path(payload_root)/account
        try:
            files,worker,updates=validate_payload(root,payload,account,state)
            for name,src in files.items():
                if name.startswith('worker-state/'): continue
                dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
            state['tasks'].update(updates)
            state['accounts'][account]={k:copy.deepcopy(worker[k]) for k in ('budget','leases','not_before') if k in worker}
            results[account]={'status':'persisted','updated_tasks':len(updates),'report':c.load_json(root/f'latest-report-{account}.json',{})}
        except (OSError,ValueError,KeyError,TypeError) as e:
            # Preserve the remotely reserved budget and other successful shard.
            failed=True;results[account]={'status':'not_merged','reason':type(e).__name__}
    c.write_json(root/'checkpoint.json',state)
    report={'finished_at':c.iso(c.utcnow()),'shard_version':c.SHARD_VERSION,'accounts':results,'all_shards_persisted':not failed}
    c.write_json(root/'latest-report.json',report)
    c.write_json(root/'reports'/'merged'/(c.iso(c.utcnow()).replace(':','-')+'.json'),report)
    return failed

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['package','merge']);p.add_argument('--root',default='data/datasets');p.add_argument('--account',choices=c.ACCOUNTS);p.add_argument('--payload',required=True);a=p.parse_args()
    if a.command=='package': package(a.root,a.account,a.payload)
    elif merge(a.root,a.payload): raise SystemExit('One or more account artifacts missing or invalid; other shard retained')
if __name__=='__main__':main()
