"""Offline, lossless session-cost batch index and fail-closed research selector.

Existing attempts/raw are the source of truth. No HTTP requests, credentials,
checkpoint rewrites, or raw rewrites are performed here.
"""
import gzip
import hashlib
import json
from pathlib import Path


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def safe_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('archive_path_outside_root')
    return path


def read_json(path):
    return json.loads(path.read_bytes())


def assert_public(value):
    # Match the collector's privacy gate even for imported historical archives.
    forbidden = {'clerk_user_id', 'api_key', 'authorization', 'session_id'}
    if isinstance(value, dict):
        if forbidden.intersection(str(k).lower() for k in value):
            raise ValueError('private_field')
        for child in value.values(): assert_public(child)
    elif isinstance(value, list):
        for child in value: assert_public(child)


def batches(root):
    """Partition attempts by query, UTC fetch date and offset-zero starts.

    A nonzero first page is an orphan, never attached to yesterday's batch.
    Repeated offset zero starts a distinct batch even if all response bytes match.
    """
    root = Path(root)
    active = {}
    result = []
    for path in sorted((root / 'attempts').glob('*/*.json')):
        record = read_json(path)
        if record.get('endpoint') != 'session-cost':
            continue
        params = record.get('params', {})
        query = {k: v for k, v in params.items() if k not in ('offset', 'limit')}
        key = (path.parent.name, encoded(query))
        if params.get('offset') == 0 or key not in active:
            batch = {'schema_version': 1, 'endpoint': 'session-cost', 'query': query,
                     'fetch_date': path.parent.name, 'attempt_paths': []}
            active[key] = batch
            result.append(batch)
        active[key]['attempt_paths'].append(str(path.relative_to(root)))
    return result


def inspect_batch(root, batch, validate):
    """Recompute eligibility from archived bytes; never trust a saved green label."""
    root = Path(root)
    result = dict(batch)
    result['batch_id'] = sha256(encoded({'endpoint': 'session-cost', 'query': batch['query'],
                                         'first_attempt': batch['attempt_paths'][0]}))[:24]
    pages, metas, identities, data, errors = [], [], set(), [], []
    expected_offset = 0
    terminal = False
    for relative in batch['attempt_paths']:
        record_bytes = safe_path(root, relative).read_bytes()
        record = json.loads(record_bytes)
        assert_public(record)
        params = record.get('params', {})
        meta = record.get('meta')
        page = {'attempt_path': relative, 'attempt_sha256': sha256(record_bytes),
                'requested_at': record.get('requested_at'), 'offset': params.get('offset'),
                'limit': params.get('limit'), 'http_status': record.get('http_status'),
                'raw_path': record.get('raw_path'), 'response_sha256': record.get('response_sha256'),
                'gzip_sha256': record.get('gzip_sha256'), 'bytes': record.get('bytes'),
                'rows': record.get('rows'), 'source_meta': meta,
                'source_as_of': meta.get('as_of') if isinstance(meta, dict) else None,
                'source_version': meta.get('version') if isinstance(meta, dict) else None,
                'window_end_date': meta.get('window_end_date') if isinstance(meta, dict) else None,
                'window_days': meta.get('window_days') if isinstance(meta, dict) else None}
        pages.append(page)
        try:
            if record.get('endpoint') != 'session-cost': raise ValueError('wrong_endpoint')
            if {k: v for k, v in params.items() if k not in ('offset', 'limit')} != batch['query']:
                raise ValueError('wrong_query')
            if terminal: raise ValueError('page_after_terminal')
            if params.get('offset') != expected_offset or params.get('limit') != 500:
                raise ValueError('noncontiguous_or_unknown_pagination')
            if record.get('http_status') != 200 or not record.get('raw_path'):
                raise ValueError('invalid_or_unavailable_response')
            archive = safe_path(root, record['raw_path']).read_bytes()
            if sha256(archive) != record['gzip_sha256']: raise ValueError('gzip_sha256_mismatch')
            raw = gzip.decompress(archive)
            if sha256(raw) != record['response_sha256'] or len(raw) != record['bytes']:
                raise ValueError('body_integrity_mismatch')
            body = json.loads(raw)
            assert_public(body)
            current = validate(body, 'session-cost', params)
            if body['meta'] != meta or len(body['data']) != record['rows']:
                raise ValueError('attempt_body_mismatch')
            if len(body['data']) > 500: raise ValueError('oversized_page')
            if identities.intersection(current): raise ValueError('duplicate_identity_across_pages')
            identities.update(current)
            metas.append(meta)
            data.extend(body['data'])
            expected_offset += 500
            terminal = len(body['data']) < 500
            page['integrity_valid'] = True
        except (ValueError, KeyError, TypeError, OSError, EOFError) as exc:
            page['integrity_valid'] = False
            page['error'] = str(exc)
            errors.append(str(exc))
    consistent = bool(metas) and all(meta == metas[0] for meta in metas)
    if metas and not consistent: errors.append('snapshot_changed_during_pagination')
    complete = terminal and not errors and consistent
    eligible = complete and bool(data)
    result.update(pages=pages, started_at=pages[0]['requested_at'], last_requested_at=pages[-1]['requested_at'],
                  source_meta_consistent=consistent if len(metas) == len(pages) else None,
                  pagination_complete=terminal and not errors,
                  completeness='complete' if complete else 'unconfirmed', research_eligible=eligible,
                  status='complete' if eligible else 'source_empty' if complete else 'inconsistent' if 'snapshot_changed_during_pagination' in errors else 'incomplete',
                  observed_rows=sum(p.get('rows') or 0 for p in pages),
                  verified_rows=len(data), reasons=sorted(set(errors)))
    return result, data if eligible else []


def index_session_cost(root, validate):
    root = Path(root)
    manifests = []
    for batch in batches(root):
        manifest, _ = inspect_batch(root, batch, validate)
        destination = root / 'versions' / 'session-cost' / (manifest['batch_id'] + '.json')
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = encoded(manifest) + b'\n'
        if not destination.exists() or destination.read_bytes() != payload:
            temporary = destination.with_suffix('.json.tmp')
            temporary.write_bytes(payload)
            temporary.replace(destination)
        manifests.append(manifest)
    return manifests


def session_cost_research(root, validate):
    """Read-only view: complete historical batches, with explicit latest-attempt state.

    Query partitions are kept separate, never unioned as a fictitious snapshot.
    Each page retains its provenance; this view does not create a flat mixed CSV.
    """
    groups = {}
    for batch in batches(root):
        manifest, rows = inspect_batch(root, batch, validate)
        key = encoded(batch['query']).decode()
        group = groups.setdefault(key, {'query': batch['query'], 'complete_batches': [],
                                         'latest_attempt': None, 'latest_complete_batch_id': None})
        group['latest_attempt'] = {k: manifest[k] for k in ('batch_id', 'status', 'last_requested_at', 'research_eligible', 'reasons')}
        if manifest['research_eligible']:
            group['complete_batches'].append({'manifest': manifest, 'data': rows})
            group['latest_complete_batch_id'] = manifest['batch_id']
    for group in groups.values():
        group['last_complete_is_older_attempt'] = (group['latest_complete_batch_id'] is not None and
            group['latest_complete_batch_id'] != group['latest_attempt']['batch_id'])
    return {'schema_version': 1, 'endpoint': 'session-cost', 'queries': list(groups.values()),
            'scope': 'Verified complete per-query batches only; older batches retain their source timestamps and are not fresh observations.'}
