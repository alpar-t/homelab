#!/usr/bin/env python3
"""Scan exact running Kubernetes image digests for critical vulnerabilities."""
import copy
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import tempfile
import threading
import time
from datetime import datetime
import urllib.error
import urllib.parse
import urllib.request

SA = Path('/var/run/secrets/kubernetes.io/serviceaccount')
STATE = Path(os.environ.get('SCANNER_STATE', '/state/state.json'))
LEGACY_STATE = Path(os.environ.get('SCANNER_LEGACY_STATE', '/cache/state.json'))
TRIVY = os.environ.get('TRIVY_BINARY', '/tools/trivy')
SCAN_INTERVAL = 6 * 3600
INVENTORY_INTERVAL = 5 * 60
ERROR_RETRY_INTERVAL = 5 * 60
RECENT_EXPOSURE_SECONDS = 7 * 86400
MAX_WATCH_EVENT_BYTES = 2 * 1024 * 1024
MAX_RECENT_EXPOSURES = 10000
MAX_REPORT_BYTES = 32 * 1024 * 1024
IMAGE_REF = re.compile(r'^[a-z0-9][a-z0-9._:/-]*@sha256:[a-f0-9]{64}$')
ADVISORY_ID = re.compile(r'^(?:CVE-\d{4}-\d{4,}|GHSA-[a-z0-9-]{10,})$', re.I)


def canonical_ref(image_id):
    if not isinstance(image_id, str):
        return None
    for prefix in ('docker-pullable://', 'containerd://'):
        if image_id.startswith(prefix):
            image_id = image_id[len(prefix):]
    return image_id if IMAGE_REF.fullmatch(image_id) else None


def owner_name(pod, replicasets, jobs):
    namespace = pod['metadata']['namespace']
    owner = next((o for o in pod['metadata'].get('ownerReferences', [])
                  if o.get('controller')), None)
    if owner is None:
        return f"{namespace}/Pod/{pod['metadata']['name']}"
    kind, name = owner['kind'], owner['name']
    if kind == 'ReplicaSet':
        rs = replicasets.get((namespace, name), {})
        parent = next((o for o in rs.get('metadata', {}).get('ownerReferences', [])
                       if o.get('controller') and o.get('kind') == 'Deployment'), None)
        if parent:
            kind, name = 'Deployment', parent['name']
    elif kind == 'Job':
        job = jobs.get((namespace, name), {})
        parent = next((o for o in job.get('metadata', {}).get('ownerReferences', [])
                       if o.get('controller') and o.get('kind') == 'CronJob'), None)
        if parent:
            kind, name = 'CronJob', parent['name']
    return f'{namespace}/{kind}/{name}'


def image_inventory(pods, replicasets, jobs):
    """Use runtime image IDs, including init and ephemeral containers."""
    result, unresolved = {}, []
    for pod in pods:
        if pod.get('status', {}).get('phase') != 'Running' or pod['metadata'].get('deletionTimestamp'):
            continue
        workload = owner_name(pod, replicasets, jobs)
        status = pod['status']
        for group in ('containerStatuses', 'initContainerStatuses', 'ephemeralContainerStatuses'):
            for container in status.get(group, []) or []:
                ref = canonical_ref(container.get('imageID'))
                identity = f"{workload}/{container.get('name', 'unknown')}"
                if ref:
                    result.setdefault(ref, set()).add(identity)
                else:
                    unresolved.append(identity)
    if not result:
        raise ValueError('no running image IDs')
    return {ref: sorted(owners) for ref, owners in sorted(result.items())}, sorted(set(unresolved))


def _finished_at(pod):
    """Use the container's terminal time, not repeated observations of its Pod."""
    values = []
    for group in ('containerStatuses', 'initContainerStatuses', 'ephemeralContainerStatuses'):
        for container in pod.get('status', {}).get(group, []) or []:
            value = container.get('state', {}).get('terminated', {}).get('finishedAt')
            if value:
                try:
                    values.append(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())
                except ValueError:
                    pass
    return max(values) if values else None


