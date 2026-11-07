import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('push_datasets', Path(__file__).parents[1] / 'scripts/push-datasets.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def result(code=0, out='', err=''):
    return subprocess.CompletedProcess([], code, out, err)


class PersistenceTests(unittest.TestCase):
    def run_case(self, responses, error=None):
        def invoke(*args):
            expected, answer = responses.pop(0)
            self.assertEqual(args, expected)
            return answer
        with patch.object(m, 'git', side_effect=invoke), patch.object(m.time, 'sleep'):
            if error:
                with self.assertRaisesRegex(RuntimeError, error):
                    m.persist(sleep=lambda _: None)
            else:
                m.persist(sleep=lambda _: None)
        self.assertEqual(responses, [])

    def prefix(self):
        return [(('rev-parse','HEAD'),result(out='local\n')),
                (('rev-parse','local:data/datasets'),result(out='tree\n')),
                (('status','--porcelain','--untracked-files=all','--','data/datasets'),result())]

    def before_push(self):
        return [(('fetch','origin','refs/heads/main:refs/remotes/origin/main'),result()),
                (('rev-parse','refs/remotes/origin/main'),result(out='remote')),
                (('merge-base','--is-ancestor','local','remote'),result(1)),
                (('merge-base','--is-ancestor','remote','local'),result())]

    def verified(self):
        return [(('fetch','origin','refs/heads/main:refs/remotes/origin/main'),result()),
                (('rev-parse','refs/remotes/origin/main'),result(out='local')),
                (('merge-base','--is-ancestor','local','local'),result()),
                (('rev-parse','local:data/datasets'),result(out='tree'))]

    def test_normal_push(self):
        self.run_case(self.prefix()+self.before_push()+[(('push','origin','local:refs/heads/main'),result())]+self.verified())

    def test_uncertain_push_already_saved(self):
        self.run_case(self.prefix()+self.before_push()+[(('push','origin','local:refs/heads/main'),result(1,err='connection reset'))]+self.verified())

    def test_transient_failure_retry(self):
        retry=[(('push','origin','local:refs/heads/main'),result(1,err='fatal error in commit_refs_rules')),
               (('fetch','origin','refs/heads/main:refs/remotes/origin/main'),result()),
               (('rev-parse','refs/remotes/origin/main'),result(out='remote')),
               (('merge-base','--is-ancestor','local','remote'),result(1))]
        self.run_case(self.prefix()+self.before_push()+retry+self.before_push()+[(('push','origin','local:refs/heads/main'),result())]+self.verified())

    def test_rules_rejection_never_retried(self):
        self.run_case(self.prefix()+self.before_push()+[(('push','origin','local:refs/heads/main'),result(1,err='GH013 repository rule'))], 'non-transient')

    def test_already_saved_no_push(self):
        self.run_case(self.prefix()+self.verified())

    def test_remote_changed_tree(self):
        r=self.prefix()+self.verified();r[-1]=(r[-1][0],result(out='different'))
        self.run_case(r,'advanced/changed')

    def test_divergence_never_overwritten(self):
        r=self.prefix()+self.before_push();r[-1]=(r[-1][0],result(1))
        self.run_case(r,'advanced/diverged')

    def test_dirty_archive(self):
        r=self.prefix();r[-1]=(r[-1][0],result(out='?? data/datasets/raw/new'))
        self.run_case(r,'Uncommitted')

    def test_three_fetch_failures_stop(self):
        self.run_case(self.prefix()+[(('fetch','origin','refs/heads/main:refs/remotes/origin/main'),result(1,err='HTTP 503'))]*3,'Cannot verify')

    def test_classifier(self):
        self.assertFalse(m.transient(result(1,err='GH013 fatal error in commit_refs_rules')))
        self.assertFalse(m.transient(result(1,err='unknown failure')))
        self.assertTrue(m.transient(result(1,err='remote: fatal error in commit_refs_rules')))
