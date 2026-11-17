"""Offline retry fairness and unchanged budget/quality regression tests."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_collect_datasets import m, NOW, ok

class RetryPriorityTests(unittest.TestCase):
    def task(self, n, day='2026-04-14'):
        return m.task('app-rankings', {'start_date':day,'end_date':day,'sort':'trending','subcategory':str(n)}, 'app-rankings')

    def test_current_then_ten_due_failures_then_unseen(self):
        current=self.task('current','2026-10-18')
        failures=[self.task(i) for i in range(12)]
        fresh=self.task('new')
        state={t['id']:{'status':'deferred_error','retry_on':f'2026-10-{i+1:02d}','checked_date':'2026-10-01'} for i,t in enumerate(failures)}
        order=m.prioritize([fresh,*reversed(failures),current],state,NOW.date())
        self.assertEqual(order,[current,*failures[:10],fresh,*reversed(failures[10:])])

    def test_empty_future_and_missing_retry_date_not_promoted(self):
        empty,future,missing,fresh=[self.task(i) for i in range(4)]
        state={empty['id']:{'status':'source_empty','retry_on':'2026-10-01'},
               future['id']:{'status':'deferred_error','retry_on':'2026-10-20'},
               missing['id']:{'status':'invalid_response'}}
        order=m.prioritize([empty,future,missing,fresh],state,NOW.date())
        self.assertEqual(order[0],fresh)
        self.assertFalse(m.eligible(future,state[future['id']],NOW.date()))
        self.assertFalse(m.eligible(missing,state[missing['id']],NOW.date()))

    def test_all_failure_states_and_deterministic_ties(self):
        failures=[self.task(i) for i in range(3)]
        state={t['id']:{'status':s,'retry_on':'2026-10-19','checked_date':'2026-10-18'} for t,s in zip(failures,sorted(m.ERROR_STATES))}
        self.assertEqual(m.prioritize(failures,state,NOW.date()), sorted(failures,key=lambda t:t['id']))

    def execute(self, response):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root=Path(temp.name); old=self.task('failed'); new=self.task('unseen')
        state={'version':1,'tasks':{old['id']:{'status':'deferred_error','retry_on':'2026-10-19','checked_date':'2026-10-18'}},'budget':{}}
        m.write_json(root/'checkpoint.json',state)
        m.reserve(root,'test-lease',NOW.date(),1)
        c=m.Collector(root,'fake',now=lambda:NOW,transport=lambda url:response,lease='test-lease',sleep=lambda _:None)
        with patch.object(m,'plan',return_value=[new,old]): c.execute()
        self.assertEqual(c.run['requests'],1)
        self.assertEqual(c.state['budget']['2026-10-19']['attempts'],1)
        self.assertEqual(c.run['blocked'],'lease_exhausted')
        self.assertEqual(len(list((root/'attempts').rglob('*.json'))),1)
        return root,c,old

    def test_due_failure_recovers_before_unseen_under_tiny_lease(self):
        root,c,old=self.execute(ok([{}],{'start_date':'2026-04-14','end_date':'2026-04-14'}))
        self.assertEqual(c.state['tasks'][old['id']]['status'],'complete')
        self.assertEqual(c.run['outcomes'],{'complete':1})

    def test_persistent_500_remains_failure_and_is_rescheduled(self):
        root,c,old=self.execute((500,{},b'server error'))
        self.assertEqual(c.state['tasks'][old['id']]['status'],'deferred_error')
        self.assertEqual(c.state['tasks'][old['id']]['retry_on'],'2026-10-20')
        from dataset_exit_policy import exit_code
        self.assertEqual(exit_code(root,c.run,m.validate),1)

    def test_retried_error_moves_behind_older_due_failures(self):
        a,b=self.task('a'),self.task('b')
        state={a['id']:{'status':'deferred_error','retry_on':'2026-10-20','checked_date':'2026-10-19'},
               b['id']:{'status':'deferred_error','retry_on':'2026-10-19','checked_date':'2026-10-18'}}
        self.assertEqual(m.prioritize([a,b],state,dt.date(2026,10,20)),[b,a])

class RollingRetryTests(unittest.TestCase):
    OLD=dt.date(2026,11,15)
    TODAY=dt.date(2026,11,16)

    def failure(self, recent=False):
        start='2026-11-01' if recent else '2026-01-01'
        t=m.task('rankings-daily',dict(category='science',period='week',start_date=start,end_date='2026-11-14'),'rankings-week')
        state=dict(endpoint=t['endpoint'],params=t['params'],family=t['family'],checked_date=str(self.OLD),retry_on=str(self.TODAY),status='deferred_error',pages=[],last_attempt='attempts/2026-11-15/0086.json')
        return t,state

    def test_annual_and_recent_windows_survive_day_rollover(self):
        for recent in (False,True):
            t,s=self.failure(recent);tasks=m.plan(self.TODAY)
            self.assertNotIn(t['id'],{x['id'] for x in tasks})
            restored=m.restore_due_failures(tasks,{t['id']:s},self.TODAY)
            self.assertEqual(restored[-1],t)
            self.assertTrue(m.eligible(t,s,self.TODAY))
            self.assertEqual(m.restore_due_failures(restored,{t['id']:s},self.TODAY),restored)

    def test_future_failure_and_completed_query_are_not_replayed(self):
        t,s=self.failure();tasks=m.plan(self.TODAY)
        s['retry_on']='2026-11-17'
        self.assertEqual(m.restore_due_failures(tasks,{t['id']:s},self.TODAY),tasks)
        s.update(status='complete',retry_on='2026-11-16')
        self.assertEqual(m.restore_due_failures(tasks,{t['id']:s},self.TODAY),tasks)

    def test_checkpoint_query_must_match_original_supported_plan(self):
        t,s=self.failure();s['params']=dict(s['params'],category='unapproved')
        with self.assertRaisesRegex(ValueError,'invalid_orphan_failure_identity'):
            m.restore_due_failures(m.plan(self.TODAY),{t['id']:s},self.TODAY)

    def test_restored_query_follows_current_and_precedes_unseen(self):
        t,s=self.failure();tasks=m.plan(self.TODAY)
        ordered=m.prioritize(m.restore_due_failures(tasks,{t['id']:s},self.TODAY),{t['id']:s},self.TODAY)
        i=ordered.index(t)
        self.assertTrue(all(x['endpoint']=='session-cost' or x['params'].get('end_date')=='2026-11-15' for x in ordered[:i]))
        self.assertTrue(any(x['endpoint']=='app-rankings' for x in ordered[i+1:]))

    def execute_orphan(self,response):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        old,state=self.failure();now=dt.datetime(2026,11,16,10,tzinfo=dt.timezone.utc)
        old_attempt=root/state['last_attempt'];old_attempt.parent.mkdir(parents=True);old_attempt.write_bytes(b'{"http_status":500}\n')
        m.write_json(root/'checkpoint.json',{'version':1,'tasks':{old['id']:state},'budget':{}})
        m.reserve(root,'rolling',self.TODAY,1)
        new=m.task('app-rankings',dict(start_date='2026-03-01',end_date='2026-03-01',sort='popular'),'app-rankings')
        original_plan=m.plan
        calls=[]
        def transport(url): calls.append(url);return response
        c=m.Collector(root,'fake',now=lambda:now,transport=transport,lease='rolling',sleep=lambda _:None)
        with patch.object(m,'plan',side_effect=lambda day: [new] if day==self.TODAY else original_plan(day)):
            c.execute()
        self.assertEqual(len(calls),1)
        self.assertIn('end_date=2026-11-14',calls[0])
        self.assertEqual(c.state['budget'][str(self.TODAY)]['attempts'],1)
        self.assertEqual(old_attempt.read_bytes(),b'{"http_status":500}\n')
        self.assertEqual(c.run['planned_tasks'],2)
        self.assertEqual(c.run['blocked'],'lease_exhausted')
        return root,c,old

    def test_execute_retries_original_window_preserving_history_and_budget(self):
        root,c,t=self.execute_orphan(ok([{}],dict(start_date='2026-01-01',end_date='2026-11-14')))
        self.assertEqual(c.state['tasks'][t['id']]['status'],'complete')
        self.assertEqual(c.run['pending_tasks'],1)

    def test_persistent_rolling_failure_still_exits_failure(self):
        root,c,t=self.execute_orphan((500,{},b'error'))
        self.assertEqual(c.state['tasks'][t['id']]['status'],'deferred_error')
        self.assertEqual(c.state['tasks'][t['id']]['retry_on'],'2026-11-17')
        from dataset_exit_policy import exit_code
        self.assertEqual(exit_code(root,c.run,m.validate),1)

    def test_repeated_failure_is_restored_again_on_following_day(self):
        root,c,t=self.execute_orphan((500,{},b'error'))
        tomorrow=self.TODAY+dt.timedelta(days=1)
        tasks=m.plan(tomorrow)
        restored=m.restore_due_failures(tasks,c.state['tasks'],tomorrow)
        self.assertEqual(restored[-1],t)
        self.assertTrue(m.eligible(t,c.state['tasks'][t['id']],tomorrow))

    def test_exhausted_lease_does_not_erase_orphan_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);t,state=self.failure()
            m.write_json(root/'checkpoint.json',{'version':1,'tasks':{t['id']:state},'budget':{}})
            m.reserve(root,'empty',self.TODAY,0)
            c=m.Collector(root,'fake',now=lambda:dt.datetime(2026,11,16,10,tzinfo=dt.timezone.utc),lease='empty',transport=lambda url:self.fail('must not request'))
            c.collect(t)
            self.assertEqual(c.state['tasks'][t['id']],state)
            self.assertEqual(c.run['requests'],0)
            self.assertEqual(m.restore_due_failures(m.plan(self.TODAY),c.state['tasks'],self.TODAY)[-1],t)
