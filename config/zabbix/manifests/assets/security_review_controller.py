#!/usr/bin/env python3
"""Deterministic, exact-finding Zabbix review and notification controller.

The scanner supplies evidence; Baloo submits bounded review decisions.  Only
this process holds the Zabbix write token.  Raw CVE checks are dashboard-only,
so an API or maintenance propagation failure cannot send a raw CVE to WhatsApp.
"""
import copy
import datetime as dt
import hashlib
import hmac
import http.server
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

SCANNER_URL = os.environ.get('SCANNER_URL', 'http://security-scanner.zabbix.svc.cluster.local:8080/snapshot')
ZABBIX_URL = os.environ.get('ZABBIX_URL', 'http://zabbix-web.zabbix.svc.cluster.local/api_jsonrpc.php')
STATE_PATH = Path(os.environ.get('REVIEW_STATE', '/state/review.json'))
ZABBIX_TOKEN = Path(os.environ.get('ZABBIX_TOKEN_FILE', '/zabbix-credentials/api-token'))
BALOO_TOKEN = Path(os.environ.get('BALOO_TOKEN_FILE', '/review-credentials/baloo-token'))
COLLECTOR_TOKEN = Path(os.environ.get('COLLECTOR_TOKEN_FILE', '/review-credentials/collector-token'))
APPLY = os.environ.get('REVIEW_APPLY', 'false').lower() == 'true'
MAX_HTTP = 4 * 1024 * 1024
MAX_FINDINGS = 2000
TEMP_SECONDS = 30 * 86400
REVIEW_SECONDS = 3600
PERMANENT_TILL = int(dt.datetime(2037, 12, 31, tzinfo=dt.timezone.utc).timestamp())
MARKER = '\nHOME107V2:'
IMAGE = re.compile(r'^[a-z0-9][a-z0-9._:/-]*@sha256:[a-f0-9]{64}$')
CVE = re.compile(r'^(?:CVE-\d{4}-\d{4,}|GHSA-[a-z0-9-]{10,})$', re.I)
HEX20 = re.compile(r'^[a-f0-9]{20}$')
HEX64 = re.compile(r'^[a-f0-9]{64}$')
DISPOSITIONS = {'not_affected', 'config', 'needs_evidence', 'requires_fix', 'urgent'}
RECHECKS = {'image_digest_change', 'service_config_change', 'advisory_change',
            'vendor_fix', '7_days', '30_days'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect())


def bounded_json(url, token=None, data=None, limit=MAX_HTTP):
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if data is not None:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, headers=headers, data=(json.dumps(data).encode() if data is not None else None))
    with OPENER.open(request, timeout=10) as response:
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError('response exceeds limit')
    return json.loads(body)


