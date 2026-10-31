import sys, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import dataset_exit_policy as policy
import dataset_versions as versions
import test_collect_datasets as fixtures
import unittest
m,ok=fixtures.m,fixtures.ok

class ExitPolicyTests(unittest.TestCase):
 setUp=fixtures.Tests.setUp
 tearDown=fixtures.Tests.tearDown
 collector=fixtures.Tests.collector
 def mixed(self):
  c=self.collector([ok([{}]*500,{'as_of':'one'}),ok([{'model_permaslug':'model/500'}],{'as_of':'two'})])
  c.collect(m.task('session-cost',{},'session-cost'))
  versions.index_session_cost(self.root,m.validate)
  return c
 def code(self,c):return policy.exit_code(self.root,c.run,m.validate)
 def test_only_known_verified_mismatch_is_provisional_warning(self):
  c=self.mixed(); self.assertEqual(self.code(c),75)
  self.assertFalse(versions.session_cost_research(self.root,m.validate)['queries'][0]['complete_batches'])
 def test_raw_corruption_is_failure(self):
  c=self.mixed(); p=next((self.root/'raw').rglob('*.gz'));p.write_bytes(p.read_bytes()+b'bad')
  self.assertEqual(self.code(c),1)
 def test_manifest_tampering_is_failure(self):
  c=self.mixed();p=next((self.root/'versions').rglob('*.json'));x=json.loads(p.read_bytes());x['research_eligible']=True;m.write_json(p,x)
  self.assertEqual(self.code(c),1)
 def test_missing_manifest_is_failure(self):
  c=self.mixed();next((self.root/'versions').rglob('*.json')).unlink()
  self.assertEqual(self.code(c),1)
 def test_checkpoint_mismatch_is_failure(self):
  c=self.mixed();c.state['tasks'][next(iter(c.state['tasks']))]['reason']='other';c.save()
  self.assertEqual(self.code(c),1)
 def test_unknown_invalid_never_downgraded(self):
  c=self.collector([(200,{},b'{}')]);c.collect(m.task('session-cost',{},'session-cost'))
  versions.index_session_cost(self.root,m.validate);self.assertEqual(self.code(c),1)
 def test_source_errors_never_downgraded(self):
  for status in [400,401,403,404,500]:
   c=self.collector([(status,{},b'error')]);c.collect(m.task('session-cost',{},'session-cost'))
   self.assertEqual(self.code(c),1)
 def test_duplicate_identity_never_downgraded(self):
  c=self.collector([ok([{}]*500),ok([{}])]);c.collect(m.task('session-cost',{},'session-cost'))
  versions.index_session_cost(self.root,m.validate);self.assertEqual(self.code(c),1)
 def test_mixed_warning_and_real_failure_is_failure(self):
  c=self.mixed();c.transport=lambda u:(500,{},b'error');c.collect(m.task('app-rankings',{},'app-rankings'))
  self.assertEqual(self.code(c),1)
 def test_missing_outcome_accounting_fails_closed(self):
  c=self.mixed();c.run['task_outcomes']=[];self.assertEqual(self.code(c),1)
 def test_normal_complete_and_budget_stop(self):
  c=self.collector([ok([{}])],limit=1);c.execute();self.assertEqual(self.code(c),0)
 def test_warning_adds_no_requests_and_preserves_bytes(self):
  c=self.mixed();before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
  self.assertEqual(self.code(c),75);self.assertEqual(len(self.calls),2)
  self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
 def test_rate_limit_remains_normal_stop(self):
  c=self.collector([(429,{'Retry-After':'120'},b'error')]);c.collect(m.task('session-cost',{},'session-cost'))
  self.assertEqual(self.code(c),0)
 def test_rate_limit_does_not_hide_unknown_failure(self):
  c=self.collector([(200,{},b'{}'),(429,{},b'error')])
  c.collect(m.task('session-cost',{},'session-cost'));c.collect(m.task('app-rankings',{},'app-rankings'))
  self.assertEqual(self.code(c),1)
 def test_cli_requires_current_lease(self):
  import subprocess
  c=self.mixed();m.write_json(self.root/'latest-report.json',dict(c.run,lease='old'))
  result=subprocess.run([sys.executable,str(Path(__file__).parents[1]/'scripts/collect-datasets.py'),'--root',str(self.root),'--verify-exit-policy','--lease','new'],capture_output=True)
  self.assertNotEqual(result.returncode,0)
 def test_argparse_failure_is_not_warning_code(self):
  import subprocess
  result=subprocess.run([sys.executable,str(Path(__file__).parents[1]/'scripts/collect-datasets.py'),'--no-such-flag'],capture_output=True)
  self.assertNotIn(result.returncode,[0,75])
