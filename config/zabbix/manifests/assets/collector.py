#!/usr/bin/env python3
"""Small, read-only Kubernetes/HTTP collector. No third-party runtime packages."""
import concurrent.futures
import datetime as dt
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from mail_activity import MailActivity
from functional import FunctionalChecks

UTC = dt.timezone.utc
SA = Path('/var/run/secrets/kubernetes.io/serviceaccount')


def age(value, now):
    if not value:
        return float('inf')
    return max(0, now - dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())


def ready(obj):
    return any(c['type'] == 'Ready' and c['status'] == 'True'
               for c in obj.get('status', {}).get('conditions', []))


def quantity(value):
    match = re.fullmatch(r'([0-9.]+)([a-zA-Z]*)', str(value))
    if not match:
        raise ValueError('invalid Kubernetes quantity')
    scale = {'': 1, 'n': 1e-9, 'u': 1e-6, 'm': .001,
             'Ki': 1024, 'Mi': 1024**2, 'Gi': 1024**3, 'Ti': 1024**4,
             'k': 1000, 'M': 1000**2, 'G': 1000**3}
    return float(match[1]) * scale[match[2]]


def check(name, family, bad, detail, severity=4):
    # IDs are safe for both Zabbix item keys and JSONPath literals.
    return {'id': hashlib.sha256(name.encode()).hexdigest()[:20], 'name': name,
            'family': family, 'status': int(bool(bad)), 'detail': str(detail)[:1800],
            'severity': severity}


class Kubernetes:
    def __init__(self):
        self.context = ssl.create_default_context(cafile=str(SA / 'ca.crt'))
        self.base = 'https://kubernetes.default.svc'

    def get(self, path):
        # Re-read projected tokens, which Kubernetes rotates automatically.
        req = urllib.request.Request(self.base + path, headers={
            'Authorization': 'Bearer ' + (SA / 'token').read_text().strip()})
        with urllib.request.urlopen(req, context=self.context, timeout=15) as response:
            return json.load(response)

    def items(self, path):
        result, token = [], ''
        while True:
            query = '?limit=500' + ('&continue=' + urllib.parse.quote(token) if token else '')
            page = self.get(path + query)
            result.extend(page['items'])
            token = page.get('metadata', {}).get('continue', '')
            if not token:
                return result

    def logs(self, ns, pod, container, since_seconds=600, limit_bytes=200000,
             tail_lines=1000, timestamps=False):
        query = {'container': container, 'sinceSeconds': since_seconds, 'limitBytes': limit_bytes,
                 'timestamps': str(timestamps).lower()}
        if tail_lines is not None:
            query['tailLines'] = tail_lines
        path = f'/api/v1/namespaces/{ns}/pods/{pod}/log?' + urllib.parse.urlencode(query)
        req = urllib.request.Request(self.base + path, headers={
            'Authorization': 'Bearer ' + (SA / 'token').read_text().strip()})
        with urllib.request.urlopen(req, context=self.context, timeout=15) as response:
            value = response.read(limit_bytes + 1)
            if timestamps and len(value) >= limit_bytes:
                raise ValueError('Mail event log response was truncated')
            return value.decode(errors='replace')


