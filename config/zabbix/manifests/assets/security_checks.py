"""Turn bounded image scan results into stable Zabbix checks."""
import json
from pathlib import Path
import time
import urllib.request

SCANNER_URL = 'http://security-scanner.zabbix.svc.cluster.local:8080/snapshot'
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
INVENTORY_MAX_AGE = 15 * 60
REPORT_MAX_AGE = 8 * 3600
INITIAL_SCAN_GRACE = 2 * 3600


def evaluate(snapshot, now, check):
    if not isinstance(snapshot, dict):
        raise ValueError('invalid scanner snapshot')
    images = snapshot.get('images')
    reports = snapshot.get('reports')
    errors = snapshot.get('errors')
    if not isinstance(images, dict) or not isinstance(reports, dict) or not isinstance(errors, dict):
        raise ValueError('invalid scanner snapshot')
    inventory_at = snapshot.get('inventory_at', 0)
    started_at = snapshot.get('started_at', 0)
    inventory_ok = (isinstance(inventory_at, (float, int)) and
                    0 <= now - inventory_at < INVENTORY_MAX_AGE and
                    not snapshot.get('inventory_error') and bool(images))
    checks = [check('Security image inventory', 'security', not inventory_ok,
                    f'{len(images)} unique running image digests inventoried' if inventory_ok else
                    'running image inventory missing, stale or failed', 4)]
    unresolved = snapshot.get('unresolved', [])
    if not isinstance(unresolved, list):
        raise ValueError('invalid unresolved image list')
    checks.append(check('Security unresolved image IDs', 'security', bool(unresolved),
                        f'{len(unresolved)} running containers lack a canonical registry digest', 4))
    complete = inventory_ok and not unresolved
    for ref, users in sorted(images.items()):
        if not isinstance(ref, str) or not isinstance(users, list):
            raise ValueError('invalid image inventory')
        report = reports.get(ref, {})
        scanned_at = report.get('scanned_at', 0)
        fresh = isinstance(scanned_at, (float, int)) and 0 <= now - scanned_at < REPORT_MAX_AGE
        error = errors.get(ref)
        pending = (not report and isinstance(started_at, (float, int)) and
                   0 <= now - started_at < INITIAL_SCAN_GRACE and not error)
        covered = fresh and not error
        complete = complete and covered
        short_ref = ref.rsplit('/', 1)[-1].split('@')[0] + '@' + ref.rsplit(':', 1)[-1][:12]
        checks.append(check('Security scan ' + short_ref, 'security',
                            not covered and not pending,
                            'critical vulnerability scan current' if covered else
                            'initial image scan pending' if pending else
                            'image scan failed or stale; prior findings retained', 4))
        if not report:
            continue
        findings = report.get('findings')
        if not isinstance(findings, list):
            raise ValueError('invalid image findings')
        for finding in findings:
            advisory = finding['id']
            package_rows = finding.get('packages') or []
            package = package_rows[0] if package_rows else {}
            consumers = sorted(set(users))
            detail = (f"{ref}; package={package.get('name', 'unknown')} "
                      f"installed={package.get('installed', 'unknown')} "
                      f"fixed={package.get('fixed') or 'not published'}; "
                      f"source={finding.get('url') or 'see scanner report'}; "
                      f"consumers={', '.join(consumers[:10])}; total={len(consumers)}")
            checks.append(check(f'Critical {advisory} {short_ref}', 'security', True, detail, 4))
    return checks, complete


class SecurityCheckLifecycle:
    """Recover vanished CVEs only after a complete current scan."""

    def __init__(self, path):
        self.path = Path(path)
        try:
            self.records = json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            self.records = {}

    def reconcile(self, checks, complete, now):
        active = {c['id']: c for c in checks if c['name'].startswith('Critical ')}
        for key, value in active.items():
            self.records[key] = {'check': value, 'last_seen': now}
        for key, record in list(self.records.items()):
            if key in active:
                continue
            if not complete:
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
    def __init__(self, check, url=SCANNER_URL, state_path='/state/security-checks.json'):
        self.check = check
        self.url = url
        self.lifecycle = SecurityCheckLifecycle(state_path)

    def collect(self):
        now = time.time()
        try:
            with urllib.request.urlopen(self.url, timeout=5) as response:
                body = response.read(MAX_SNAPSHOT_BYTES + 1)
            if len(body) > MAX_SNAPSHOT_BYTES:
                raise ValueError('scanner snapshot exceeds limit')
            checks, complete = evaluate(json.loads(body), now, self.check)
        except Exception as error:
            checks = [self.check('Security scanner response', 'security', True,
                                 'scanner unavailable or invalid: ' + type(error).__name__, 4)]
            complete = False
        return self.lifecycle.reconcile(checks, complete, now)