def finding_id(image, cve, service):
    value = json.dumps(['security-finding-v1', image, cve, service], separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(value.encode()).hexdigest()


def raw_check_id(image, cve, service):
    # Keep the exact v2 collector identity stable across staged rollouts. The
    # collector can be on the previous ConfigMap while this controller starts.
    value = json.dumps(['security-raw-v2', image, cve, service], separators=(',', ':'))
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def finding_rows(snapshot, now):
    images, recent, reports = (snapshot.get('images'), snapshot.get('recent_images', {}),
                               snapshot.get('reports'))
    if not isinstance(images, dict) or not isinstance(recent, dict) or not isinstance(reports, dict):
        raise ValueError('invalid scanner snapshot')
    result = {}
    refs = set(images) | set(recent)
    for image in sorted(refs):
        if not IMAGE.fullmatch(image):
            raise ValueError('invalid scanner image identity')
        services = set(images.get(image, []))
        for service, last_seen in recent.get(image, {}).items():
            if not isinstance(last_seen, (float, int)) or last_seen > now + 60:
                raise ValueError('invalid recent exposure timestamp')
            if 0 <= now - last_seen < 7 * 86400:
                services.add(service)
        report = reports.get(image, {})
        scanned_at = report.get('scanned_at', 0)
        if (not isinstance(scanned_at, (float, int)) or
                not 0 <= now - scanned_at < 8 * 3600):
            continue
        for finding in report.get('findings', []):
            cve = finding.get('id', '')
            if not CVE.fullmatch(cve):
                continue
            for service in sorted(services):
                if not isinstance(service, str) or not 1 <= len(service) <= 240 or '\n' in service:
                    raise ValueError('invalid scanner service identity')
                check = raw_check_id(image, cve, service)
                key = finding_id(image, cve, service)
                result[key] = {'finding_id': key, 'image': image, 'cve': cve,
                               'service': service, 'check_id': check,
                               'packages': finding.get('packages', [])[:8],
                               'scanner_url': finding.get('url', ''),
                               'first_seen': snapshot.get('first_seen', {}).get(image, now)}
                if len(result) > MAX_FINDINGS:
                    raise ValueError('scanner finding inventory exceeds limit')
    return result


def description(meta):
    title = f"{meta['status'].upper()} | {meta['cve']} | {meta['service']}"
    summary = (f"Image: {meta['image']}\nReason: {meta.get('reason', '')}\n"
               f"Evidence: {', '.join(meta.get('evidence_urls', [])) or 'scanner report pending review'}\n"
               f"Recheck: {', '.join(meta.get('recheck_on', [])) or 'within one hour'}")
    return title + '\n' + summary + MARKER + json.dumps(meta, sort_keys=True, separators=(',', ':'))


def parse_description(value):
    if not isinstance(value, str) or MARKER not in value:
        return None
    try:
        meta = json.loads(value.rsplit(MARKER, 1)[1])
    except ValueError:
        return None
    return meta if meta.get('schema') == 2 and HEX64.fullmatch(meta.get('finding_id', '')) else None


def maintenance_payload(hostid, row, meta, start, end):
    start = int(start // 60 * 60)
    end = int(end // 60 * 60)
    return {'name': f"HOME107v2 {meta['status'].upper()} {row['cve']} {row['check_id']}",
            'description': description(meta), 'maintenance_type': 0,
            'active_since': start, 'active_till': end,
            'hosts': [{'hostid': hostid}], 'tags_evaltype': 0,
            'tags': [{'tag': 'check_id', 'operator': 0, 'value': row['check_id']}],
            'timeperiods': [{'timeperiod_type': 2, 'every': 1, 'start_time': 0, 'period': 86400}]}


class Zabbix:
    def __init__(self, url=ZABBIX_URL, token_path=ZABBIX_TOKEN):
        self.url, self.token_path = url, Path(token_path)
        self.invalid_maintenance_count = 0

    def call(self, method, params):
        if method not in {'host.get', 'maintenance.get', 'maintenance.create', 'maintenance.update',
                          'problem.get', 'event.acknowledge'}:
            raise ValueError('Zabbix method not allowed')
        payload = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
        result = bounded_json(self.url, self.token_path.read_text().strip(), payload)
        if 'error' in result:
            raise RuntimeError(method + ': ' + str(result['error'].get('message', 'failed')))
        return result['result']

    def host(self):
        rows = self.call('host.get', {'filter': {'host': 'HomePBP'}, 'output': ['hostid']})
        if len(rows) != 1:
            raise ValueError('HomePBP host identity ambiguous')
        return rows[0]['hostid']

    def maintenances(self, hostid):
        rows = self.call('maintenance.get', {'hostids': [hostid], 'output': 'extend',
                                             'selectTags': 'extend', 'selectHosts': ['hostid'],
                                             'selectTimeperiods': 'extend'})
        by_check = {}
        self.invalid_maintenance_count = 0
        for row in rows:
            if not row.get('name', '').startswith('HOME107v2 '):
                continue
            tags = row.get('tags') or []
            hosts = row.get('hosts') or []
            periods = row.get('timeperiods') or []
            check_id = next((tag.get('value') for tag in tags if tag.get('tag') == 'check_id'), None)
            if not isinstance(check_id, str) or not HEX20.fullmatch(check_id):
                self.invalid_maintenance_count += 1
                name_check = row['name'].rsplit(' ', 1)[-1]
                if HEX20.fullmatch(name_check):
                    by_check[name_check] = {'_invalid': 'check ID tag missing or invalid'}
                continue
            if check_id in by_check:
                by_check[check_id] = {'_invalid': 'duplicate check ID'}
                self.invalid_maintenance_count += 1
                continue
            valid = (len(tags) == 1 and tags[0].get('tag') == 'check_id' and
                     tags[0].get('operator') in ('0', 0) and len(hosts) == 1 and
                     str(hosts[0].get('hostid')) == str(hostid) and
                     str(row.get('maintenance_type')) == '0' and len(periods) == 1 and
                     str(periods[0].get('timeperiod_type')) == '2' and
                     str(periods[0].get('every')) == '1' and
                     str(periods[0].get('start_time')) == '0' and
                     str(periods[0].get('period')) == '86400')
            if not valid:
                by_check[check_id] = {'_invalid': 'maintenance scope invalid'}
                self.invalid_maintenance_count += 1
                continue
            by_check[check_id] = row
        return by_check

    def problems(self, hostid):
        rows, cursor = [], None
        for _ in range(10):
            params = {'hostids': [hostid], 'recent': False,
                      'output': ['eventid', 'name', 'suppressed', 'acknowledged'],
                      'selectTags': 'extend', 'selectAcknowledges': 'extend',
                      'selectSuppressionData': 'extend', 'limit': 1000,
                      'sortfield': 'eventid', 'sortorder': 'ASC'}
            if cursor is not None:
                params['eventid_from'] = str(cursor)
            page = self.call('problem.get', params)
            rows.extend(page)
            if len(page) < 1000:
                break
            last = int(page[-1]['eventid'])
            if cursor is not None and last < cursor:
                raise ValueError('problem pagination did not advance')
            cursor = last + 1
        else:
            raise ValueError('problem inventory exceeds limit')
        result = {}
        for row in rows:
            check_ids = [tag.get('value') for tag in row.get('tags', []) if tag.get('tag') == 'check_id']
            if len(check_ids) == 1:
                result.setdefault(check_ids[0], []).append(row)
        return result


def load_state(path):
    if not path.exists():
        return None
    state = json.loads(path.read_text())
    if state.get('schema') != 1 or not isinstance(state.get('seen_images'), dict):
        raise ValueError('review state schema invalid')
    return state


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, separators=(',', ':'), sort_keys=True))
    temporary.replace(path)


def initial_meta(row, now, fingerprint='', intake='new_finding'):
    return {'schema': 2, 'finding_id': row['finding_id'], 'image': row['image'],
            'cve': row['cve'], 'service': row['service'], 'check_id': row['check_id'],
            'status': 'pending', 'created_at': now, 'expires_at': now + TEMP_SECONDS,
            'review_by': now + REVIEW_SECONDS, 'reason':
            'Automatically queued for Baloo review; this finite mute is not a safety claim.',
            'evidence_urls': ([row['scanner_url']] if row['scanner_url'].startswith('https://') else []),
            'recheck_on': ['30_days'], 'fingerprint': fingerprint,
            'packages': row['packages'], 'scanner_url': row['scanner_url'],
            'intake': intake}


def validate_record(meta, row, maintenance):
    for key in ('finding_id', 'image', 'cve', 'service', 'check_id'):
        if meta.get(key) != row[key]:
            raise ValueError('review record identity mismatch')
    if meta.get('status') not in DISPOSITIONS | {'pending'}:
        raise ValueError('review record status invalid')
    if int(meta.get('expires_at', 0)) != int(maintenance['active_till']):
        # Zabbix rounds maintenance bounds down to whole minutes.
        if abs(int(meta.get('expires_at', 0)) - int(maintenance['active_till'])) >= 60:
            raise ValueError('review record expiry mismatch')


def review_note(meta):
    return (f"HOME107V2 finding_id={meta['finding_id']} status={meta['status'].upper()} "
            f"revision={review_revision(meta)} reviewed_at={meta.get('reviewed_at', '')} "
            f"image={meta['image']} cve={meta['cve']} service={meta['service']} "
            f"reason={meta['reason']} evidence={', '.join(meta.get('evidence_urls', []))} "
            f"attack_path={meta.get('attack_path', '')} impact={meta.get('impact', '')} "
            f"action={meta.get('action_summary', '')} "
            f"recheck={','.join(meta.get('recheck_on', []))}")[:3900]


def review_revision(meta):
    fields = ('status', 'reason', 'evidence_urls', 'reviewed_at', 'recheck_on',
              'action_summary', 'attack_path', 'impact', 'fingerprint', 'packages', 'scanner_url')
    value = json.dumps({field: meta.get(field) for field in fields},
                       sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def printable(value, limit):
    return ' '.join(''.join(character if character.isprintable() else ' '
                            for character in value).split())[:limit]


def review_due(meta, now):
    return meta.get('status') == 'pending' or int(meta.get('review_by', 0)) <= now


def evidence_recent(meta, now):
    try:
        reviewed = dt.datetime.fromisoformat(meta['reviewed_at'].replace('Z', '+00:00')).timestamp()
    except (KeyError, AttributeError, ValueError):
        return False
    return 0 <= now - reviewed <= 365 * 86400


class Controller:
    def __init__(self, api=None, state_path=STATE_PATH, now=time.time, apply=APPLY):
        self.api = api or Zabbix()
        self.path = Path(state_path)
        self.now = now
        self.apply = apply
        self.lock = threading.RLock()
        self.state = load_state(self.path)
        self.rows = {}
        self.records = {}
        self.degraded_ids = set()
        self.snapshot_data = {'generated_at': 0, 'healthy': False, 'error': 'not_started',
                              'queue_depth': 0, 'overdue_count': 0, 'unmuted_count': 0,
                              'pending_count': 0, 'ready_check_ids': [], 'urgent': []}

    def scanner(self):
        snapshot = bounded_json(SCANNER_URL)
        inventory_at = snapshot.get('inventory_at', 0)
        if (not isinstance(inventory_at, (float, int)) or
                self.now() - inventory_at > 15 * 60 or snapshot.get('inventory_error')):
            raise ValueError('scanner inventory stale or failed')
        watch_at = snapshot.get('watch_at')
        if (snapshot.get('watch_error') or
                (watch_at is not None and
                 (not isinstance(watch_at, (float, int)) or self.now() - watch_at > 15 * 60))):
            raise ValueError('scanner watch stale or failed')
        degraded = set(snapshot.get('errors', {}))
        for image in set(snapshot.get('images', {})) | set(snapshot.get('recent_images', {})):
            report = snapshot.get('reports', {}).get(image, {})
            scanned_at = report.get('scanned_at', 0)
            if not isinstance(scanned_at, (float, int)) or not 0 <= self.now() - scanned_at < 8 * 3600:
                degraded.add(image)
        snapshot['_degraded_refs'] = sorted(degraded)
        snapshot['_coverage_fault_count'] = len(degraded) + len(snapshot.get('unresolved', []))
        return snapshot

    def initialize(self):
        with self.lock:
            if self.path.exists():
                raise ValueError('review state already initialized')
            snapshot = self.scanner()
            images = set(snapshot.get('images', {})) | set(snapshot.get('recent_images', {}))
            first_seen = snapshot.get('first_seen', {})
            now = int(self.now())
            state = {'schema': 1, 'initialized_at': now,
                     'seen_images': {image: int(first_seen.get(image, now)) for image in images},
                     'known_rows': finding_rows(snapshot, now)}
            save_state(self.path, state)
            self.state = state
            return len(images)

    def _note_problems(self, by_check, records):
        faults = 0
        for check_id, problems in by_check.items():
            meta = records.get(check_id)
            if not meta:
                continue
            marker = (f"HOME107V2 finding_id={meta['finding_id']} status={meta['status'].upper()} "
                      f"revision={review_revision(meta)}")
            for problem in problems:
                if any(marker in a.get('message', '') for a in problem.get('acknowledges', [])):
                    continue
                # Pending is represented by the exact maintenance record, not
                # by undoing a human's acknowledgement of the raw event.
                action = 4 if meta['status'] == 'pending' else 6
                try:
                    self.api.call('event.acknowledge', {'eventids': [problem['eventid']],
                                                        'action': action, 'message': review_note(meta)})
                except Exception:
                    faults += 1
        return faults

    def tick(self):
        with self.lock:
            now = int(self.now())
            try:
                if self.state is None:
                    self.state = load_state(self.path)
                if self.state is None:
                    raise ValueError('review state missing; explicit initialization required')
                snapshot = self.scanner()
                fresh_rows = finding_rows(snapshot, now)
                refs = set(snapshot.get('images', {})) | set(snapshot.get('recent_images', {}))
                degraded_refs = set(snapshot['_degraded_refs'])
                known_rows = self.state.setdefault('known_rows', {})
                rows = dict(fresh_rows)
                for key, old_row in known_rows.items():
                    if old_row['image'] in degraded_refs and old_row['image'] in refs:
                        rows.setdefault(key, old_row)
                self.degraded_ids = {key for key, row in rows.items() if row['image'] in degraded_refs}
                self.state['known_rows'] = {key: row for key, row in rows.items() if row['image'] in refs}
                new_images = refs - set(self.state['seen_images'])
                for image in refs:
                    if image not in self.state['seen_images']:
                        self.state['seen_images'][image] = int(snapshot.get('first_seen', {}).get(image, now))
                save_state(self.path, self.state)
                hostid = self.api.host()
                maintenances = self.api.maintenances(hostid)
                preexisting = set(maintenances)
                problems = self.api.problems(hostid)
                records = {}
                ready_check_ids = []
                missing = 0
                renewal_required = 0
                record_faults = getattr(self.api, 'invalid_maintenance_count', 0)
                for key, row in rows.items():
                    check_id = row['check_id']
                    current = maintenances.get(check_id)
                    fingerprint = (snapshot.get('consumer_fingerprints', {})
                                   .get(row['image'], {}).get(row['service'], ''))
                    if current is None:
                        if key in self.degraded_ids:
                            # Never create a review from stale retained evidence.
                            continue
                        missing += 1
                        if not self.apply:
                            continue
                        meta = initial_meta(row, now, fingerprint,
                                            'new_digest' if row['image'] in new_images else
                                            'new_advisory_or_service')
                        payload = maintenance_payload(hostid, row, meta, now - 60, meta['expires_at'])
                        try:
                            result = self.api.call('maintenance.create', payload)
                        except Exception:
                            record_faults += 1
                            continue
                        current = {**payload, 'maintenanceid': result['maintenanceids'][0]}
                        maintenances[check_id] = current
                    if current.get('_invalid'):
                        continue
                    meta = parse_description(current.get('description', ''))
                    if not meta:
                        record_faults += 1
                        continue
                    try:
                        validate_record(meta, row, current)
                    except (ValueError, TypeError, KeyError):
                        record_faults += 1
                        continue
                    if (meta.get('packages') != row['packages'] or
                            meta.get('scanner_url') != row['scanner_url']):
                        # A Trivy database refresh can change package/fix/source data
                        # for the same CVE. Re-review the exact finding and shorten a
                        # prior permanent exception to the usual finite window.
                        end = min(int(current['active_till']), now + TEMP_SECONDS)
                        meta = {**meta, 'status': 'pending', 'review_by': now + REVIEW_SECONDS,
                                'expires_at': end, 'reason':
                                'Scanner advisory or package evidence changed; prior review must be repeated.',
                                'packages': row['packages'], 'scanner_url': row['scanner_url'],
                                'evidence_urls': ([row['scanner_url']] if row['scanner_url'].startswith('https://') else []),
                                'recheck_on': ['advisory_change', '30_days'],
                                'legacy_backlog': False}
                        if not self.apply or key in self.degraded_ids:
                            record_faults += 1
                            continue
                        try:
                            self.api.call('maintenance.update', {
                                'maintenanceid': current['maintenanceid'],
                                'name': f"HOME107v2 PENDING {row['cve']} {check_id}",
                                'active_till': end, 'description': description(meta)})
                        except Exception:
                            record_faults += 1
                            continue
                        current = {**current, 'active_till': end}
                    if meta['status'] in {'config', 'needs_evidence', 'requires_fix'} and fingerprint and fingerprint != meta.get('fingerprint', ''):
                        meta = {**meta, 'status': 'pending', 'review_by': now + REVIEW_SECONDS,
                                'reason': 'Workload template fingerprint changed; prior configuration review must be repeated.',
                                'fingerprint': fingerprint, 'recheck_on': ['service_config_change', '30_days'],
                                'legacy_backlog': False}
                        if self.apply:
                            try:
                                self.api.call('maintenance.update', {'maintenanceid': current['maintenanceid'],
                                                                     'name': f"HOME107v2 PENDING {row['cve']} {check_id}",
                                                                     'description': description(meta)})
                            except Exception:
                                record_faults += 1
                                continue
                    records[check_id] = meta
                    if (meta['status'] == 'not_affected' and
                            int(current['active_till']) - now < 2 * 365 * 86400):
                        if not evidence_recent(meta, now) or not self.apply or key in self.degraded_ids:
                            renewal_required += 1
                        else:
                            renewed_end = now + 10 * 365 * 86400
                            renewed_meta = {**meta, 'expires_at': renewed_end}
                            try:
                                self.api.call('maintenance.update', {
                                    'maintenanceid': current['maintenanceid'],
                                    'active_till': renewed_end, 'description': description(renewed_meta)})
                            except Exception:
                                renewal_required += 1
                            else:
                                meta = renewed_meta
                                records[check_id] = meta
                                current = {**current, 'active_till': renewed_end}
                    if (check_id in preexisting and
                            int(current['active_since']) <= now < int(current['active_till'])):
                        ready_check_ids.append(check_id)
                if self.apply:
                    record_faults += self._note_problems(problems, records)
                unmuted = sum(1 for check_id in records for problem in problems.get(check_id, [])
                               if str(problem.get('suppressed')) != '1' and
                               now - int(records[check_id].get('created_at', now)) > 300 and
                               int(records[check_id].get('expires_at', 0)) > now)
                urgent = [{'finding_id': meta['finding_id'], 'image': meta['image'],
                           'cve': meta['cve'], 'service': meta['service'], 'check_id': meta['check_id'],
                           'detail': printable(meta['reason'], 1000),
                           'action_summary': printable(meta.get('action_summary', ''), 240),
                           'reviewed_at': meta.get('reviewed_at', '')}
                          for meta in records.values() if meta['status'] == 'urgent']
                due = [meta for meta in records.values() if review_due(meta, now)]
                overdue = sum(1 for meta in records.values() if
                              int(meta['expires_at']) <= now or
                              (review_due(meta, now) and now > int(meta.get('review_by', now)) and
                               not meta.get('legacy_backlog')))
                expiring = sum(1 for meta in records.values() if meta['status'] == 'not_affected' and
                               int(meta['expires_at']) - now < 90 * 86400)
                self.rows, self.records = rows, records
                self.snapshot_data = {'generated_at': now, 'healthy': not (missing and not self.apply),
                                      'error': 'apply_disabled' if missing and not self.apply else '',
                                      'queue_depth': len(due),
                                      'overdue_count': overdue + renewal_required + expiring + record_faults +
                                      snapshot['_coverage_fault_count'],
                                      'pending_count': sum(1 for meta in records.values() if meta['status'] == 'pending'),
                                      'unmuted_count': unmuted,
                                      'ready_check_ids': sorted(ready_check_ids), 'urgent': urgent}
            except Exception as error:
                self.snapshot_data = {'generated_at': now, 'healthy': False,
                                      'error': type(error).__name__, 'queue_depth': 0,
                                      'overdue_count': 0, 'pending_count': 0, 'unmuted_count': 0,
                                      'ready_check_ids': [], 'urgent': []}
            return copy.deepcopy(self.snapshot_data)

    def queue(self, limit=20, offset=0):
        with self.lock:
            now = int(self.now())
            rows = []
            for row in self.rows.values():
                meta = self.records.get(row['check_id'])
                if not meta or not review_due(meta, now) or row['finding_id'] in self.degraded_ids:
                    continue
                rows.append({**row, 'status': meta['status'], 'review_by': meta['review_by'],
                             'reason': meta['reason'], 'evidence_urls': meta.get('evidence_urls', []),
                             'fingerprint': meta.get('fingerprint', ''),
                             'legacy_backlog': bool(meta.get('legacy_backlog', False)),
                             'legacy_revalidation': bool(meta.get('legacy_revalidation', False))})
            rows.sort(key=lambda item: (0 if item['status'] == 'pending' and not item['legacy_backlog'] else
                                        2 if item['legacy_backlog'] else
                                        3 if item['legacy_revalidation'] else 1,
                                        item['review_by'], item['finding_id']))
            return {'findings': rows[offset:offset + limit], 'next_offset':
                    offset + limit if offset + limit < len(rows) else None, 'total': len(rows)}

    def submit_review(self, proposal):
        if not isinstance(proposal, dict) or not set(proposal).issubset({
                'finding_id', 'image', 'cve', 'service', 'check_id', 'disposition',
                'reason', 'evidence_urls', 'reviewed_at', 'recheck_on', 'action_summary',
                'attack_path', 'impact'}) or not {
                'finding_id', 'image', 'cve', 'service', 'check_id', 'disposition',
                'reason', 'evidence_urls', 'reviewed_at', 'recheck_on'}.issubset(proposal):
            raise ValueError('review fields invalid')
        disposition = proposal['disposition']
        if disposition not in DISPOSITIONS:
            raise ValueError('review disposition invalid')
        image, cve, service = proposal['image'], proposal['cve'], proposal['service']
        if not (isinstance(image, str) and IMAGE.fullmatch(image) and
                isinstance(cve, str) and CVE.fullmatch(cve) and
                isinstance(service, str) and 1 <= len(service) <= 240):
            raise ValueError('review identity invalid')
        key = finding_id(image, cve, service)
        check_id = raw_check_id(image, cve, service)
        if (proposal['finding_id'] != key or not HEX64.fullmatch(proposal['finding_id']) or
                proposal['check_id'] != check_id or not HEX20.fullmatch(proposal['check_id'])):
            raise ValueError('review identity stale or mismatched')
        reason = proposal['reason']
        urls = proposal['evidence_urls']
        recheck = proposal['recheck_on']
        if not isinstance(reason, str) or not 40 <= len(reason.strip()) <= 2000 or '\x00' in reason:
            raise ValueError('review reason invalid')
        if (not isinstance(urls, list) or not 1 <= len(urls) <= 8 or
                any(not isinstance(url, str) or not url.startswith('https://') or len(url) > 300 for url in urls)):
            raise ValueError('review evidence URLs invalid')
        if (not isinstance(recheck, list) or not 1 <= len(recheck) <= 5 or
                len(recheck) != len(set(recheck)) or set(recheck) - RECHECKS):
            raise ValueError('review recheck triggers invalid')
        if disposition == 'not_affected' and (len(reason) < 80 or len(urls) < 2 or
                                              'service_config_change' in recheck):
            raise ValueError('permanent review needs intrinsic evidence')
        action_summary = proposal.get('action_summary', '')
        attack_path = proposal.get('attack_path', '')
        impact = proposal.get('impact', '')
        if (disposition == 'urgent' and
                (not isinstance(action_summary, str) or
                 not 20 <= len(printable(action_summary, 241)) <= 240 or
                 not isinstance(attack_path, str) or not 40 <= len(printable(attack_path, 501)) <= 500 or
                 not isinstance(impact, str) or not 30 <= len(printable(impact, 301)) <= 300 or
                 len(urls) < 2 or len(reason.strip()) < 80 or
                 any('\x00' in item for item in (action_summary, attack_path, impact)))):
            raise ValueError('urgent review needs reachability, impact, action and sources')
        if action_summary and (not isinstance(action_summary, str) or len(action_summary) > 240):
            raise ValueError('review action summary invalid')
        if (attack_path and (not isinstance(attack_path, str) or len(attack_path) > 500) or
                impact and (not isinstance(impact, str) or len(impact) > 300)):
            raise ValueError('review exposure fields invalid')
        try:
            reviewed_at = dt.datetime.fromisoformat(proposal['reviewed_at'].replace('Z', '+00:00'))
        except (AttributeError, ValueError) as error:
            raise ValueError('review timestamp invalid') from error
        if reviewed_at.tzinfo is None or abs(reviewed_at.timestamp() - self.now()) > 3600:
            raise ValueError('review timestamp stale')
        with self.lock:
            fresh = self.tick()
            if not fresh['healthy'] or not self.apply:
                raise RuntimeError('review controller unavailable or apply disabled')
            row = self.rows.get(key)
            if not row or row['check_id'] != check_id or key in self.degraded_ids:
                raise ValueError('finding no longer active')
            hostid = self.api.host()
            current = self.api.maintenances(hostid).get(check_id)
            if not current:
                raise RuntimeError('exact maintenance missing')
            old = parse_description(current.get('description', ''))
            if not old:
                raise ValueError('current review record invalid')
            validate_record(old, row, current)
            now = int(self.now())
            if disposition == 'not_affected':
                expires = PERMANENT_TILL
                review_by = now + 365 * 86400
            else:
                expires = int(current['active_till'])
                interval = 7 * 86400 if '7_days' in recheck or disposition == 'urgent' else 30 * 86400
                review_by = min(now + interval, expires)
            fingerprint = (self.scanner().get('consumer_fingerprints', {})
                           .get(image, {}).get(service, ''))
            meta = {**old, 'status': disposition, 'reason': reason.strip(),
                    'evidence_urls': urls, 'reviewed_at': proposal['reviewed_at'],
                    'recheck_on': recheck, 'review_by': review_by,
                    'expires_at': expires, 'fingerprint': fingerprint,
                    'action_summary': action_summary.strip(),
                    'attack_path': printable(attack_path, 500) if isinstance(attack_path, str) else '',
                    'impact': printable(impact, 300) if isinstance(impact, str) else '',
                    'legacy_revalidation': False, 'legacy_backlog': False,
                    'packages': row['packages'], 'scanner_url': row['scanner_url']}
            update = {'maintenanceid': current['maintenanceid'],
                      'name': f"HOME107v2 {disposition.upper()} {cve} {check_id}",
                      'description': description(meta)}
            if disposition == 'not_affected':
                update['active_till'] = expires
            self.api.call('maintenance.update', update)
            self.records[check_id] = meta
            self.tick()
            return {'finding_id': key, 'check_id': check_id, 'status': disposition,
                    'expires_at': expires}

    def serve(self, port=8081):
        controller = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _authorized(self, path):
                token_path = COLLECTOR_TOKEN if path == '/snapshot' else BALOO_TOKEN
                expected = token_path.read_text().strip()
                actual = self.headers.get('Authorization', '')
                return bool(expected) and hmac.compare_digest(actual, 'Bearer ' + expected)

            def _send(self, status, value):
                body = json.dumps(value, separators=(',', ':')).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == '/live':
                    self._send(200, {'ok': True})
                    return
                if parsed.path == '/health':
                    value = controller.snapshot_data
                    okay = value['healthy'] and controller.now() - value['generated_at'] < 180
                    self._send(200 if okay else 503, {'ok': okay})
                    return
                if parsed.path not in ('/snapshot', '/queue') or not self._authorized(parsed.path):
                    self._send(403, {'error': 'forbidden'})
                    return
                if parsed.path == '/snapshot':
                    self._send(200, controller.snapshot_data)
                    return
                try:
                    query = urllib.parse.parse_qs(parsed.query, strict_parsing=False)
                    limit = int(query.get('limit', ['20'])[0])
                    offset = int(query.get('offset', ['0'])[0])
                    if not 1 <= limit <= 50 or not 0 <= offset <= MAX_FINDINGS:
                        raise ValueError('queue bounds invalid')
                    if not controller.snapshot_data['healthy']:
                        self._send(503, {'error': 'review controller unavailable'})
                    else:
                        self._send(200, controller.queue(limit, offset))
                except ValueError:
                    self._send(400, {'error': 'invalid queue parameters'})

            def do_POST(self):
                if self.path != '/review' or not self._authorized('/review'):
                    self._send(403, {'error': 'forbidden'})
                    return
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 16384:
                        raise ValueError('review request size invalid')
                    proposal = json.loads(self.rfile.read(size))
                    result = controller.submit_review(proposal)
                except (ValueError, TypeError):
                    self._send(422, {'error': 'review validation failed'})
                    return
                except Exception:
                    self._send(503, {'error': 'review write unavailable'})
                    return
                self._send(200, result)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(('0.0.0.0', port), Handler)
        def loop():
            while True:
                controller.tick()
                time.sleep(60)
        threading.Thread(target=loop, daemon=True).start()
        server.serve_forever()


def main():
    controller = Controller()
    if os.environ.get('REVIEW_INITIALIZE') == 'true':
        print('initialized image identities:', controller.initialize())
        return
    controller.serve()


if __name__ == '__main__':
    main()
