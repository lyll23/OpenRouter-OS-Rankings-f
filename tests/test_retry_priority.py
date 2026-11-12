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
