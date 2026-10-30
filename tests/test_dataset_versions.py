import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parents[1] / 'scripts'))
import dataset_versions as v
import unittest
import json
import test_collect_datasets as fixtures
m, ok, NOW = fixtures.m, fixtures.ok, fixtures.NOW

class VersionTests(unittest.TestCase):
 setUp = fixtures.Tests.setUp
 tearDown = fixtures.Tests.tearDown
 collector = fixtures.Tests.collector
 def make(self, responses, **kw):
  c=self.collector(responses,**kw); c.collect(m.task('session-cost',{},'session-cost')); return c
 def inspect(self): return v.index_session_cost(self.root,m.validate)
 def test_mixed_pages_all_retained_but_excluded(self):
  self.make([ok([{}]*500,{'as_of':'one'}),ok([{'model_permaslug':'model/500'}],{'as_of':'two'})])
  before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
  manifest=self.inspect()[0]
  self.assertEqual(manifest['status'],'inconsistent');self.assertEqual(len(manifest['pages']),2)
  self.assertEqual(manifest['observed_rows'],501);self.assertFalse(manifest['research_eligible'])
  self.assertEqual([p['offset'] for p in manifest['pages']],[0,500])
  self.assertNotEqual(manifest['pages'][0]['source_as_of'],manifest['pages'][1]['source_as_of'])
  self.assertEqual(v.session_cost_research(self.root,m.validate)['queries'][0]['complete_batches'],[])
  for p,b in before.items():self.assertEqual(__import__('pathlib').Path(p).read_bytes(),b)
 def test_complete_and_older_success_not_overwritten(self):
  self.make([ok([{}])]); first=self.inspect()[0]
  self.make([ok([{}]*500,{'as_of':'one'}),ok([{'model_permaslug':'model/500'}],{'as_of':'two'})])
  manifests=self.inspect();self.assertEqual(len(manifests),2)
  self.assertNotEqual(manifests[0]['batch_id'],manifests[1]['batch_id'])
  group=v.session_cost_research(self.root,m.validate)['queries'][0]
  self.assertEqual(len(group['complete_batches']),1);self.assertTrue(group['last_complete_is_older_attempt'])
  self.assertEqual(group['latest_attempt']['status'],'inconsistent')
  self.assertEqual(group['latest_complete_batch_id'],first['batch_id'])
 def test_resume_partial_same_day_becomes_complete(self):
  self.make([ok([{}]*500)],limit=1); a=self.inspect()[0]
  self.assertFalse(a['research_eligible'])
  self.make([ok([{'model_permaslug':'model/500'}])],limit=2); b=self.inspect()[0]
  self.assertEqual(a['batch_id'],b['batch_id']);self.assertTrue(b['research_eligible'])
  self.assertEqual(len(v.session_cost_research(self.root,m.validate)['queries'][0]['complete_batches'][0]['data']),501)
 def test_hash_tamper_fail_closed(self):
  self.make([ok([{}])]);manifest=self.inspect()[0]
  path=self.root/manifest['pages'][0]['raw_path'];path.write_bytes(path.read_bytes()+b'X')
  self.assertFalse(self.inspect()[0]['research_eligible'])
 def test_empty_excluded_and_index_idempotent(self):
  self.make([ok([])]);a=self.inspect();b=self.inspect()
  self.assertEqual(a,b);self.assertEqual(a[0]['status'],'source_empty');self.assertFalse(a[0]['research_eligible'])
 def test_cross_day_no_join_and_same_raw_new_batch(self):
  self.make([ok([{}]*500)],limit=1)
  c=self.collector([ok([{}])]);c.today=NOW.date()+m.dt.timedelta(days=1);c.now=lambda:NOW+m.dt.timedelta(days=1)
  c.collect(m.task('session-cost',{},'session-cost'))
  a=self.inspect();self.assertEqual(len(a),2);self.assertFalse(a[0]['research_eligible']);self.assertTrue(a[1]['research_eligible'])
 def test_budget_and_no_added_requests(self):
  c=self.make([ok([{}]*500)],limit=1); before=c.state['budget'].copy()
  self.inspect();v.session_cost_research(self.root,m.validate)
  self.assertEqual(c.state['budget'],before);self.assertEqual(len(self.calls),1)
 def test_unsafe_response_and_http_error_no_raw_leak(self):
  self.make([ok([{'clerk_user_id':'PRIVATE'}])]);self.assertFalse(self.inspect()[0]['research_eligible'])
  self.make([(500,{},b'SECRET')]);self.assertFalse(self.inspect()[-1]['research_eligible'])
  self.assertNotIn('SECRET',''.join(p.read_text() for p in self.root.rglob('*.json')))
 def test_orphan_page_cannot_be_complete(self):
  c=self.collector([ok([{}])]);c.request(m.task('session-cost',{},'session-cost'),{'limit':500,'offset':500})
  self.assertFalse(self.inspect()[0]['research_eligible'])
 def test_duplicate_across_pages_rejected(self):
  self.make([ok([{}]*500),ok([{}])]);self.assertFalse(self.inspect()[0]['research_eligible'])
 def test_plan_execute_indexes_without_extra_requests(self):
  c=self.collector([ok([{}])],limit=1);c.execute()
  self.assertEqual(len(self.calls),1);self.assertEqual(len(list((self.root/'versions/session-cost').glob('*.json'))),1)

 def test_imported_private_field_raw_is_rejected(self):
  self.make([ok([{}])]);record_path=next((self.root/'attempts').glob('*/*.json'))
  record=m.load_json(record_path,{})
  raw=json.loads(m.gzip.decompress((self.root/record['raw_path']).read_bytes()))
  raw['data'][0]['clerk_user_id']='PRIVATE'
  body=m.encoded(raw);archive=m.gzip.compress(body,mtime=0)
  (self.root/record['raw_path']).write_bytes(archive)
  record.update(bytes=len(body),response_sha256=m.digest(body),gzip_sha256=m.digest(archive))
  m.write_json(record_path,record)
  self.assertFalse(self.inspect()[0]['research_eligible'])
  self.assertNotIn('PRIVATE',m.encoded(v.session_cost_research(self.root,m.validate)).decode())
