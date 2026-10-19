import copy,datetime as dt,importlib.util,json,tempfile,unittest,shutil
from pathlib import Path
spec=importlib.util.spec_from_file_location('transfer',Path(__file__).parents[1]/'scripts/datasets-transfer.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);c=m.c
NOW=dt.datetime(2026,10,19,15,tzinfo=dt.timezone.utc)
class Parallel(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'data';self.root.mkdir()
 def tearDown(self):self.tmp.cleanup()
 def test_migration_does_not_reset_old_budget(self):
  old={'version':1,'tasks':{},'budget':{'2026-10-19':{'attempts':449,'reserved':450}},'leases':{'old':{'day':'2026-10-19','granted':438,'remaining':0}},'not_before':'2026-10-20T00:00:00Z'}
  c.write_json(self.root/'checkpoint.json',old)
  self.assertEqual(c.reserve(self.root,'new1',NOW.date(),450,account='account1'),0)
  self.assertEqual(c.reserve(self.root,'new2',NOW.date(),12,account='account2'),12)
  s=c.load_json(self.root/'checkpoint.json',{});self.assertEqual(s['budget'],old['budget']);self.assertEqual(s['accounts']['account1']['not_before'],old['not_before']);self.assertNotIn('not_before',s['accounts']['account2'])
  self.assertEqual(c.migrate(copy.deepcopy(s)),s)
 def test_partitions_disjoint_complete_and_stable(self):
  tasks=c.plan(NOW.date());parts={a:{t['id'] for t in tasks if c.owner(t['id'])==a} for a in c.ACCOUNTS}
  self.assertFalse(parts['account1']&parts['account2']);self.assertEqual(parts['account1']|parts['account2'],{t['id'] for t in tasks})
  self.assertEqual(c.owner(c.task('session-cost',{},'')['id']),c.owner(c.task('session-cost',{},'',refresh=True)['id']))
 def test_account_429_isolation(self):
  c.reserve(self.root,'a',NOW.date(),12,account='account1');c.reserve(self.root,'b',NOW.date(),12,account='account2')
  worker=c.Collector(self.root,'fake',now=lambda:NOW,transport=lambda u:(429,{},b''),account='account1',lease='a',sleep=lambda _:None)
  t=next(t for t in c.plan(NOW.date()) if c.owner(t['id'])=='account1');worker.collect(t)
  self.assertEqual(worker.run['blocked'],'http_429')
  baseline=c.load_json(self.root/'checkpoint.json',{});self.assertNotIn('not_before',baseline['accounts']['account2']);self.assertEqual(baseline['accounts']['account2']['leases']['b']['remaining'],12)
 def payload(self,account):
  c.reserve(self.root,'lease-'+account,NOW.date(),12,account=account)
  worker=c.Collector(self.root,'fake',now=lambda:NOW,account=account,lease='lease-'+account,sleep=lambda _:None)
  worker.save();payload=Path(self.tmp.name)/'payload'/account
  rel='worker-state/'+account+'.json';target=payload/'files'/rel;target.parent.mkdir(parents=True);shutil.copyfile(self.root/rel,target)
  b=target.read_bytes();c.write_json(payload/'manifest.json',{'account':account,'shard_version':c.SHARD_VERSION,'files':[{'path':rel,'sha256':c.digest(b),'bytes':len(b)}]})
  return payload
 def test_missing_artifact_keeps_other_shard_and_reservation(self):
  self.payload('account1');c.reserve(self.root,'b',NOW.date(),12,account='account2')
  self.assertTrue(m.merge(self.root,Path(self.tmp.name)/'payload'))
  state=c.load_json(self.root/'checkpoint.json',{});self.assertEqual(state['accounts']['account2']['budget']['2026-10-19']['reserved'],12)
  report=c.load_json(self.root/'latest-report.json',{});self.assertEqual(report['accounts']['account1']['status'],'persisted');self.assertEqual(report['accounts']['account2']['status'],'not_merged')
 def test_corrupt_payload_rejected(self):
  p=self.payload('account1');(p/'files/worker-state/account1.json').write_text('{}')
  with self.assertRaises(ValueError):m.validate_payload(self.root,p,'account1',c.load_json(self.root/'checkpoint.json',{}))
 def test_path_traversal_rejected(self):
  for name in ['../bad','/absolute','bad\\file']:
   with self.assertRaises(ValueError):m.safe_path(name)
 def test_lease_cannot_be_reclaimed(self):
  p=self.payload('account1');path=p/'files/worker-state/account1.json';s=c.load_json(path,{});s['budget']['2026-10-19']['reserved']=450;c.write_json(path,s)
  manifest=c.load_json(p/'manifest.json',{});manifest['files'][0].update(sha256=c.digest(path.read_bytes()),bytes=path.stat().st_size);c.write_json(p/'manifest.json',manifest)
  with self.assertRaises(ValueError):m.validate_payload(self.root,p,'account1',c.load_json(self.root/'checkpoint.json',{}))
 def test_both_worker_results_merge_without_clobber(self):
  legacy=self.root/'raw/legacy/old.json.gz';legacy.parent.mkdir(parents=True);legacy.write_bytes(c.gzip.compress(b'old preserved raw',mtime=0));old_hash=c.digest(legacy.read_bytes())
  for account in c.ACCOUNTS:c.reserve(self.root,'lease-'+account,NOW.date(),12,account=account)
  chosen={a:next(t for t in c.plan(NOW.date()) if c.owner(t['id'])==a and t['endpoint']=='rankings-daily') for a in c.ACCOUNTS}
  for account in c.ACCOUNTS:
   t=chosen[account];meta={'as_of':'2026-10-19T00:00:00Z','version':'v1','start_date':t['params']['start_date'],'end_date':t['params']['end_date']}
   body={'data':[{'date':meta['end_date'],'model_permaslug':'model/test','total_tokens':'10'}],'meta':meta}
   worker=c.Collector(self.root,'fake',now=lambda:NOW,transport=lambda u:(200,{},c.encoded(body)),account=account,lease='lease-'+account,sleep=lambda _:None)
   worker.collect(t)
   payload=Path(self.tmp.name)/'payload'/account;files=[]
   paths=list((self.root/'attempts'/account).rglob('*.json'))+list((self.root/'raw').rglob('*.gz'))+[self.root/'worker-state'/f'{account}.json']
   for src in paths:
    rel=src.relative_to(self.root).as_posix();dest=payload/'files'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest);files.append({'path':rel,'sha256':c.digest(src.read_bytes()),'bytes':src.stat().st_size})
   c.write_json(payload/'manifest.json',{'account':account,'shard_version':c.SHARD_VERSION,'files':files})
  self.assertFalse(m.merge(self.root,Path(self.tmp.name)/'payload'))
  state=c.load_json(self.root/'checkpoint.json',{})
  self.assertEqual(set(state['tasks']),{t['id'] for t in chosen.values()});self.assertEqual(c.digest(legacy.read_bytes()),old_hash)
  for account in c.ACCOUNTS:self.assertEqual(state['accounts'][account]['budget']['2026-10-19']['attempts'],1)
 def test_missing_budget_history_rejected(self):
  p=self.payload('account1');path=p/'files/worker-state/account1.json';s=c.load_json(path,{});s['budget']={};c.write_json(path,s)
  manifest=c.load_json(p/'manifest.json',{});manifest['files'][0].update(sha256=c.digest(path.read_bytes()),bytes=path.stat().st_size);c.write_json(p/'manifest.json',manifest)
  with self.assertRaises(ValueError):m.validate_payload(self.root,p,'account1',c.load_json(self.root/'checkpoint.json',{}))
if __name__=='__main__':unittest.main()
