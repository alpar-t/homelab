#!/usr/bin/env python3
"""Scan exact running Kubernetes image digests for critical vulnerabilities."""
import copy
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
import urllib.parse
import urllib.request

SA = Path('/var/run/secrets/kubernetes.io/serviceaccount')
STATE = Path(os.environ.get('SCANNER_STATE', '/cache/state.json'))
TRIVY = os.environ.get('TRIVY_BINARY', '/tools/trivy')
SCAN_INTERVAL = 6 * 3600
INVENTORY_INTERVAL = 5 * 60
ERROR_RETRY_INTERVAL = 3600
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

    def items(self, path):
        rows, token = [], ''
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
            if len(rows) > 3000:
                raise ValueError('Kubernetes inventory exceeds limit')
            token = page.get('metadata', {}).get('continue', '')
            if not token:
                return rows
        raise ValueError('Kubernetes inventory exceeds page limit')

    def inventory(self):
        pods = self.items('/api/v1/pods')
        replicasets = {(r['metadata']['namespace'], r['metadata']['name']): r
                       for r in self.items('/apis/apps/v1/replicasets')}
        jobs = {(j['metadata']['namespace'], j['metadata']['name']): j
                for j in self.items('/apis/batch/v1/jobs')}
        return image_inventory(pods, replicasets, jobs)


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
    def __init__(self, kube=None, scan=None, state_path=STATE, now=time.time):
        self.kube = kube or Kubernetes()
        self.scan = scan or scan_image
        self.path = Path(state_path)
        self.now = now
        self.lock = threading.Lock()
        try:
            self.state = json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            self.state = {'started_at': self.now(), 'inventory_at': 0, 'inventory_error': '',
                          'images': {}, 'unresolved': [], 'reports': {}, 'errors': {},
                          'attempted_at': {}}

    def save(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.state, separators=(',', ':')))
            temporary.replace(self.path)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def refresh_inventory(self):
        try:
            images, unresolved = self.kube.inventory()
            with self.lock:
                self.state['images'] = images
                self.state['unresolved'] = unresolved
                self.state['inventory_at'] = self.now()
                self.state['inventory_error'] = ''
                self.state['reports'] = {
                    ref: report for ref, report in self.state['reports'].items() if ref in images}
                self.state['errors'] = {
                    ref: error for ref, error in self.state['errors'].items() if ref in images}
                self.state['attempted_at'] = {
                    ref: when for ref, when in self.state.get('attempted_at', {}).items() if ref in images}
            self.save()
        except Exception as error:
            with self.lock:
                self.state['inventory_error'] = type(error).__name__
            self.save()
            return

    def scan_due(self):
        state = self.snapshot()
        for ref in state['images']:
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
    scanner = Scanner()

    def inventory_loop():
        while True:
            started = time.monotonic()
            scanner.refresh_inventory()
            time.sleep(max(1, INVENTORY_INTERVAL - (time.monotonic() - started)))

    def scan_loop():
        while True:
            if not scanner.scan_due():
                time.sleep(60)

    threading.Thread(target=inventory_loop, daemon=True).start()
    threading.Thread(target=scan_loop, daemon=True).start()
    scanner.serve()


if __name__ == '__main__':
    main()
