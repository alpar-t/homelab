"""Turn bounded image scan and review results into stable Zabbix checks."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request

SCANNER_URL = 'http://security-scanner.zabbix.svc.cluster.local:8080/snapshot'
REVIEW_URL = 'http://security-review-controller.zabbix.svc.cluster.local:8081/snapshot'
REVIEW_TOKEN = Path('/review-credentials/collector-token')
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
MAX_REVIEW_BYTES = 1024 * 1024
INVENTORY_MAX_AGE = 15 * 60
REPORT_MAX_AGE = 8 * 3600
REVIEW_MAX_AGE = 3 * 60
INITIAL_SCAN_GRACE = 2 * 3600
RECENT_EXPOSURE_SECONDS = 7 * 86400
IMAGE_REF = re.compile(r'^[a-z0-9][a-z0-9._:/-]*@sha256:[a-f0-9]{64}$')
ADVISORY_ID = re.compile(r'^(?:CVE-\d{4}-\d{4,}|GHSA-[a-z0-9-]{10,})$', re.I)
CHECK_ID = re.compile(r'^[a-f0-9]{20}$')


def _identity_id(kind, ref, advisory, service):
    """Hash the complete identity; short display names are never a security key."""
    value = json.dumps([kind, ref, advisory, service], separators=(',', ':'))
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def raw_check_id(ref, advisory, service):
    return _identity_id('security-raw-v2', ref, advisory, service)


def urgent_check_id(ref, advisory, service):
    return _identity_id('security-urgent-v1', ref, advisory, service)


def short_ref(ref):
    basename = ref.rsplit('/', 1)[-1].split('@')[0]
    if len(basename) > 55:
        basename = basename[:45] + '~' + hashlib.sha256(basename.encode()).hexdigest()[:8]
    return basename + '@' + ref.rsplit(':', 1)[-1][:12]


def _display_service(service):
    if len(service) <= 80:
        return service
    return service[:68] + '~' + hashlib.sha256(service.encode()).hexdigest()[:10]


def _finding_consumers(snapshot, ref, now):
    current = snapshot['images'].get(ref, [])
    recent = snapshot.get('recent_images', {}).get(ref, {})
    if not isinstance(current, list) or not isinstance(recent, dict):
        raise ValueError('invalid image consumer inventory')
    consumers = {service: ('running', None) for service in current}
    for service, last_seen in recent.items():
        if not isinstance(service, str) or not isinstance(last_seen, (float, int)):
            raise ValueError('invalid recent image consumer')
        if not 0 <= now - last_seen < RECENT_EXPOSURE_SECONDS:
            continue
        consumers.setdefault(service, ('recent', last_seen))
    if any(not isinstance(service, str) or not service or len(service) > 240 or '\n' in service
           for service in consumers):
        raise ValueError('invalid image service identity')
    return consumers


def _utc(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat(timespec='seconds')


def evaluate(snapshot, now, check):
    if not isinstance(snapshot, dict):
        raise ValueError('invalid scanner snapshot')
    images = snapshot.get('images')
    recent_images = snapshot.get('recent_images', {})
    reports = snapshot.get('reports')
    errors = snapshot.get('errors')
    if (not isinstance(images, dict) or not isinstance(recent_images, dict) or
            not isinstance(reports, dict) or not isinstance(errors, dict)):
        raise ValueError('invalid scanner snapshot')
    inventory_at = snapshot.get('inventory_at', 0)
    started_at = snapshot.get('started_at', 0)
    inventory_ok = (isinstance(inventory_at, (float, int)) and
                    0 <= now - inventory_at < INVENTORY_MAX_AGE and
                    not snapshot.get('inventory_error') and bool(images))
    checks = [check('Security image inventory', 'security', not inventory_ok,
                    f'{len(images)} running and {len(recent_images)} recently used image digests inventoried' if inventory_ok else
                    'running image inventory missing, stale or failed', 4)]
    watch_at = snapshot.get('watch_at', 0)
    watch_ok = (isinstance(watch_at, (float, int)) and
                0 <= now - watch_at < INVENTORY_MAX_AGE and
                not snapshot.get('watch_error'))
    checks.append(check('Security image watch', 'security', not watch_ok,
                        'Pod image watch current' if watch_ok else
                        'Pod image watch missing, stale or failed; short jobs may be missed', 4))
    unresolved = snapshot.get('unresolved', [])
    if not isinstance(unresolved, list):
        raise ValueError('invalid unresolved image list')
    checks.append(check('Security unresolved image IDs', 'security', bool(unresolved),
                        f'{len(unresolved)} running containers lack a canonical registry digest', 4))
    complete = inventory_ok and watch_ok and not unresolved
    for ref in sorted(set(images) | set(recent_images)):
        if not isinstance(ref, str) or not IMAGE_REF.fullmatch(ref):
            raise ValueError('invalid image inventory')
        users = _finding_consumers(snapshot, ref, now)
        if not users:
            continue
        report = reports.get(ref, {})
        scanned_at = report.get('scanned_at', 0)
        fresh = isinstance(scanned_at, (float, int)) and 0 <= now - scanned_at < REPORT_MAX_AGE
        error = errors.get(ref)
        pending = (not report and isinstance(started_at, (float, int)) and
                   0 <= now - started_at < INITIAL_SCAN_GRACE and not error)
        covered = fresh and not error
        complete = complete and covered
        display_ref = short_ref(ref)
        coverage = check('Security scan ' + display_ref, 'security',
                         not covered and not pending,
                         'critical vulnerability scan current' if covered else
                         'initial image scan pending' if pending else
                         'image scan failed or stale; prior findings retained', 4)
        coverage['id'] = hashlib.sha256(('security-scan-v2\0' + ref).encode()).hexdigest()[:20]
        checks.append(coverage)
        if not report:
            continue
        findings = report.get('findings')
        if not isinstance(findings, list):
            raise ValueError('invalid image findings')
        for finding in findings:
            advisory = finding['id']
            if (not isinstance(advisory, str) or len(advisory) > 64 or
                    not ADVISORY_ID.fullmatch(advisory)):
                raise ValueError('invalid image advisory')
            package_rows = finding.get('packages') or []
            package = package_rows[0] if package_rows else {}
            for service, (exposure, last_seen) in sorted(users.items()):
                detail = (f"image={ref}; advisory={advisory}; service={service}; "
                          f"exposure={exposure}; "
                          + (f"last_seen_utc={_utc(last_seen)}; " if last_seen else '')
                          + f"package={package.get('name', 'unknown')} "
                          f"installed={package.get('installed', 'unknown')} "
                          f"fixed={package.get('fixed') or 'not published'}; "
                          f"source={finding.get('url') or 'see scanner report'}")
                raw = check(f'Critical {advisory} {display_ref} {_display_service(service)}',
                            'security-cve', True, detail, 4)
                raw['id'] = raw_check_id(ref, advisory, service)
                # Raw scanner findings stay visible in Zabbix. Only a verified
                # urgent review may send a CVE WhatsApp notification.
                raw['notification'] = 'dashboard'
                checks.append(raw)
    return checks, complete


class SecurityCheckLifecycle:
    """Recover vanished CVEs only after complete scan and review snapshots."""

    def __init__(self, path):
        self.path = Path(path)
        try:
            self.records = json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            self.records = {}
        # Old digest-level Critical checks must not send a migration recovery
        # digest while per-service dashboard checks replace them.
        for record in self.records.values():
            value = record.get('check', {})
            if value.get('name', '').startswith('Critical '):
                value['notification'] = 'dashboard'

    def reconcile(self, checks, complete, now, allowed_raw_ids=None,
                  urgent_complete=False):
        active = {c['id']: c for c in checks
                  if c['name'].startswith(('Critical ', 'Urgent '))}
        for key, value in active.items():
            self.records[key] = {'check': value, 'last_seen': now}
        for key, record in list(self.records.items()):
            if key in active:
                continue
            record_complete = complete or (urgent_complete and
                                           record['check']['name'].startswith('Urgent '))
            if not record_complete:
                if (allowed_raw_ids is not None and
                        record['check']['name'].startswith('Critical ') and
                        key not in allowed_raw_ids):
                    # A previously published finding must obey the current
                    # exact maintenance gate too, including after expiry.
                    continue
                checks.append(record['check'])
            elif now - record['last_seen'] < 86400:
                recovered = {**record['check'], 'status': 0,
                             'detail': 'No longer present in the running image inventory'}
                checks.append(recovered)
                record['check'] = recovered
            else:
                del self.records[key]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.records, separators=(',', ':')))
        temporary.replace(self.path)
        return checks


class SecurityMonitor:
    def __init__(self, check, url=SCANNER_URL, state_path='/state/security-checks.json',
                 review_url=REVIEW_URL, review_token=REVIEW_TOKEN):
        self.check = check
        self.url = url
        self.review_url = review_url
        self.review_token = Path(review_token)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, message, headers, newurl):
                return None
        self.review_opener = urllib.request.build_opener(NoRedirect())
        self.lifecycle = SecurityCheckLifecycle(state_path)

    def fetch_review(self):
        token = self.review_token.read_text().strip()
        if not token:
            raise ValueError('empty review controller token')
        request = urllib.request.Request(self.review_url, headers={
            'Authorization': 'Bearer ' + token})
        with self.review_opener.open(request, timeout=5) as response:
            body = response.read(MAX_REVIEW_BYTES + 1)
        if len(body) > MAX_REVIEW_BYTES:
            raise ValueError('review controller snapshot exceeds limit')
        return json.loads(body)

    def review_checks(self, snapshot, active_raw_ids, now):
        if not isinstance(snapshot, dict):
            raise ValueError('invalid review controller snapshot')
        generated = snapshot.get('generated_at')
        if not isinstance(generated, (float, int)) or not 0 <= now - generated < REVIEW_MAX_AGE:
            raise ValueError('review controller snapshot stale')
        urgent = snapshot.get('urgent')
        if not isinstance(urgent, list) or len(urgent) > 512:
            raise ValueError('invalid urgent review list')
        values = {key: snapshot.get(key) for key in
                  ('queue_depth', 'overdue_count', 'unmuted_count', 'pending_count')}
        if any(type(value) is not int or value < 0 or value > 100000
               for value in values.values()):
            raise ValueError('invalid review queue counters')
        healthy = snapshot.get('healthy') is True and not snapshot.get('error')
        if not healthy:
            raise ValueError('review controller unhealthy')
        ready = snapshot.get('ready_check_ids')
        if (not isinstance(ready, list) or len(ready) > 2000 or
                any(not isinstance(value, str) or not CHECK_ID.fullmatch(value)
                    for value in ready) or len(ready) != len(set(ready))):
            raise ValueError('invalid review maintenance gate')
        checks = []
        for row in urgent:
            if not isinstance(row, dict):
                raise ValueError('invalid urgent review')
            ref, advisory, service = (row.get(key) for key in ('image', 'cve', 'service'))
            if (not isinstance(ref, str) or not IMAGE_REF.fullmatch(ref) or
                    not isinstance(advisory, str) or len(advisory) > 64 or
                    not ADVISORY_ID.fullmatch(advisory) or
                    not isinstance(service, str) or not service or len(service) > 240 or
                    '\n' in service):
                raise ValueError('invalid urgent review identity')
            if row.get('check_id') != raw_check_id(ref, advisory, service):
                raise ValueError('urgent review has mismatched raw check')
            action = row.get('action_summary')
            reason = row.get('detail', '')
            if (not isinstance(action, str) or not 20 <= len(action) <= 240 or
                    not action.isprintable() or not isinstance(reason, str) or
                    len(reason) > 1000 or not reason.isprintable()):
                raise ValueError('invalid urgent review action')
            if row['check_id'] not in active_raw_ids:
                # A retired image cannot keep an urgent page active.
                continue
            name = f'Urgent {advisory} {short_ref(ref)} {_display_service(service)}'
            detail = (f'Action: {action}; reason={reason or "see Zabbix review record"}; '
                      f'image={ref}; advisory={advisory}; service={service}')
            item = self.check(name, 'security-urgent', True, detail, 4)
            item['id'] = urgent_check_id(ref, advisory, service)
            item['notification'] = 'page'
            item['notify_delay'] = 'immediate'
            item['failure_samples'] = 1
            checks.append(item)
        fault = values['overdue_count'] or values['unmuted_count']
        detail = (f"queue={values['queue_depth']} pending={values['pending_count']} "
                  f"overdue={values['overdue_count']} missing_mutes={values['unmuted_count']}")
        return checks, bool(fault), detail, set(ready), values['pending_count']

    def collect(self):
        now = time.time()
        scanner_complete = False
        raw_ids = set()
        try:
            with urllib.request.urlopen(self.url, timeout=5) as response:
                body = response.read(MAX_SNAPSHOT_BYTES + 1)
            if len(body) > MAX_SNAPSHOT_BYTES:
                raise ValueError('scanner snapshot exceeds limit')
            checks, scanner_complete = evaluate(json.loads(body), now, self.check)
            raw_ids = {value['id'] for value in checks if value['name'].startswith('Critical ')}
        except Exception as error:
            checks = [self.check('Security scanner response', 'security', True,
                                 'scanner unavailable or invalid: ' + type(error).__name__, 4)]
        review_complete = False
        urgent_complete = False
        ready = None
        try:
            urgent, review_bad, detail, ready, pending_count = self.review_checks(
                self.fetch_review(), raw_ids, now)
            held = raw_ids - ready
            if held:
                checks = [row for row in checks
                          if not row['name'].startswith('Critical ') or row['id'] in ready]
            checks.extend(urgent)
            pending = self.check('Security review pending', 'security',
                                 bool(held or pending_count),
                                 f'{len(held)} raw CVE checks awaiting active exact maintenance; '
                                 f'controller_pending={pending_count}', 3)
            pending['notification'] = 'dashboard'
            checks.append(pending)
            review_complete = not held
            urgent_complete = scanner_complete
        except Exception as error:
            review_bad, detail = True, 'review unavailable or invalid: ' + type(error).__name__
            pending = self.check('Security review pending', 'security', True,
                                 'controller unavailable; raw CVE checks remain visible without WhatsApp', 3)
            pending['notification'] = 'dashboard'
            checks.append(pending)
        checks.append(self.check('Security review automation', 'security', review_bad, detail, 4))
        return self.lifecycle.reconcile(checks, scanner_complete and review_complete,
                                        now, allowed_raw_ids=ready,
                                        urgent_complete=urgent_complete)