def evaluate(data, policy, now):
    checks = []
    nodes = {n['metadata']['name']: n for n in data['nodes']}
    for name in policy['nodes']:
        n = nodes.get(name, {})
        conditions = n.get('status', {}).get('conditions', [])
        issues = [c['type'] for c in conditions if c['type'] in
                  ('MemoryPressure', 'DiskPressure', 'PIDPressure') and c['status'] != 'False']
        checks.append(check(f'Node {name}', 'node', not ready(n) or issues,
                            ', '.join(issues) or ('Ready' if ready(n) else 'missing or NotReady')))
        metrics = next((m for m in data['metrics'] if m['metadata']['name'] == name), None)
        for resource, threshold in [('memory', .9), ('cpu', .95)]:
            ratio = None
            if metrics and n:
                ratio = quantity(metrics['usage'][resource]) / quantity(n['status']['allocatable'][resource])
            checks.append(check(f'Node {name} {resource}', 'node', ratio is None or ratio >= threshold,
                                f'{ratio * 100:.1f}% of allocatable' if ratio is not None else 'metrics missing', 3))

    pods = data['pods']
    for name in policy['nodes']:
        storage = [p for p in pods if p['metadata']['namespace'] == 'node-config'
                   and p['metadata'].get('labels', {}).get('app.kubernetes.io/name') == 'node-storage-health'
                   and p.get('spec', {}).get('nodeName') == name
                   and not p['metadata'].get('deletionTimestamp')]
        # Latest scheduled collector wins during rolling updates; absence fails closed.
        storage.sort(key=lambda p: p['metadata']['creationTimestamp'], reverse=True)
        healthy = bool(storage and ready(storage[0]))
        detail = 'SMART/filesystem readiness healthy'
        if not healthy:
            detail = 'collector missing or NotReady; inspect node-storage-health readiness events'
            if storage:
                uid = storage[0]['metadata']['uid']
                events = [e for e in data['events'] if e.get('involvedObject', {}).get('uid') == uid
                          and e.get('reason') == 'Unhealthy']
                events.sort(key=lambda e: e.get('lastTimestamp') or e['metadata']['creationTimestamp'])
                if events:
                    detail = events[-1].get('message', detail)
        checks.append(check(f'Physical storage {name}', 'storage', not healthy, detail))

    workloads = {(d['metadata']['namespace'], d['metadata']['name']): d for d in data['deployments']}
    for ns, name in policy['deployments']:
        d = workloads.get((ns, name), {})
        desired = d.get('spec', {}).get('replicas', 1)
        status = d.get('status', {})
        healthy = bool(d) and desired > 0 and status.get('availableReplicas', 0) >= desired
        checks.append(check(f'Application {ns}/{name}', 'application', not healthy,
                            f"available={status.get('availableReplicas', 0)}/{desired}"))
    for d in data['daemonsets']:
        name = d['metadata']['namespace'] + '/' + d['metadata']['name']
        s = d.get('status', {})
        desired = s.get('desiredNumberScheduled', 0)
        checks.append(check(f'DaemonSet {name}', 'cluster', not desired or s.get('numberReady', 0) < desired,
                            f"ready={s.get('numberReady', 0)}/{desired}"))
    for p in pods:
        if p.get('status', {}).get('phase') == 'Succeeded' or p['metadata'].get('deletionTimestamp'):
            continue
        if age(p['metadata']['creationTimestamp'], now) < 600:
            continue  # Startup/rollout grace; infrastructure is checked separately.
        if not ready(p):
            name = p['metadata']['namespace'] + '/' + p['metadata']['name']
            states = [s.get('state', {}) for s in p.get('status', {}).get('containerStatuses', [])]
            checks.append(check(f'Pod {name}', 'cluster', True, json.dumps(states), 3))

    completed = {}
    for b in data['longhorn_backups']:
        s = b.get('status', {})
        if s.get('state') == 'Completed':
            v = s.get('volumeName')
            completed[v] = min(completed.get(v, float('inf')), age(s.get('backupCreatedAt'), now))
    for v in data['volumes']:
        meta, s = v['metadata'], v.get('status', {})
        name = meta['name']
        ks = s.get('kubernetesStatus', {})
        label = f"{ks.get('namespace', '')}/{ks.get('pvcName', name)}"
        robustness = s.get('robustness', 'unknown')
        # Intentionally unused/detached volumes may report unknown; faults still alert.
        bad = robustness in ('degraded', 'faulted') or (s.get('state') == 'attached' and robustness != 'healthy')
        checks.append(check(f'Longhorn volume {label}', 'longhorn', bad,
                            f"state={s.get('state')}; robustness={robustness}"))
        groups = meta.get('labels', {})
        critical = groups.get('recurring-job-group.longhorn.io/critical') == 'enabled'
        weekly = groups.get('recurring-job-group.longhorn.io/default') == 'enabled'
        if critical or weekly:
            max_age = 48 * 3600 if critical else 10 * 86400
            actual_age = completed.get(name, float('inf'))
            checks.append(check(f'Longhorn backup {label}', 'backup', actual_age > max_age,
                                f'completed backup age={actual_age / 3600:.1f}h; limit={max_age / 3600:.0f}h'))
    for target in data['backup_targets']:
        s = target.get('status', {})
        checks.append(check('Longhorn backup target ' + target['metadata']['name'], 'backup',
                            not s.get('available', False), s.get('conditions', [])))

    schedules = {}
    for b in data['scheduled_backups']:
        meta, spec = b['metadata'], b['spec']
        fields = spec['schedule'].split()
        valid = len(fields) == 6 and fields[3:5] == ['*', '*'] and (
            fields[5] == '*' or re.fullmatch('[0-7]', fields[5]))
        checks.append(check('CNPG schedule ' + meta['namespace'] + '/' + meta['name'], 'backup',
                            not valid or spec.get('suspend', False), spec['schedule']))
        if valid and not spec.get('suspend', False):
            key = (meta['namespace'], spec['cluster']['name'])
            limit = 48 * 3600 if fields[5] == '*' else 10 * 86400
            schedules[key] = min(schedules.get(key, float('inf')), limit)
    clusters = {(c['metadata']['namespace'], c['metadata']['name']): c for c in data['clusters']}
    for key in policy['databases']:
        ns, name = key
        c = clusters.get((ns, name), {})
        s = c.get('status', {})
        conditions = {x['type']: x for x in s.get('conditions', [])}
        bad = not ready(c) or s.get('readyInstances', 0) < c.get('spec', {}).get('instances', 2)
        checks.append(check(f'CNPG health {ns}/{name}', 'cnpg', bad,
                            f"ready={s.get('readyInstances', 0)}; phase={s.get('phase', 'missing')}"))
        for cond in ('ContinuousArchiving', 'LastBackupSucceeded'):
            value = conditions.get(cond, {})
            checks.append(check(f'CNPG {cond} {ns}/{name}', 'backup', value.get('status') != 'True',
                                value.get('message', 'condition missing')))
        limit = schedules.get((ns, name), 0)
        actual_age = age(s.get('lastSuccessfulBackup'), now)
        checks.append(check(f'CNPG backup freshness {ns}/{name}', 'backup',
                            not limit or actual_age > limit,
                            f'backup age={actual_age / 3600:.1f}h; limit={limit / 3600:.0f}h'))
    return checks


