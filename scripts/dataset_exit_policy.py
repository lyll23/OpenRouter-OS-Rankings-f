"""Fail-closed exception for archived, quarantined session snapshot changes."""
import json
from pathlib import Path
from dataset_versions import batches, inspect_batch, safe_path


def verified_warnings(root, report, validate):
    root = Path(root)
    outcomes = report.get('task_outcomes', [])
    failures = [x for x in outcomes if x['status'] in ('invalid_response', 'source_error', 'deferred_error')]
    expected = sum(report['outcomes'].get(s, 0) for s in ('invalid_response', 'source_error', 'deferred_error'))
    if len(failures) != expected:
        raise ValueError('failure_accounting_mismatch')
    state = json.loads((root / 'checkpoint.json').read_bytes())
    warnings = []
    for failure in failures:
        current = state['tasks'][failure['task_id']]
        if current != failure['outcome']:
            raise ValueError('checkpoint_outcome_mismatch')
        # Preserve the existing normal Retry-After stop, but never let it hide
        # an unrelated failure from earlier in this run.
        if current.get('status') == 'deferred_error' and report.get('blocked') == 'http_429':
            attempt = json.loads(safe_path(root, current['last_attempt']).read_bytes())
            if attempt.get('http_status') == 429:
                continue
        if (current.get('endpoint') != 'session-cost' or current.get('status') != 'invalid_response'
                or current.get('reason') != 'snapshot_changed_during_pagination'):
            raise ValueError('unhandled_failure')
        paths = current['pages'] + [current['last_attempt']]
        matches = [b for b in batches(root) if b['attempt_paths'] == paths]
        if len(matches) != 1:
            raise ValueError('batch_not_identified')
        manifest, rows = inspect_batch(root, matches[0], validate)
        saved = json.loads((root / 'versions/session-cost' / (manifest['batch_id'] + '.json')).read_bytes())
        if saved != manifest:
            raise ValueError('version_manifest_mismatch')
        if (manifest['status'] != 'inconsistent' or manifest['completeness'] != 'unconfirmed'
                or manifest['research_eligible'] is not False or rows
                or manifest['reasons'] != ['snapshot_changed_during_pagination']
                or not all(p['integrity_valid'] for p in manifest['pages'])):
            raise ValueError('unsafe_warning_downgrade')
        warnings.append(manifest['batch_id'])
    return warnings


def exit_code(root, report, validate):
    if report.get('blocked') == 'authentication_or_access':
        return 1
    try:
        warnings = verified_warnings(root, report, validate)
    except (ValueError, KeyError, TypeError, OSError, EOFError):
        return 1
    return 75 if warnings else 0
