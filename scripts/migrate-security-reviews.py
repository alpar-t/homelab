#!/usr/bin/env python3
"""Plan and apply exact-service Zabbix review records from legacy CVE reviews.

Run dry-run before the per-service collector cutover. The plan contains no API
credentials. Apply re-reads live state, requires an identical fresh plan, and
only creates new check-scoped maintenance; it leaves legacy records intact.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bootstrap_zabbix', ROOT / 'scripts/bootstrap-zabbix.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)

REVIEW_MARKERS = {
    'REVIEWED_NOT_AFFECTED': 'not_affected',
    'REVIEWED_CONFIG_30D': 'config',
    'REVIEWED_CONFIG_ALERTING': 'config',
    'REVIEWED_NEEDS_EVIDENCE': 'needs_evidence',
    'REVIEWED_REQUIRES_FIX': 'requires_fix',
}
URL = re.compile(r'https://[^\s;,]+')
FULL_REF = re.compile(r'^[a-z0-9][a-z0-9._:/-]*@sha256:[a-f0-9]{64}$')
CVE = re.compile(r'^(?:CVE-\d{4}-\d{4,}|GHSA-[a-z0-9-]{10,})$', re.I)
CHECK = re.compile(r'^[a-f0-9]{20}$')


def exact_hash(parts):
    value = json.dumps(parts, separators=(',', ':')).encode()
    return hashlib.sha256(value).hexdigest()


def legacy_check_id(image, cve):
    short = image.rsplit('/', 1)[-1].split('@')[0] + '@' + image.rsplit(':', 1)[-1][:12]
    return hashlib.sha256(f'Critical {cve} {short}'.encode()).hexdigest()[:20]


def new_check_id(image, cve, service):
    return exact_hash(['security-raw-v2', image, cve, service])[:20]


def finding_id(image, cve, service):
    return exact_hash(['security-finding-v1', image, cve, service])


def one_check_tag(value):
    tags = value.get('tags') or []
    checks = [t.get('value') for t in tags if t.get('tag') == 'check_id']
    return checks[0] if len(checks) == 1 and CHECK.fullmatch(str(checks[0])) else None


def evidence_note(event, maintenance):
    notes = sorted(event.get('acknowledges') or [], key=lambda a: int(a.get('clock') or 0), reverse=True)
    notes = [a.get('message') or '' for a in notes]
    notes.extend(m.get('description') or '' for m in maintenance)
    for note in notes:
        if any(marker in note for marker in REVIEW_MARKERS):
            return note
    return next((note for note in notes if note), '')


def review_status(note):
    for marker, status in REVIEW_MARKERS.items():
        if marker in note:
            return status
    if 'disposition=not applicable in reviewed runtime' in note:
        return 'not_affected'
    return 'pending'


def field(note, name):
    match = re.search(r'(?:^|[;|\n])\s*' + re.escape(name) + r'=([^;|\n]+)', note)
    return match[1].strip() if match else ''


def record_evidence(note, finding):
    reason = field(note, 'reason') or note.split(' | ', 1)[-1].strip()
    urls = list(dict.fromkeys(URL.findall(note)))[:5]
    if finding.get('url') and finding['url'] not in urls:
        urls.append(finding['url'])
    recheck = field(note, 'review_trigger') or field(note, 'recheck_on')
    if recheck:
        reason += '; legacy recheck trigger: ' + recheck[:220]
    return reason[:650], urls


def recheck_triggers(status):
    if status == 'not_affected':
        return ['image_digest_change', 'advisory_change']
    if status == 'config':
        return ['image_digest_change', 'service_config_change', '30_days']
    if status == 'requires_fix':
        return ['vendor_fix', 'advisory_change', '30_days']
    if status == 'needs_evidence':
        return ['service_config_change', 'advisory_change', '30_days']
    return ['30_days']


def current_expiry(event, maintenance, now):
    # A finite migration may never inherit a stale or long-lived broad window.
    cap = now + 30 * 86400 + 120
    valid = {str(m['maintenanceid']) for m in maintenance}
    times = [int(m.get('active_till') or 0) for m in maintenance]
    for suppression in event.get('suppression_data') or []:
        mid = str(suppression.get('maintenanceid') or '0')
        if mid in ('0', '') or mid in valid:
            times.append(int(suppression.get('suppress_until') or 0))
    return max((value for value in times if now < value <= cap), default=0)


def validate_snapshot(snapshot, now):
    if snapshot.get('inventory_error') or snapshot.get('errors'):
        raise ValueError('scanner inventory or scan errors present')
    if now - snapshot.get('inventory_at', 0) >= 900:
        raise ValueError('scanner inventory stale')
    if not isinstance(snapshot.get('images'), dict) or not isinstance(snapshot.get('reports'), dict):
        raise ValueError('scanner snapshot missing images or reports')


def plan(snapshot, events, maintenances, hostid, now, approved_permanent, skip_existing_new=True):
    validate_snapshot(snapshot, now)
    old_events = {}
    for event in events:
        check = one_check_tag(event)
        if check:
            if check in old_events:
                raise ValueError('duplicate active legacy event check_id ' + check)
            old_events[check] = event
    old_maintenance = {}
    existing_new = set()
    for maintenance in maintenances:
        check = one_check_tag(maintenance)
        if not check:
            continue
        if any(h.get('hostid') == hostid for h in maintenance.get('hosts') or []):
            old_maintenance.setdefault(check, []).append(maintenance)
            if 'HOME107v2 ' in maintenance.get('name', ''):
                existing_new.add(check)
    entries, unmatched, permanent_candidates = [], [], []
    seen_new = set()
    for image, consumers in sorted(snapshot['images'].items()):
        if not FULL_REF.fullmatch(image) or not consumers:
            raise ValueError('invalid current image or consumer list')
        report = snapshot['reports'].get(image)
        if not report or now - report.get('scanned_at', 0) >= 8 * 3600:
            raise ValueError('missing or stale report for ' + image)
        for finding in report.get('findings') or []:
            cve = finding.get('id', '')
            if not CVE.fullmatch(cve):
                raise ValueError('invalid CVE ID in report')
            old = legacy_check_id(image, cve)
            event = old_events.get(old)
            if not event:
                unmatched.append({'image': image, 'cve': cve, 'legacy_check_id': old,
                                  'reason': 'no active legacy event'})
                continue
            if not event.get('name', '').startswith('Critical ' + cve + ' '):
                raise ValueError('legacy event name does not match ' + old)
            prior = [m for m in old_maintenance.get(old, []) if image in (m.get('description') or '')
                     and cve in (m.get('description') or '')]
            note = evidence_note(event, prior)
            permanent = [m for m in prior if int(m.get('active_till') or 0) > now and
                         ('REVIEWED_NOT_AFFECTED' in (m.get('name') or '') or
                          ((m.get('name') or '').startswith('Reviewed ') and
                           ('not applicable' in (m.get('description') or '').lower())))]
            status = review_status(note)
            if status == 'pending' and permanent:
                status = 'not_affected'
            if status == 'not_affected':
                candidate_reason, candidate_urls = record_evidence(note, finding)
                permanent_candidates.append({
                    'image': image, 'cve': cve, 'legacy_check_id': old,
                    'legacy_eventid': str(event['eventid']),
                    'legacy_maintenance_ids': [str(m['maintenanceid']) for m in permanent],
                    'consumers': sorted(set(consumers)), 'original_expiry':
                    min((int(m['active_till']) for m in permanent), default=0),
                    'review_note': note, 'reason': candidate_reason,
                    'evidence_urls': candidate_urls,
                    'evidence_status': ('exact_legacy_record_review_required' if permanent and
                                        candidate_reason and candidate_urls else 'insufficient'),
                    'approved': old in approved_permanent})
            finite_intrinsic = status == 'not_affected' and not permanent
            if finite_intrinsic:
                if old in approved_permanent:
                    raise ValueError('approved permanent review lacks exact old maintenance: ' + old)
                # A review note alone is not durable permanent authorization.
                # Preserve its original finite window and evidence for re-review.
                status = 'needs_evidence'
            elif status == 'not_affected' and old not in approved_permanent:
                unmatched.append({'image': image, 'cve': cve, 'legacy_check_id': old,
                                  'reason': 'permanent evidence needs explicit approval'})
                continue
            expiry = min(int(m['active_till']) for m in permanent) if status == 'not_affected' else current_expiry(event, prior, now)
            if not expiry:
                unmatched.append({'image': image, 'cve': cve, 'legacy_check_id': old,
                                  'reason': 'no live finite expiry to preserve'})
                continue
            reason, urls = record_evidence(note, finding)
            if status == 'not_affected' and (not reason or not urls):
                raise ValueError('permanent review lacks reason or evidence: ' + old)
            for service in sorted(set(consumers)):
                if not isinstance(service, str) or not service:
                    raise ValueError('invalid service identity')
                new = new_check_id(image, cve, service)
                if new in seen_new:
                    raise ValueError('new check_id collision ' + new)
                seen_new.add(new)
                if new in old_events:
                    raise ValueError('new check_id collides with legacy check ' + new)
                if skip_existing_new and new in existing_new:
                    continue
                fingerprint = ((snapshot.get('consumer_fingerprints') or {}).get(image) or {}).get(service, '')
                record = {'schema': 2, 'finding_id': finding_id(image, cve, service),
                          'image': image, 'cve': cve, 'service': service, 'check_id': new,
                          'status': status, 'created_at': now, 'expires_at': expiry,
                          'review_by': now + 30 * 86400 if status == 'not_affected' else now,
                          'reason': reason or 'Legacy review pending reassessment',
                          'evidence_urls': urls, 'recheck_on': recheck_triggers(status),
                          'fingerprint': fingerprint,
                          'legacy_reviewed': review_status(note) != 'pending',
                          'legacy_disposition': review_status(note),
                          'legacy_review_note': note,
                          'legacy_eventid': str(event['eventid']),
                          'legacy_maintenance_ids': [str(m['maintenanceid']) for m in prior],
                          'packages': finding.get('packages', [])[:8],
                          'scanner_url': finding.get('url', '')}
                if status == 'not_affected':
                    record['legacy_revalidation'] = True
                else:
                    record['legacy_backlog'] = True
                description = (f'{status.upper()} | {cve} | {service}\nImage: {image}\n'
                               f'Reason: {record["reason"]}\nEvidence: {", ".join(urls)}\n'
                               f'Recheck: {", ".join(record["recheck_on"])}\nHOME107V2:' +
                               json.dumps(record, separators=(',', ':')))
                entries.append({'legacy_eventid': str(event['eventid']), 'legacy_check_id': old,
                                'old_maintenance_ids': [str(m['maintenanceid']) for m in prior],
                                'image': image, 'cve': cve, 'service': service,
                                'new_check_id': new, 'status': status,
                                'active_till': expiry, 'description': description})
    missing_approved = approved_permanent - {e['legacy_check_id'] for e in entries if e['status'] == 'not_affected'}
    if missing_approved:
        raise ValueError('approved permanent IDs absent from current exact matches: ' + ','.join(sorted(missing_approved)))
    return {'schema': 1, 'generated_at': now, 'hostid': hostid,
            'entries': entries, 'unmatched': unmatched,
            'permanent_candidates': permanent_candidates}


def scanner_snapshot(path=None):
    if path:
        return json.loads(Path(path).read_text())
    code = ('import urllib.request,sys;'
            'sys.stdout.buffer.write(urllib.request.urlopen('
            '"http://security-scanner:8080/snapshot",timeout=15).read(4194305))')
    result = subprocess.run(['kubectl', '-n', 'zabbix', 'exec', 'deployment/collector', '--',
                             'python', '-c', code], capture_output=True, check=True)
    if len(result.stdout) > 4 * 1024 * 1024:
        raise ValueError('scanner snapshot exceeds 4 MiB')
    return json.loads(result.stdout)


def api_state(api):
    hosts = api.call('host.get', {'filter': {'host': 'HomePBP'}, 'output': ['hostid']})
    if len(hosts) != 1:
        raise ValueError('HomePBP host missing or ambiguous')
    hostid = hosts[0]['hostid']
    events = api.call('problem.get', {'hostids': [hostid], 'output': ['eventid', 'name', 'suppressed'],
                                      'selectTags': 'extend', 'selectAcknowledges': 'extend',
                                      'selectSuppressionData': 'extend', 'limit': 2000})
    maintenances = api.call('maintenance.get', {'output': ['maintenanceid', 'name', 'description',
                                                           'active_till', 'maintenance_type'],
                                                 'selectTags': 'extend', 'selectHosts': ['hostid'],
                                                 'limit': 5000})
    return hostid, events, maintenances


def create_maintenance(api, hostid, entry, now):
    check = entry['new_check_id']
    if not CHECK.fullmatch(check) or entry['active_till'] <= now:
        raise ValueError('invalid check ID or expired migration entry')
    name = f'HOME107v2 {entry["status"].upper()} {entry["cve"]} {check}'
    params = {'name': name, 'description': entry['description'],
              'maintenance_type': 0, 'active_since': now // 60 * 60,
              'active_till': entry['active_till'], 'hosts': [{'hostid': hostid}],
              'tags_evaltype': 0, 'tags': [{'tag': 'check_id', 'operator': 0, 'value': check}],
              'timeperiods': [{'timeperiod_type': 2, 'every': 1, 'start_time': 0,
                              'period': 86400}]}
    result = api.call('maintenance.create', params)
    return str(result['maintenanceids'][0])


def exact_existing(maintenances, hostid, entry):
    """Find only a review record identical to the approved plan entry."""
    check = entry['new_check_id']
    matches = [m for m in maintenances if one_check_tag(m) == check]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError('duplicate exact-service maintenance for ' + check)
    row = matches[0]
    expected_name = f'HOME107v2 {entry["status"].upper()} {entry["cve"]} {check}'
    tags = row.get('tags') or []
    hosts = row.get('hosts') or []
    if (row.get('name') != expected_name or row.get('description') != entry['description'] or
            int(row.get('active_till') or 0) != int(entry['active_till']) // 60 * 60 or
            len(tags) != 1 or tags[0].get('operator') not in ('0', 0) or
            len(hosts) != 1 or str(hosts[0].get('hostid')) != str(hostid)):
        raise ValueError('existing exact-service maintenance differs from approved plan: ' + check)
    return str(row['maintenanceid'])


def write_progress(path, progress):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(progress, indent=2))
    temporary.replace(path)


def audit_cutover(saved, events, maintenances, now=None):
    """Verify active v2 events are suppressed by their exact review records."""
    now = int(time.time()) if now is None else now
    hostid = str(saved['hostid'])
    event_by_check = {}
    for event in events:
        check = one_check_tag(event)
        if check:
            event_by_check.setdefault(check, []).append(event)
    present, absent, unsuppressed, wrong_maintenance = [], [], [], []
    for entry in saved['entries']:
        check = entry['new_check_id']
        mid = exact_existing(maintenances, hostid, entry)
        if not mid:
            wrong_maintenance.append(check)
            continue
        matched = event_by_check.get(check, [])
        if len(matched) != 1:
            absent.append(check)
            continue
        event = matched[0]
        if str(event.get('suppressed')) not in ('1', 'True', 'true'):
            unsuppressed.append(check)
            continue
        suppression = event.get('suppression_data') or []
        if not any(str(item.get('maintenanceid')) == mid and
                   int(item.get('suppress_until') or 0) > now
                   for item in suppression):
            wrong_maintenance.append(check)
            continue
        present.append(check)
    result = {'expected': len(saved['entries']), 'verified': len(present),
              'missing_event': absent, 'unsuppressed': unsuppressed,
              'wrong_or_missing_maintenance': wrong_maintenance}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18080')
    parser.add_argument('--snapshot-file', help='Use a captured scanner snapshot for offline dry-run')
    parser.add_argument('--approved-permanent-ids', help='Text file with one audited legacy check ID per line')
    parser.add_argument('--plan-out', type=Path, help='Write the dry-run plan as JSON')
    parser.add_argument('--apply-plan', type=Path, help='Apply a fresh, reviewed plan after live revalidation')
    parser.add_argument('--verify-cutover', type=Path,
                        help='Read-only audit of exact event suppression after per-service collector cutover')
    args = parser.parse_args()
    if args.verify_cutover:
        if any((args.apply_plan, args.snapshot_file, args.plan_out, args.approved_permanent_ids)):
            parser.error('--verify-cutover cannot be combined with plan/apply options')
        saved = json.loads(args.verify_cutover.read_text())
        credential = bootstrap.read_secret('baloo', 'zabbix-mcp')
        if not credential or not credential.get('read-token'):
            raise SystemExit('Baloo Zabbix read token is unavailable')
        api = bootstrap.API(args.url)
        api.token = credential['read-token']
        hostid, events, maintenances = api_state(api)
        if str(hostid) != str(saved['hostid']):
            raise SystemExit('HomePBP host changed since migration plan')
        result = audit_cutover(saved, events, maintenances)
        print(json.dumps(result))
        if result['verified'] != result['expected']:
            raise SystemExit(1)
        return
    if args.apply_plan and (args.snapshot_file or args.plan_out or args.approved_permanent_ids):
        parser.error('--apply-plan cannot be combined with plan input options')
    approved = set()
    if args.apply_plan:
        saved = json.loads(args.apply_plan.read_text())
        progress_path = args.apply_plan.with_suffix('.progress.json')
        if not progress_path.exists() and time.time() - saved['generated_at'] > 900:
            raise SystemExit('Plan is older than 15 minutes; regenerate')
        approved = {e['legacy_check_id'] for e in saved['entries'] if e['status'] == 'not_affected'}
        credential = bootstrap.read_secret('zabbix', 'security-review-reconciler')
        if not credential or not credential.get('api-token'):
            raise SystemExit('Run bootstrap-zabbix.py --apply --security-review-only first')
        token = credential['api-token']
    else:
        if args.approved_permanent_ids:
            approved = {line.strip() for line in Path(args.approved_permanent_ids).read_text().splitlines()
                        if line.strip() and not line.lstrip().startswith('#')}
            if any(not CHECK.fullmatch(value) for value in approved):
                raise SystemExit('Approved permanent list contains an invalid check ID')
        credential = bootstrap.read_secret('baloo', 'zabbix-mcp')
        if not credential or not credential.get('read-token'):
            raise SystemExit('Baloo Zabbix read token is unavailable')
        token = credential['read-token']
    api = bootstrap.API(args.url)
    api.token = token
    snapshot = scanner_snapshot(args.snapshot_file)
    if args.apply_plan:
        validate_snapshot(snapshot, int(time.time()))
    hostid, events, maintenances = api_state(api)
    current = plan(snapshot, events, maintenances, hostid,
                   saved['generated_at'] if args.apply_plan else int(time.time()), approved,
                   skip_existing_new=not args.apply_plan)
    if args.apply_plan:
        if current != saved:
            raise SystemExit('Live scanner/Zabbix state changed; regenerate and review the plan')
        progress = json.loads(progress_path.read_text()) if progress_path.exists() else {'created': [], 'failed': []}
        completed = {row['new_check_id']: row['maintenanceid'] for row in progress['created']}
        newly_created = 0
        for entry in saved['entries']:
            check = entry['new_check_id']
            try:
                mid = exact_existing(maintenances, hostid, entry)
                if check in completed and mid != str(completed[check]):
                    raise ValueError('checkpoint differs from live maintenance for ' + check)
                if not mid:
                    mid = create_maintenance(api, hostid, entry, int(time.time()))
                    newly_created += 1
                    # A failed checkpoint write is safe to retry: the next run
                    # discovers and validates the live maintenance by check ID.
                    maintenances.append({'maintenanceid': mid, 'name':
                                         f'HOME107v2 {entry["status"].upper()} {entry["cve"]} {check}',
                                         'description': entry['description'],
                                         'active_till': entry['active_till'],
                                         'tags': [{'tag': 'check_id', 'operator': '0', 'value': check}],
                                         'hosts': [{'hostid': hostid}]})
                if check not in completed:
                    progress['created'].append({'new_check_id': check, 'maintenanceid': mid})
                    completed[check] = mid
                progress['failed'] = [f for f in progress['failed'] if f['new_check_id'] != check]
                write_progress(progress_path, progress)
            except Exception as error:
                progress['failed'] = [f for f in progress['failed'] if f['new_check_id'] != check]
                progress['failed'].append({'new_check_id': check, 'error': type(error).__name__})
                write_progress(progress_path, progress)
                raise
        print(f'Completed {len(progress["created"])} exact-service review maintenances '
              f'({newly_created} created this run); legacy records retained. '
              'Run --verify-cutover after per-service collector rollout.')
    else:
        if args.plan_out:
            args.plan_out.write_text(json.dumps(current, indent=2))
        counts = {status: sum(e['status'] == status for e in current['entries'])
                  for status in ('not_affected', 'config', 'needs_evidence', 'requires_fix', 'pending')}
        print(json.dumps({'entries': len(current['entries']), 'status_counts': counts,
                          'legacy_pairs_imported': len({e['legacy_check_id'] for e in current['entries']}),
                          'permanent_candidates': len(current['permanent_candidates']),
                          'unmatched': len(current['unmatched']), 'plan_out': str(args.plan_out or '')}))


if __name__ == '__main__':
    main()