PATHS = {
    'nodes': '/api/v1/nodes', 'pods': '/api/v1/pods',
    'events': '/api/v1/namespaces/node-config/events',
    'metrics': '/apis/metrics.k8s.io/v1beta1/nodes',
    'deployments': '/apis/apps/v1/deployments', 'daemonsets': '/apis/apps/v1/daemonsets',
    'volumes': '/apis/longhorn.io/v1beta2/namespaces/longhorn-system/volumes',
    'longhorn_backups': '/apis/longhorn.io/v1beta2/namespaces/longhorn-system/backups',
    'backup_targets': '/apis/longhorn.io/v1beta2/namespaces/longhorn-system/backuptargets',
    'clusters': '/apis/postgresql.cnpg.io/v1/clusters',
    'scheduled_backups': '/apis/postgresql.cnpg.io/v1/scheduledbackups',
}


def probe(target):
    name = target['name']
    try:
        if 'url' in target:
            req = urllib.request.Request(target['url'], headers={'User-Agent': 'HomePBP-monitor/1'})
            try:
                with urllib.request.urlopen(req, timeout=8) as response:
                    code = response.status
            except urllib.error.HTTPError as error:
                code = error.code
            bad = code not in target.get('codes', [200])
            detail = f'HTTP {code}'
        else:
            with socket.create_connection((target['host'], target['port']), timeout=8):
                pass
            bad, detail = False, 'TCP reachable'
        return check(name, target.get('family', 'reachability'), bad, detail)
    except Exception as error:
        return check(name, target.get('family', 'reachability'), True, type(error).__name__)


