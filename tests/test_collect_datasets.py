import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('collector',Path(__file__).parents[1]/'scripts/collect-datasets.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
NOW=dt.datetime(2026,10,19,10,tzinfo=dt.timezone.utc)
def ok(rows,meta=None):
 meta=dict({'as_of':'2026-10-19T00:00:00Z','version':'v1','start_date':'2026-10-18','end_date':'2026-10-18','window_end_date':'2026-10-18','window_days':30},**(meta or {}))
 if meta['as_of'] in ('one','two'): meta['as_of']='2026-10-19T0'+('1' if meta['as_of']=='one' else '2')+':00:00Z'
 rows=[dict({'app_id':i,'app_name':'app','rank':i+1,'total_requests':1,'total_tokens':'10','model_permaslug':'model/'+str(i),'date':'2026-10-18','app_slug':'app','turn_range':'1-turn','median_session_cost_usd':0.5},**r) for i,r in enumerate(rows)]
 return 200,{},m.encoded({'data':rows,'meta':meta})
class Tests(unittest.TestCase):
 def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
 def tearDown(self): self.tmp.cleanup()
 def collector(self, responses, **kw):
  self.calls=[]; self.sleeps=[]
  def transport(url): self.calls.append(url); return responses.pop(0)
  return m.Collector(self.root,'FAKE-SECRET',now=lambda:NOW,transport=transport,sleep=self.sleeps.append,**kw)
 def test_plan_boundaries_and_filters(self):
  tasks=m.plan(NOW.date()); self.assertEqual(len({t['id'] for t in tasks}),len(tasks))
  apps=[t for t in tasks if t['endpoint']=='app-rankings']; self.assertEqual(len(apps),656*40)
  self.assertEqual(min(t['params']['start_date'] for t in apps),'2025-01-01')
  self.assertEqual(max(t['params']['end_date'] for t in apps),'2026-10-18')
  for t in tasks:
   p=t['params']; self.assertLessEqual(sum(k in p for k in ['modality','context_bucket','category','subcategory','language_type']),1)
   if t['endpoint']=='rankings-daily': self.assertLessEqual((dt.date.fromisoformat(p['end_date'])-dt.date.fromisoformat(p['start_date'])).days+1,366)
   if 'language_type' in p or t['endpoint']=='rankings-daily' and 'category' in p: self.assertEqual(p['period'],'week')
 def test_raw_hash_and_no_secret(self):
  c=self.collector([ok([{'x':1}],{'as_of':'one'})]);t=m.task('session-cost',{},'session-cost'); c.collect(t)
  entry=c.state['tasks'][t['id']];self.assertEqual(entry['status'],'complete')
  record=m.load_json(self.root/entry['pages'][0],{}); raw=m.gzip.decompress((self.root/record['raw_path']).read_bytes())
  self.assertEqual(m.digest(raw),record['response_sha256']); self.assertEqual(m.digest((self.root/record['raw_path']).read_bytes()),record['gzip_sha256'])
  self.assertNotIn('FAKE-SECRET',''.join(p.read_text() for p in self.root.rglob('*.json')))
 def test_app_pagination_cap(self):
  c=self.collector([ok([{}]*100),ok([{'app_id':i+100} for i in range(100)])]);t=m.task('app-rankings',{},'app-rankings');c.collect(t)
  self.assertEqual(c.state['tasks'][t['id']]['status'],'pagination_cap');self.assertIn('offset=100',self.calls[1]);self.assertTrue(self.sleeps)
 def test_empty_has_recheck(self):
  c=self.collector([ok([])]); t=m.task('app-rankings',{},'app-rankings');c.collect(t)
  self.assertEqual(c.state['tasks'][t['id']]['status'],'source_empty');self.assertIn('retry_on',c.state['tasks'][t['id']])
 def test_429_stops_until_at_least_midnight(self):
  c=self.collector([(429,{'Retry-After':'5'},b'key echo FAKE-SECRET')]);c.collect(m.task('session-cost',{},'session-cost'))
  self.assertTrue(c.stop);self.assertGreaterEqual(c.state['not_before'],'2026-10-20T00:00:00Z')
  self.assertNotIn('FAKE-SECRET',''.join(p.read_text() for p in self.root.rglob('*.json')))
 def test_unsafe_response_not_saved(self):
  c=self.collector([ok([{'clerk_user_id':'private'}])]);t=m.task('session-cost',{},'session-cost');c.collect(t)
  self.assertEqual(c.state['tasks'][t['id']]['status'],'invalid_response'); self.assertEqual(list(self.root.glob('raw/**/*gz')),[])
 def test_session_metadata_changes(self):
  c=self.collector([ok([{}]*500,{'as_of':'one'}),ok([{}],{'as_of':'two'})]);t=m.task('session-cost',{},'session-cost');c.collect(t)
  self.assertEqual(c.state['tasks'][t['id']]['status'],'invalid_response')
 def test_session_resume_meta(self):
  t=m.task('session-cost',{},'session-cost');c=self.collector([ok([{}]*500,{'as_of':'one'})],limit=1);c.collect(t)
  self.assertEqual(c.state['tasks'][t['id']]['status'],'pending')
  c=self.collector([ok([{'model_permaslug':'model/500'}],{'as_of':'one'})],limit=2);c.collect(t)
  self.assertEqual(c.state['tasks'][t['id']]['status'],'complete'); self.assertEqual(c.state['tasks'][t['id']]['rows'],501)
 def test_remote_reservations_survive_crash(self):
  self.assertEqual(m.reserve(self.root,'a',NOW.date(),12),12)
  self.assertEqual(m.reserve(self.root,'b',NOW.date(),450),438)
  self.assertEqual(m.reserve(self.root,'c',NOW.date(),450),0)
  self.assertEqual(m.reserve(self.root,'a',NOW.date(),12),12)
 def test_lease_consumption(self):
  m.reserve(self.root,'a',NOW.date(),1); c=self.collector([ok([{}]*500)],lease='a');t=m.task('session-cost',{},'session-cost');c.collect(t)
  self.assertEqual(len(self.calls),1);self.assertEqual(c.run['blocked'],'lease_exhausted')
 def test_auth_stops(self):
  c=self.collector([(401,{},b'failure')]);c.collect(m.task('session-cost',{},'session-cost'));self.assertTrue(c.stop)
 def test_network_failure_deferred(self):
  c=self.collector([]);c.transport=lambda url: (_ for _ in ()).throw(TimeoutError()); t=m.task('session-cost',{},'session-cost');c.collect(t)
  self.assertEqual(c.state['tasks'][t['id']]['status'],'deferred_error')
 def test_window_change_starts_fresh(self):
  t=m.task('session-cost',{},'session-cost');c=self.collector([ok([{}]*500,{'as_of':'one'})],limit=1);c.collect(t)
  c=self.collector([ok([{}],{'as_of':'two'})],limit=2);c.today=NOW.date()+dt.timedelta(days=1);c.now=lambda:NOW+dt.timedelta(days=1);c.collect(t)
  self.assertIn('offset=0',self.calls[0]);self.assertEqual(c.state['tasks'][t['id']]['rows'],1)
 def test_malformed_row_is_not_complete(self):
  c=self.collector([(200,{},m.encoded({'data':[{}],'meta':{}}))]);t=m.task('session-cost',{},'session-cost');c.collect(t)
  self.assertEqual(c.state['tasks'][t['id']]['status'],'invalid_response')
 def test_negative_metric_is_rejected(self):
  c=self.collector([ok([{'total_tokens':'-1'}])]);t=m.task('app-rankings',{},'app-rankings');c.collect(t)
  self.assertEqual(c.state['tasks'][t['id']]['status'],'invalid_response')
if __name__=='__main__': unittest.main()
