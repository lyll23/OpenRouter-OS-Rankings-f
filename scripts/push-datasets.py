#!/usr/bin/env python3
"""Bounded, non-force Git persistence with read-back after uncertain results.

No automatic merge/rebase or retries of policy/auth/conflict failures. All data
must already be committed. Verify the entire datasets tree, not just exit code.
"""
import subprocess
import time

TRANSIENT = ('fatal error in commit_refs_rules', 'internal server error',
             'error: 500', 'error: 502', 'error: 503', 'error: 504',
             'http 500', 'http 502', 'http 503', 'http 504',
             'connection reset', 'connection timed out', 'connection closed',
             'remote end hung up', 'unexpected disconnect', 'timed out',
             'could not resolve host', 'failed to connect')
PERMANENT = ('permission denied', 'authentication failed', 'access denied',
             'protected branch', 'repository rule', 'gh006', 'gh013',
             'non-fast-forward', 'fetch first', 'file size limit', 'large files',
             'error: 401', 'error: 403')


def git(*args):
    return subprocess.run(['git', *args], text=True, capture_output=True, timeout=180)


def transient(result):
    message = (result.stdout + result.stderr).lower()
    return not any(x in message for x in PERMANENT) and any(x in message for x in TRANSIENT)


def checked(*args):
    result = git(*args)
    if result.returncode:
        raise RuntimeError('Git check failed: ' + ' '.join(args))
    return result.stdout.strip()


def persist(attempts=3, sleep=time.sleep):
    target = checked('rev-parse', 'HEAD')
    tree = checked('rev-parse', target + ':data/datasets')
    if checked('status', '--porcelain', '--untracked-files=all', '--', 'data/datasets'):
        raise RuntimeError('Uncommitted datasets: refusing persistence')
    for attempt in range(attempts):
        # Read back first, including after a failed/uncertain push. Never force.
        fetched = git('fetch', 'origin', 'refs/heads/main:refs/remotes/origin/main')
        if fetched.returncode:
            if not transient(fetched) or attempt == attempts - 1:
                raise RuntimeError('Cannot verify remote state; stopped without unsafe retry')
        else:
            remote = checked('rev-parse', 'refs/remotes/origin/main')
            ancestor = git('merge-base', '--is-ancestor', target, remote)
            if ancestor.returncode == 0:
                if checked('rev-parse', remote + ':data/datasets') != tree:
                    raise RuntimeError('Remote datasets advanced/changed; manual reconciliation required')
                print('Remote commit and complete datasets tree verified: ' + target)
                return
            if ancestor.returncode != 1:
                raise RuntimeError('Cannot establish remote ancestry')
            base = git('merge-base', '--is-ancestor', remote, target)
            if base.returncode != 0:
                raise RuntimeError('Remote advanced/diverged; no force or automatic rebase')
            pushed = git('push', 'origin', target + ':refs/heads/main')
            if pushed.returncode and not transient(pushed):
                raise RuntimeError('Push rejected by non-transient error; no retry')
            # Always verify outcome, even when the transport reported a failure.
            verify = git('fetch', 'origin', 'refs/heads/main:refs/remotes/origin/main')
            if verify.returncode == 0:
                remote = checked('rev-parse', 'refs/remotes/origin/main')
                if git('merge-base', '--is-ancestor', target, remote).returncode == 0:
                    if checked('rev-parse', remote + ':data/datasets') != tree:
                        raise RuntimeError('Remote datasets tree differs after push')
                    print('Remote commit and complete datasets tree verified: ' + target)
                    return
            elif not transient(verify):
                raise RuntimeError('Remote verification failed; no retry')
        if attempt < attempts - 1:
            print('Transient persistence failure; bounded retry after remote read-back')
            sleep((10, 30)[attempt])
    raise RuntimeError('Persistence not verified after three attempts')


if __name__ == '__main__':
    persist()