def collect(kube, policy, activity=None, functional=None):
    now = time.time()
    data, failures = {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(kube.items, path): name for name, path in PATHS.items()}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                data[name] = future.result()
                if name in ('nodes', 'volumes', 'clusters', 'backup_targets') and not data[name]:
                    raise ValueError('empty inventory')
            except Exception as error:
                data[name] = []
                failures.append(check('Collector API ' + name, 'monitoring', True, type(error).__name__))
        reachability = list(pool.map(probe, policy['probes']))
    checks = evaluate(data, policy, now) + failures + reachability
    mail_pods = [p for p in data['pods'] if p['metadata']['namespace'] == 'stalwart-mail'
                 and p['metadata'].get('labels', {}).get('app') == 'stalwart'
                 and not p['metadata'].get('deletionTimestamp')]
    for container, pattern in [
        ('fetchmail', r'(?i)authorization failure|authentication failed|socket error|connection refused|delivery.*failed|SMTP error|query status=[2-9]|certificate.*fail'),
        ('stalwart', r'(?i)delivery\.(failed|d[sn].*failed)|delivery.*(error|failed)|smtp.*(auth.*fail|connection.*fail)|queue.*error')]:
        bad, count = not bool(mail_pods), 0
        try:
            for pod in mail_pods:
                lines = kube.logs('stalwart-mail', pod['metadata']['name'], container).splitlines()
                count += sum(bool(re.search(pattern, line)) for line in lines)
            bad = bad or count > 0
            detail = f'{count} matching failure records in the last 10 minutes; inspect {container} logs'
        except Exception as error:
            bad, detail = True, 'log query failed: ' + type(error).__name__
        checks.append(check('Mail ' + container + ' failures', 'mail', bad, detail))
    if 'mail_activity' in policy:
        try:
            if not mail_pods:
                raise ValueError('Mail workload is missing')
            activity = activity or MailActivity()
            options, full = activity.query_options(now, policy['mail_activity'])
            logs = [kube.logs('stalwart-mail', pod['metadata']['name'], 'stalwart', **options)
                    for pod in mail_pods]
            result = activity.observe(logs, now, policy['mail_activity'], full)
            checks.append(check('Mail incoming activity', 'mail', result['bad'], result['detail'], 3))
        except Exception as error:
            checks.append(check('Mail incoming activity', 'mail', True,
                                'Arrival monitoring unavailable: ' + type(error).__name__, 3))
    if functional is not None:
        checks.extend(functional.collect())
    return {'collected_at': int(now), 'checks': checks}


def main():
    policy = json.loads(Path(os.environ.get('POLICY_FILE', '/config/policy.json')).read_text())
    kube = Kubernetes()
    activity = MailActivity(os.environ.get('MAIL_ACTIVITY_STATE', '/state/mail-activity.json'))
    functional = FunctionalChecks(kube, Path(os.environ.get('POLICY_FILE', '/config/policy.json')).parent, check)
    snapshot = {'collected_at': 0, 'checks': []}
    lock = threading.Lock()

    def loop():
        nonlocal snapshot
        while True:
            started = time.monotonic()
            try:
                result = collect(kube, policy, activity, functional)
                with lock:
                    snapshot = result
            except Exception as error:
                print('collector failed:', type(error).__name__, flush=True)
            time.sleep(max(1, 60 - (time.monotonic() - started)))

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            with lock:
                value = snapshot
            fresh = time.time() - value['collected_at'] < 180
            if self.path not in ('/health', '/snapshot'):
                self.send_error(404)
                return
            # A failed collection cannot masquerade as a healthy stale snapshot.
            if not fresh:
                self.send_error(503, 'collector has no fresh snapshot')
                return
            body = json.dumps(value if self.path == '/snapshot' else {'ok': True}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    threading.Thread(target=loop, daemon=True).start()
    http.server.ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()


if __name__ == '__main__':
    main()
