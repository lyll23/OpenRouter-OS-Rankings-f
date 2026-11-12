# 2026-11-12: Bounded priority for due source failures

## Reason and authorization

The owner approved the proposed retry-scheduling adjustment after investigation
of the 2026-11-11 HTTP 500 for app-rankings, 2026-04-14, audio-gen, trending.
Previously, `retry_on` only enabled eligibility: unseen historical queries ran
before every failed query, so a large backlog could indefinitely delay retries.

## Changes

- Keep current-day source observations, session-cost and current rankings windows first.
- Promote at most 10 due historical failures before unseen history. Select by
  oldest retry date, then oldest checked date, then task ID for deterministic ties.
- Include source_error, deferred_error and invalid_response. Do not promote
  known source_empty responses or errors whose retry date has not arrived.
- Remaining failures and known-empty revisits stay after unseen history. A failed
  retry gets its existing next retry date, allowing older waiting tasks to rotate in.
- Historical app queries cost at most two requests each: the priority lane uses
  at most 20 requests within the existing 450/day budget, never additional calls
  outside the lease. Other historical ranking queries cost one request each.
- No immediate retry loop, budget increase, schedule, permission, source
  classification, data deletion, or completeness/exit-policy change.

`retry_on` remains an earliest permitted date, not a guaranteed execution date.
A stopped run, exhausted lease, UTC boundary, rate limit or cancellation can still
prevent attempts. Persistent HTTP 500 and all other real failures still fail the
run; successful retries are recorded through the existing raw/attempt/checkpoint
paths. Historical raw files and prior run reports remain unchanged.

## Validation

- `python -m unittest discover -s tests -v`: 61 tests passed, including six new
  offline regressions for bounded priority, due-date eligibility, deterministic
  order, persistent-error rotation, successful recovery with a one-request lease,
  and HTTP 500 still producing failure after rescheduling.
- Read-only plan replay against the 2026-11-11 checkpoint puts the three waiting
  historical errors at eligible positions 92, 93 and 94, immediately after current
  work; the April 14 audio-gen query is position 94, not behind 18,637 pending tasks.
- No live OpenRouter requests or manual workflow dispatch used for these tests.

## Deployment behavior and follow-up

The existing main-branch path trigger runs Archive when collect-datasets.py changes.
Publishing this fix therefore naturally triggers that workflow, still subject to
its existing concurrency group and durable daily request reservation. This is not
an extra manual rerun. Verify the deployed commit and its production workflow;
local test success alone is not evidence that the source error has recovered.

Rollback, if needed, should revert only this code/documentation change. Do not
restore an old checkpoint or overwrite collected data.