def recent_exposures(pods, replicasets, jobs, observed, current, now):
    """Retain every observed runtime image for seven days after its Pod exits."""
    for pod in pods:
        workload = owner_name(pod, replicasets, jobs)
        terminal = pod.get('status', {}).get('phase') in ('Succeeded', 'Failed')
        seen_at = _finished_at(pod) if terminal else now
        if seen_at is None:
            # A terminal Pod without a container finish timestamp gets the first
            # observed time, which remains stable in the persisted record.
            seen_at = None
        for group in ('containerStatuses', 'initContainerStatuses', 'ephemeralContainerStatuses'):
            for container in pod.get('status', {}).get(group, []) or []:
                state = container.get('state') or {}
                prior = container.get('lastState') or {}
                if not (state.get('running') or state.get('terminated') or
                        prior.get('terminated')):
                    continue
                ref = canonical_ref(container.get('imageID'))
                if not ref:
                    continue
                identity = f"{workload}/{container.get('name', 'unknown')}"
                previous = observed.setdefault(ref, {}).get(identity)
                if seen_at is None:
                    seen = previous if previous is not None else now
                else:
                    seen = max(previous or 0, seen_at)
                observed[ref][identity] = seen
    cutoff = now - RECENT_EXPOSURE_SECONDS
    for ref, users in list(observed.items()):
        for identity, seen in list(users.items()):
            if not isinstance(seen, (float, int)) or seen < cutoff:
                del users[identity]
        if not users:
            del observed[ref]
    if sum(len(users) for users in observed.values()) > MAX_RECENT_EXPOSURES:
        raise ValueError('recent image exposure inventory exceeds limit')
    return {ref: {identity: seen for identity, seen in sorted(users.items())
                  if identity not in current.get(ref, ())}
            for ref, users in sorted(observed.items())
            if any(identity not in current.get(ref, ()) for identity in users)}


def consumer_fingerprints(pods, replicasets, jobs, cronjobs=None):
    """Hash safe Pod-template signals; never expose env values or Secret data."""
    cronjobs = cronjobs or {}
    tokens = {}
    for pod in pods:
        metadata = pod.get('metadata', {})
        owner = next((item for item in metadata.get('ownerReferences', [])
                      if item.get('controller')), {})
        revision = ''
        if owner.get('kind') == 'Job':
            job = jobs.get((metadata.get('namespace'), owner.get('name')), {})
            parent = next((item for item in job.get('metadata', {}).get('ownerReferences', [])
                           if item.get('controller') and item.get('kind') == 'CronJob'), None)
            if parent:
                owner = parent
                cron = cronjobs.get((metadata.get('namespace'), parent.get('name')), {})
                revision = cron.get('metadata', {}).get('generation', '')
        labels = metadata.get('labels') or {}
        spec = pod.get('spec') or {}
        template = {
            'owner_kind': owner.get('kind', 'Pod'),
            'owner_uid': owner.get('uid', metadata.get('uid', '')),
            'owner_generation': revision,
            'revision': {key: labels.get(key, '') for key in
                         ('pod-template-hash', 'controller-revision-hash')},
            'service_account': spec.get('serviceAccountName', ''),
            'host_network': spec.get('hostNetwork', False),
            'volumes': sorted((volume.get('name', ''),
                               (volume.get('configMap') or {}).get('name', ''),
                               (volume.get('secret') or {}).get('secretName', ''),
                               (volume.get('persistentVolumeClaim') or {}).get('claimName', ''))
                              for volume in spec.get('volumes', []) or []),
        }
        token = hashlib.sha256(json.dumps(template, sort_keys=True).encode()).hexdigest()
        workload = owner_name(pod, replicasets, jobs)
        for group in ('containerStatuses', 'initContainerStatuses', 'ephemeralContainerStatuses'):
            for container in pod.get('status', {}).get(group, []) or []:
                ref = canonical_ref(container.get('imageID'))
                if ref:
                    identity = f"{workload}/{container.get('name', 'unknown')}"
                    tokens.setdefault(ref, {}).setdefault(identity, set()).add(token)
    return {ref: {identity: hashlib.sha256(','.join(sorted(values)).encode()).hexdigest()
                  for identity, values in sorted(users.items())}
            for ref, users in sorted(tokens.items())}


