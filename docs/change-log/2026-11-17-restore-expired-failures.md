# Restore expired failed query windows (2026-11-17)

## Cause and scope

The science annual weekly query ending 2026-11-14 failed with HTTP 500 on
2026-11-15. Its checkpoint was eligible for retry from 2026-11-16, but the daily
planner advanced the annual end date and no longer emitted its task identity.
Retry prioritization only saw the newly generated plan, so the old query was
never retried. A newer successful window was not a recovery of that query.

## Changes

- Merge due failed queries absent from the current plan, preserving their exact
  endpoint/parameters/identity. Validate against the supported plan for the
  original end date plus one day; do not trust arbitrary checkpoint endpoints.
- Use the immutable query window, not `checked_date` (which advances on retries),
  so repeated failures remain recoverable on later days.
- Deduplicate before the existing prioritizer. Current tasks remain first,
  followed by at most 10 promoted due failures and then unseen history.
- Do not overwrite an existing failure with pending if budget, lease, UTC
  boundary or retry delay stops execution before a new request.
- Preserve the 450-request daily limit, remote lease reservations, raw attempt
  history, failure handling, pagination/schema gates and unchanged probe scope.
  Restored due tasks now contribute to planned/pending task counts.

## Validation

`python -m unittest discover -s tests -v`: 69 offline tests passed.
Added coverage for annual/recent rolling windows across midnight, duplicate
restoration, future/non-failure exclusions, identity validation, ordering,
original-query execution with a one-request lease, persistent failures,
next-day repeated retry, and zero-budget preservation.

The current remote checkpoint was replayed offline: exactly one missing failed
query is restored (science/week, 2026-01-01 through 2026-11-14).
No historical files are changed by this patch. A later successful retry records
what the source returns then; it cannot recreate the original collection-time
snapshot.

## Deployment behavior

A main-branch change to scripts/collect-datasets.py automatically starts the
existing Archive public datasets workflow. No extra manual dispatch is needed.
The workflow must reserve the remaining daily budget remotely before requests.
Production success/retry outcome must be verified separately after deployment.
