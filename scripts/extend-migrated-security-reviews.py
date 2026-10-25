#!/usr/bin/env python3
"""One-time, bounded extension of finite HOME-107 migration mutes to 30 days.

The deadline is the approved migration plan's generated_at plus 30 days. The
original expiry stays in each HOME107V2 record. No new or permanently reviewed
finding is updated. Fresh finite reviews keep their status, reason and timestamp.
Dry-run and inspect a plan before --apply-plan.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('migrate_security_reviews',
                                              ROOT / 'scripts/migrate-security-reviews.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)

MARKER = '\nHOME107V2:'
FINITE = {'pending', 'config', 'needs_evidence', 'requires_fix'}
SECONDS_30D = 30 * 86400


def digest(value):
    return hashlib.sha256(value).hexdigest()


def metadata(row):
    description = row.get('description') or ''
    if MARKER not in description:
        raise ValueError('HOME107V2 metadata missing')
    value = json.loads(description.rsplit(MARKER, 1)[1])
    if value.get('schema') != 2:
        raise ValueError('HOME107V2 schema mismatch')
    return value


def display_time(value):
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def extended_description(row, meta, original_expiry):
    lead = row['description'].rsplit(MARKER, 1)[0]
    if 'HOME-107 user-approved finite 30-day cutover mute;' in lead:
        raise ValueError('legacy expiry display already exists without matching extension')
    lead += ('\nHOME-107 user-approved finite 30-day cutover mute; original expiry '
             + display_time(original_expiry) + '; fixed deadline '
             + display_time(int(meta['legacy_extension_deadline'])))
    return lead + MARKER + json.dumps(meta, sort_keys=True, separators=(',', ':'))


def source_entries(source):
    if source.get('schema') != 1 or not isinstance(source.get('generated_at'), int):
        raise ValueError('invalid approved migration plan')
    values = source.get('entries') or []
    seen = set()
    for entry in values:
        check = entry.get('new_check_id')
        if not migration.CHECK.fullmatch(str(check)) or check in seen:
            raise ValueError('duplicate or invalid source check ID')
        seen.add(check)
    return [entry for entry in values if entry['status'] != 'not_affected']


def plan(source, source_sha256, maintenances, hostid, now):
    finite = source_entries(source)
    deadline = source['generated_at'] + SECONDS_30D
    if deadline <= now:
        raise ValueError('fixed 30-day migration deadline already passed')
    if str(hostid) != str(source['hostid']):
        raise ValueError('HomePBP host changed since approved migration')
    by_check = {}
    for row in maintenances:
        check = migration.one_check_tag(row)
        if check in by_check:
            raise ValueError('duplicate tagged maintenance: ' + check)
        if check:
            by_check[check] = row
    targets, skipped = [], []
    for entry in finite:
        check = entry['new_check_id']
        row = by_check.get(check)
        if not row or not migration.reviewed_existing([row], hostid, entry, now):
            raise ValueError('migrated exact maintenance missing or invalid: ' + check)
        meta = metadata(row)
        original = int(entry['active_till'])
        if meta.get('legacy_original_expiry') not in (None, original):
            raise ValueError('legacy original expiry conflicts with source: ' + check)
        if meta.get('status') not in FINITE:
            skipped.append({'check_id': check, 'reason': 'non_finite_current_status'})
            continue
        actual = int(row['active_till'])
        if actual >= deadline // 60 * 60:
            reason = ('already_extended' if meta.get('legacy_original_expiry') == original
                      and int(meta.get('expires_at') or 0) == deadline else 'already_long_enough')
            skipped.append({'check_id': check, 'reason': reason})
            continue
        if meta.get('legacy_original_expiry') is not None:
            raise ValueError('partial or conflicting legacy extension: ' + check)
        target_meta = {**meta, 'legacy_original_expiry': original,
                       'legacy_extension_deadline': deadline, 'expires_at': deadline}
        target_description = extended_description(row, target_meta, original)
        targets.append({'check_id': check, 'maintenanceid': str(row['maintenanceid']),
                        'image': entry['image'], 'cve': entry['cve'],
                        'service': entry['service'],
                        'finding_id': migration.finding_id(entry['image'], entry['cve'], entry['service']),
                        'source_status': entry['status'], 'current_status': meta['status'],
                        'old_active_till': actual, 'original_expiry': original,
                        'target_active_till': deadline,
                        'old_description_sha256': digest(row['description'].encode()),
                        'target_description': target_description})
    return {'schema': 1, 'generated_at': now, 'source_sha256': source_sha256,
            'source_generated_at': source['generated_at'], 'hostid': str(hostid),
            'fixed_deadline': deadline, 'targets': targets, 'skipped': skipped,
            'finite_source_count': len(finite)}


def target_applied(row, target, hostid, now):
    if int(row.get('active_till') or 0) != target['target_active_till'] // 60 * 60:
        return False
    if not migration.safe_daily_period(row, now):
        return False
    tags, hosts = row.get('tags') or [], row.get('hosts') or []
    if (str(row.get('maintenanceid')) != target['maintenanceid'] or
            migration.one_check_tag(row) != target['check_id'] or
            len(tags) != 1 or tags[0].get('operator') not in ('0', 0) or
            len(hosts) != 1 or str(hosts[0].get('hostid')) != str(hostid)):
        return False
    meta = metadata(row)
    return (all(meta.get(key) == target[key] for key in
                ('image', 'cve', 'service', 'check_id', 'finding_id')) and
            meta.get('legacy_original_expiry') == target['original_expiry'] and
            int(meta.get('expires_at') or 0) == target['target_active_till'])


def current_matches(row, target, hostid, now):
    if str(row.get('maintenanceid')) != target['maintenanceid']:
        return False
    if migration.one_check_tag(row) != target['check_id'] or not migration.safe_daily_period(row, now):
        return False
    tags, hosts = row.get('tags') or [], row.get('hosts') or []
    return (len(tags) == 1 and tags[0].get('operator') in ('0', 0) and
            len(hosts) == 1 and str(hosts[0].get('hostid')) == str(hostid) and
            int(row.get('active_till') or 0) == target['old_active_till'] and
            digest((row.get('description') or '').encode()) == target['old_description_sha256'])


def live(api):
    return migration.api_state(api)


def checkpoint(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2))
    temp.replace(path)


def apply(saved, source, api, path, max_updates):
    source_sha256 = digest(source)
    if source_sha256 != saved['source_sha256']:
        raise ValueError('approved migration source plan hash changed')
    progress_path = path.with_suffix('.progress.json')
    if not progress_path.exists() and time.time() - saved['generated_at'] > 900:
        raise ValueError('extension plan older than 15 minutes; regenerate for first apply')
    progress = json.loads(progress_path.read_text()) if progress_path.exists() else {'updated': []}
    completed = set(progress['updated'])
    hostid, _, rows = live(api)
    if str(hostid) != saved['hostid']:
        raise ValueError('HomePBP host identity changed')
    by_check = {migration.one_check_tag(row): row for row in rows if migration.one_check_tag(row)}
    updated, already, changed = 0, 0, 0
    for target in saved['targets']:
        check = target['check_id']
        row = by_check.get(check)
        if not row:
            raise ValueError('target maintenance disappeared: ' + check)
        now = int(time.time())
        if target_applied(row, target, hostid, now):
            already += 1
            if check not in completed:
                progress['updated'].append(check)
                completed.add(check)
                checkpoint(progress_path, progress)
            continue
        if check in completed:
            raise ValueError('checkpointed extension no longer matches Zabbix: ' + check)
        if not current_matches(row, target, hostid, now):
            changed += 1
            continue
        if updated >= max_updates:
            continue
        # Baloo may review a record while this bounded batch runs. Re-read the
        # exact record immediately before writing and skip changed evidence.
        before = api.call('maintenance.get', {
            'maintenanceids': [target['maintenanceid']],
            'output': ['maintenanceid', 'description', 'active_since', 'active_till', 'maintenance_type'],
            'selectTags': 'extend', 'selectHosts': ['hostid'],
            'selectTimeperiods': 'extend'})
        if len(before) != 1 or not current_matches(before[0], target, hostid, int(time.time())):
            changed += 1
            continue
        api.call('maintenance.update', {'maintenanceid': target['maintenanceid'],
                                        'active_till': target['target_active_till'],
                                        'description': target['target_description']})
        refreshed = api.call('maintenance.get', {
            'maintenanceids': [target['maintenanceid']],
            'output': ['maintenanceid', 'description', 'active_since', 'active_till', 'maintenance_type'],
            'selectTags': 'extend', 'selectHosts': ['hostid'],
            'selectTimeperiods': 'extend'})
        if len(refreshed) != 1 or not target_applied(refreshed[0], target, hostid, int(time.time())):
            raise ValueError('extension readback failed: ' + check)
        by_check[check] = refreshed[0]
        progress['updated'].append(check)
        completed.add(check)
        checkpoint(progress_path, progress)
        updated += 1
    return {'planned': len(saved['targets']), 'updated_this_run': updated,
            'confirmed_applied': len(completed), 'changed_since_plan': changed,
            'remaining': len(saved['targets']) - len(completed)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18080')
    parser.add_argument('--source-plan', type=Path, required=True)
    parser.add_argument('--plan-out', type=Path)
    parser.add_argument('--apply-plan', type=Path)
    parser.add_argument('--max-updates', type=int, default=25)
    args = parser.parse_args()
    if args.plan_out and args.apply_plan:
        parser.error('--plan-out and --apply-plan are mutually exclusive')
    if not 1 <= args.max_updates <= 50:
        parser.error('--max-updates must be between 1 and 50')
    source_bytes = args.source_plan.read_bytes()
    source = json.loads(source_bytes)
    credential = (migration.bootstrap.read_secret('zabbix', 'security-review-reconciler')
                  if args.apply_plan else migration.bootstrap.read_secret('baloo', 'zabbix-mcp'))
    token_key = 'api-token' if args.apply_plan else 'read-token'
    if not credential or not credential.get(token_key):
        raise SystemExit('Zabbix API credential unavailable')
    api = migration.bootstrap.API(args.url)
    api.token = credential[token_key]
    if args.apply_plan:
        saved = json.loads(args.apply_plan.read_text())
        result = apply(saved, source_bytes, api, args.apply_plan, args.max_updates)
        print(json.dumps(result))
        return
    hostid, _, rows = live(api)
    result = plan(source, digest(source_bytes), rows, hostid, int(time.time()))
    if args.plan_out:
        args.plan_out.write_text(json.dumps(result, indent=2))
    counts = {}
    for item in result['skipped']:
        counts[item['reason']] = counts.get(item['reason'], 0) + 1
    print(json.dumps({'finite_source_count': result['finite_source_count'],
                      'targets': len(result['targets']), 'skipped': counts,
                      'fixed_deadline': result['fixed_deadline'],
                      'plan_out': str(args.plan_out or '')}))


if __name__ == '__main__':
    main()