def critical_findings(report):
    if not isinstance(report, dict):
        raise ValueError('invalid Trivy JSON report')
    results = report.get('Results')
    # Trivy omits Results when an image has no recognized packages to scan.
    if results is None and report.get('ArtifactName') and isinstance(report.get('Metadata'), dict):
        results = []
    if not isinstance(results, list):
        raise ValueError('invalid Trivy JSON report')
    findings = {}
    for target in results:
        for item in target.get('Vulnerabilities') or []:
            if item.get('Severity') != 'CRITICAL' or item.get('Status') == 'not_affected':
                continue
            advisory = item.get('VulnerabilityID', '')
            if not ADVISORY_ID.fullmatch(advisory):
                continue
            package = str(item.get('PkgName', ''))[:100]
            installed = str(item.get('InstalledVersion', ''))[:100]
            fixed = str(item.get('FixedVersion', ''))[:100]
            url = str(item.get('PrimaryURL', ''))
            if not url.startswith('https://') or len(url) > 300:
                url = ''
            finding = findings.setdefault(advisory, {'id': advisory, 'packages': [], 'url': url})
            package_row = {'name': package, 'installed': installed, 'fixed': fixed}
            if package_row not in finding['packages'] and len(finding['packages']) < 8:
                finding['packages'].append(package_row)
    return [findings[key] for key in sorted(findings)]


class Kubernetes:
    def __init__(self):
        self.base = 'https://kubernetes.default.svc'

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, message, headers, newurl):
                return None

        self.opener = urllib.request.build_opener(
            NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(SA / 'ca.crt'))))

    def _list(self, path):
        rows, token, version = [], '', ''
        for _ in range(6):
            query = '?limit=500' + ('&continue=' + urllib.parse.quote(token) if token else '')
            request = urllib.request.Request(self.base + path + query, headers={
                'Authorization': 'Bearer ' + (SA / 'token').read_text().strip()})
            with self.opener.open(request, timeout=15) as response:
                body = response.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                raise ValueError('Kubernetes inventory page exceeds limit')
            page = json.loads(body)
            rows.extend(page['items'])
            version = page.get('metadata', {}).get('resourceVersion', version)
            if len(rows) > 3000:
                raise ValueError('Kubernetes inventory exceeds limit')
            token = page.get('metadata', {}).get('continue', '')
            if not token:
                return rows, version
        raise ValueError('Kubernetes inventory exceeds page limit')

    def items(self, path):
        return self._list(path)[0]

    def _get(self, path):
        request = urllib.request.Request(self.base + path, headers={
            'Authorization': 'Bearer ' + (SA / 'token').read_text().strip()})
        try:
            with self.opener.open(request, timeout=10) as response:
                body = response.read(MAX_WATCH_EVENT_BYTES + 1)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise
        if len(body) > MAX_WATCH_EVENT_BYTES:
            raise ValueError('Kubernetes owner object exceeds limit')
        return json.loads(body)

    def job(self, namespace, name):
        namespace = urllib.parse.quote(namespace, safe='')
        name = urllib.parse.quote(name, safe='')
        return self._get(f'/apis/batch/v1/namespaces/{namespace}/jobs/{name}')

    def cronjob(self, namespace, name):
        namespace = urllib.parse.quote(namespace, safe='')
        name = urllib.parse.quote(name, safe='')
        return self._get(f'/apis/batch/v1/namespaces/{namespace}/cronjobs/{name}')

    def inventory(self):
        pods, version = self._list('/api/v1/pods')
        replicasets = {(r['metadata']['namespace'], r['metadata']['name']): r
                       for r in self.items('/apis/apps/v1/replicasets')}
        jobs = {(j['metadata']['namespace'], j['metadata']['name']): j
                for j in self.items('/apis/batch/v1/jobs')}
        cronjobs = {(j['metadata']['namespace'], j['metadata']['name']): j
                    for j in self.items('/apis/batch/v1/cronjobs')}
        if not version:
            raise ValueError('Kubernetes Pod list lacks resourceVersion')
        return pods, replicasets, jobs, cronjobs, version

    def watch_pods(self, version):
        query = urllib.parse.urlencode({'watch': '1', 'resourceVersion': version,
                                        'allowWatchBookmarks': 'true', 'timeoutSeconds': '60'})
        request = urllib.request.Request(self.base + '/api/v1/pods?' + query, headers={
            'Authorization': 'Bearer ' + (SA / 'token').read_text().strip()})
        try:
            with self.opener.open(request, timeout=75) as response:
                for line in response:
                    if len(line) > MAX_WATCH_EVENT_BYTES:
                        raise ValueError('Kubernetes Pod watch event exceeds limit')
                    if line.strip():
                        yield json.loads(line)
        except urllib.error.HTTPError as error:
            if error.code == 410:
                raise WatchExpired('Kubernetes Pod watch resourceVersion expired') from error
            raise


class WatchExpired(Exception):
    """The API server no longer has the requested resourceVersion."""


def scan_image(ref):
    if not IMAGE_REF.fullmatch(ref):
        raise ValueError('invalid image reference')
    with tempfile.TemporaryFile(dir='/tmp') as output:
        try:
            process = subprocess.run(
                [TRIVY, 'image', '--image-src', 'remote', '--scanners', 'vuln',
                 '--severity', 'CRITICAL',
                 '--format', 'json', '--no-progress', '--timeout', '20m', ref],
                stdout=output, stderr=subprocess.DEVNULL, timeout=25 * 60,
                check=False, env={**os.environ, 'TRIVY_CACHE_DIR': '/cache/trivy'})
        except subprocess.TimeoutExpired as error:
            raise TimeoutError('image scan timed out') from error
        if process.returncode:
            raise RuntimeError('Trivy exited unsuccessfully')
        if output.tell() > MAX_REPORT_BYTES:
            raise ValueError('Trivy report exceeds limit')
        output.seek(0)
        return critical_findings(json.load(output))


class Scanner:
    def __init__(self, kube=None, scan=None, state_path=STATE, now=time.time,
                 legacy_state_path=None):
        self.kube = kube or Kubernetes()
        self.scan = scan or scan_image
        self.path = Path(state_path)
        self.now = now
        self.lock = threading.Lock()
        self.pods = {}
        self.replicasets = {}
        self.jobs = {}
        self.cronjobs = {}
        self.resource_version = ''
        migrated = False
        try:
            self.state = json.loads(self.path.read_text())
        except FileNotFoundError:
            try:
                if legacy_state_path is None:
                    raise FileNotFoundError
                self.state = json.loads(Path(legacy_state_path).read_text())
                migrated = True
            except (FileNotFoundError, ValueError):
                self.state = None
        except ValueError:
            self.state = None
        if not isinstance(self.state, dict):
            self.state = None
        if self.state is None:
            self.state = {'started_at': self.now(), 'inventory_at': 0, 'inventory_error': '',
                          'images': {}, 'unresolved': [], 'reports': {}, 'errors': {},
                          'attempted_at': {}}
        for key, default in (('recent_images', {}), ('observed_images', {}),
                             ('consumer_fingerprints', {}), ('first_seen', {}),
                             ('watch_at', 0), ('watch_error', '')):
            self.state.setdefault(key, default)
        if migrated:
            self.save()

    def save(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.state, separators=(',', ':')))
            temporary.replace(self.path)

    def snapshot(self):
        with self.lock:
            result = copy.deepcopy(self.state)
            # This cache is persisted for restart recovery, but the collector
            # only needs the filtered seven-day view.
            result.pop('observed_images', None)
            return result

    def _reconcile_pods(self, now):
        images, unresolved = image_inventory(self.pods.values(), self.replicasets, self.jobs)
        observed = self.state['observed_images']
        recent = recent_exposures(self.pods.values(), self.replicasets, self.jobs,
                                  observed, images, now)
        active = set(images) | set(recent)
        self.state['images'] = images
        self.state['recent_images'] = recent
        self.state['unresolved'] = unresolved
        self.state['inventory_at'] = now
        self.state['inventory_error'] = ''
        latest = consumer_fingerprints(self.pods.values(), self.replicasets,
                                       self.jobs, self.cronjobs)
        previous = self.state['consumer_fingerprints']
        self.state['consumer_fingerprints'] = {
            ref: {identity: latest.get(ref, {}).get(identity) or
                  previous.get(ref, {}).get(identity)
                  for identity in set(images.get(ref, ())) | set(recent.get(ref, {}))
                  if latest.get(ref, {}).get(identity) or previous.get(ref, {}).get(identity)}
            for ref in active}
        for ref in active:
            self.state['first_seen'].setdefault(ref, now)
        self.state['first_seen'] = {ref: when for ref, when in self.state['first_seen'].items()
                                    if ref in active}
        for key in ('reports', 'errors', 'attempted_at'):
            self.state[key] = {ref: value for ref, value in self.state[key].items()
                               if ref in active}

    def refresh_inventory(self):
        try:
            pods, replicasets, jobs, cronjobs, version = self.kube.inventory()
            with self.lock:
                self.pods = {pod['metadata']['uid']: pod for pod in pods}
                self.replicasets = replicasets
                referenced_jobs = {
                    (pod['metadata']['namespace'], owner['name'])
                    for pod in pods
                    for owner in pod['metadata'].get('ownerReferences', [])
                    if owner.get('controller') and owner.get('kind') == 'Job'}
                self.jobs = {key: value for key, value in self.jobs.items()
                             if key in referenced_jobs}
                self.jobs.update(jobs)
                referenced_crons = {
                    (key[0], parent['name'])
                    for key, job in self.jobs.items()
                    for parent in job.get('metadata', {}).get('ownerReferences', [])
                    if parent.get('controller') and parent.get('kind') == 'CronJob'}
                self.cronjobs = {key: value for key, value in self.cronjobs.items()
                                 if key in referenced_crons}
                self.cronjobs.update(cronjobs)
                self._reconcile_pods(self.now())
                self.resource_version = version
                self.state['watch_at'] = self.now()
                self.state['watch_error'] = ''
            self.save()
        except Exception as error:
            with self.lock:
                self.state['inventory_error'] = type(error).__name__
            self.save()
            return

    def apply_watch_event(self, event):
        kind = event.get('type')
        pod = event.get('object') or {}
        if kind == 'ERROR':
            if str(pod.get('code')) == '410':
                raise WatchExpired('Kubernetes Pod watch resourceVersion expired')
            raise ValueError('Kubernetes Pod watch returned an error')
        version = pod.get('metadata', {}).get('resourceVersion')
        if kind == 'BOOKMARK':
            if version:
                self.resource_version = version
            return
        if kind not in ('ADDED', 'MODIFIED', 'DELETED') or not version:
            raise ValueError('invalid Kubernetes Pod watch event')
        uid = pod.get('metadata', {}).get('uid')
        if not uid:
            raise ValueError('Kubernetes Pod watch event lacks UID')
        owner = next((item for item in pod['metadata'].get('ownerReferences', [])
                      if item.get('controller') and item.get('kind') == 'Job'), None)
        if owner:
            namespace, name = pod['metadata']['namespace'], owner['name']
            if (namespace, name) not in self.jobs:
                try:
                    job = self.kube.job(namespace, name)
                    if job:
                        self.jobs[(namespace, name)] = job
                        parent = next((item for item in
                                       job.get('metadata', {}).get('ownerReferences', [])
                                       if item.get('controller') and item.get('kind') == 'CronJob'), None)
                        if parent and (namespace, parent['name']) not in self.cronjobs:
                            cronjob = self.kube.cronjob(namespace, parent['name'])
                            if cronjob:
                                self.cronjobs[(namespace, parent['name'])] = cronjob
                except Exception:
                    # Image discovery still succeeds if the owner was deleted
                    # before the Pod event arrived; the Job identity is fallback.
                    pass
        with self.lock:
            if kind == 'DELETED':
                old = self.pods.pop(uid, None)
                if old and not pod.get('status', {}).get('containerStatuses'):
                    pod = old
                # Capture an exited image even when deletion precedes the
                # periodic list, including a short deployment rollout.
                recent_exposures((pod,), self.replicasets, self.jobs,
                                 self.state['observed_images'], {}, self.now())
                for ref, users in consumer_fingerprints((pod,), self.replicasets,
                                                        self.jobs, self.cronjobs).items():
                    self.state['consumer_fingerprints'].setdefault(ref, {}).update(users)
            else:
                self.pods[uid] = pod
            self.resource_version = version
            self._reconcile_pods(self.now())
            self.state['watch_at'] = self.now()
            self.state['watch_error'] = ''
        self.save()

    def watch_loop(self):
        last_list = 0
        while True:
            if not self.resource_version or self.now() - last_list >= INVENTORY_INTERVAL:
                self.refresh_inventory()
                last_list = self.now()
                if not self.resource_version:
                    time.sleep(5)
                    continue
            try:
                for event in self.kube.watch_pods(self.resource_version):
                    self.apply_watch_event(event)
                with self.lock:
                    self.state['watch_at'] = self.now()
                    self.state['watch_error'] = ''
                    self.state['inventory_at'] = self.now()
                self.save()
            except WatchExpired:
                self.resource_version = ''
            except Exception as error:
                with self.lock:
                    self.state['watch_error'] = type(error).__name__
                    self.state['inventory_error'] = type(error).__name__
                self.save()
                self.resource_version = ''
                time.sleep(5)

    def scan_due(self):
        state = self.snapshot()
        for ref in sorted(set(state['images']) | set(state.get('recent_images', {}))):
            report = state['reports'].get(ref, {})
            if self.now() - report.get('scanned_at', 0) < SCAN_INTERVAL:
                continue
            if (ref in state['errors'] and
                    self.now() - state.get('attempted_at', {}).get(ref, 0) < ERROR_RETRY_INTERVAL):
                continue
            try:
                findings = self.scan(ref)
                with self.lock:
                    self.state['reports'][ref] = {'scanned_at': self.now(), 'findings': findings}
                    self.state['errors'].pop(ref, None)
                    self.state.setdefault('attempted_at', {})[ref] = self.now()
            except Exception as error:
                with self.lock:
                    self.state['errors'][ref] = type(error).__name__
                    self.state.setdefault('attempted_at', {})[ref] = self.now()
            self.save()
            return True
        return False

    def cycle(self):
        self.refresh_inventory()
        while self.scan_due():
            pass

    def serve(self):
        scanner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path not in ('/health', '/snapshot'):
                    self.send_error(404)
                    return
                body = json.dumps(scanner.snapshot() if self.path == '/snapshot' else {'ok': True}).encode()
                if len(body) > 4 * 1024 * 1024:
                    self.send_error(503, 'scanner snapshot exceeds limit')
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        http.server.ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()


def main():
    scanner = Scanner(legacy_state_path=LEGACY_STATE)

    def scan_loop():
        while True:
            if not scanner.scan_due():
                time.sleep(60)

    threading.Thread(target=scanner.watch_loop, daemon=True).start()
    threading.Thread(target=scan_loop, daemon=True).start()
    scanner.serve()


if __name__ == '__main__':
    main()
