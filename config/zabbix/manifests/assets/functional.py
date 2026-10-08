"""Bounded, credential-conscious functional service checks (standard library only)."""
import importlib.util
import json
from pathlib import Path
import queue
import re
import threading
import time
from types import SimpleNamespace
import urllib.error
import urllib.parse
import urllib.request


class SafeError(Exception):
    """An intentionally generic error; never includes URLs, bodies or credentials."""


class Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, follow):
        self.follow = follow

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self.follow:
            return None
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        # Always refuse cross-origin redirects; this also protects query credentials.
        if (old.scheme, old.hostname, old.port) != (new.scheme, new.hostname, new.port):
            raise SafeError('cross-origin redirect refused')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Context:
    def __init__(self, kube, deadline, credentials=Path('/credentials')):
        self.kube, self.deadline, self.credentials = kube, deadline, Path(credentials)
        self.now = time.time()

    def remaining(self):
        return max(0, self.deadline - time.monotonic())

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bool(bad)), detail=detail, severity=severity)

    def secret(self, key):
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', key):
            raise SafeError('invalid credential key')
        try:
            value = (self.credentials / key).read_text().strip()
            if not value:
                raise SafeError('credential unavailable')
            return value
        except OSError:
            raise SafeError('credential unavailable') from None

    def http(self, url, method='GET', headers=None, data=None, timeout=8,
             max_bytes=262144, follow_redirects=False):
        try:
            parts = urllib.parse.urlsplit(url)
            if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
                raise SafeError('invalid HTTP URL')
            if not 0 < max_bytes <= 1048576 or not 0 < timeout <= 30 or not self.remaining():
                raise SafeError('HTTP bounds exceeded')
            request_headers = dict(headers or {})
            if not any(key.lower() == 'user-agent' for key in request_headers):
                request_headers['User-Agent'] = 'HomePBP-monitor/1'
            request = urllib.request.Request(url, data=data, method=method,
                                            headers=request_headers)
            opener = urllib.request.build_opener(Redirects(follow_redirects))
            try:
                response = opener.open(request, timeout=min(timeout, self.remaining()))
            except urllib.error.HTTPError as error:
                response = error
            with response:
                chunks, size = [], 0
                while True:
                    if not self.remaining():
                        raise SafeError('service deadline exceeded')
                    chunk = response.read(min(16384, max_bytes + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > max_bytes:
                        raise SafeError('HTTP response exceeds limit')
                return SimpleNamespace(status=response.code, headers=dict(response.headers),
                                       body=b''.join(chunks))
        except SafeError:
            raise
        except Exception:
            raise SafeError('HTTP request failed') from None


class FunctionalChecks:
    def __init__(self, kube, directory, check, credentials=Path('/credentials')):
        self.kube, self.directory, self.check = kube, Path(directory), check
        self.credentials = credentials
        self.jobs = queue.Queue(maxsize=64)
        self.lock = threading.Lock()
        self.states = {}
        self.modules = {}
        for _ in range(3):
            threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        while True:
            slug, module_path, config, state, duration = self.jobs.get()
            deadline = time.monotonic() + duration
            with self.lock:
                state['deadline'] = deadline
            try:
                if time.monotonic() >= deadline:
                    raise SafeError('service deadline exceeded')
                source = module_path.read_bytes()
                cached = self.modules.get(slug)
                if cached is None or cached[0] != source:
                    spec = importlib.util.spec_from_file_location('functional_service_' + slug, module_path)
                    module = importlib.util.module_from_spec(spec)
                    # Preserve bounded in-memory observation windows between polls.
                    # Compile exact bytes so ConfigMap updates cannot reuse stale pyc.
                    exec(compile(source, str(module_path), 'exec'), module.__dict__)
                    self.modules[slug] = (source, module)
                else:
                    module = cached[1]
                records = module.run(Context(self.kube, deadline, self.credentials), config)
                if not isinstance(records, list) or not records:
                    raise SafeError('invalid or empty service results')
                names = set()
                for row in records:
                    if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not row['name'].strip() or len(row['name']) > 160:
                        raise SafeError('invalid service result name')
                    if row['name'] in names or type(row.get('status')) is not int or row['status'] not in (0, 1) or not isinstance(row.get('detail'), str) or len(row['detail']) > 1800:
                        raise SafeError('invalid service result')
                    if type(row.get('severity', 3)) is not int or not 0 <= row.get('severity', 3) <= 5:
                        raise SafeError('invalid service severity')
                    names.add(row['name'])
                if time.monotonic() >= deadline:
                    raise SafeError('service deadline exceeded')
                result, error = records, None
            except Exception as exc:
                result, error = None, ('functional check unavailable: ' + type(exc).__name__)
            with self.lock:
                if self.states.get(slug) is state:
                    if time.monotonic() >= deadline:
                        result, error = None, 'service deadline exceeded'
                    state.update(error=error, pending=False)
                    if result is not None:
                        state.update(result=result, completed=time.monotonic())
            self.jobs.task_done()

    def collect(self):
        paths = {p.stem[len('service_'):]: p for p in self.directory.glob('service_*.json')}
        for p in self.directory.glob('service_*.py'):
            paths.setdefault(p.stem[len('service_'):], self.directory / (p.stem + '.json'))
        output, now = [], time.monotonic()
        with self.lock:
            for slug, config_path in sorted(paths.items()):
                family = 'functional/' + slug
                monitor_name = 'Functional monitoring ' + slug
                try:
                    if not re.fullmatch(r'[a-z0-9_]+', slug):
                        raise SafeError('invalid slug')
                    config = json.loads(config_path.read_text())
                    if not isinstance(config, dict):
                        raise SafeError('invalid configuration')
                    interval, duration = config.get('interval', 300), config.get('deadline', 30)
                    if type(interval) not in (int, float) or not 60 <= interval <= 86400 or type(duration) not in (int, float) or not 1 <= duration <= 30:
                        raise SafeError('invalid schedule')
                    module_path = self.directory / ('service_' + slug + '.py')
                    if not module_path.is_file():
                        raise SafeError('service module missing')
                    state = self.states.get(slug)
                    failed = state is not None and (state['error'] is not None or
                                                     any(row['status'] for row in state['result'] or []))
                    retry_interval = min(interval, 60) if failed else interval
                    if state is None or (not state['pending'] and now >= state['started'] + retry_interval):
                        previous = state
                        state = dict(started=now, deadline=None,
                                     result=state['result'] if state else None,
                                     completed=state.get('completed', now) if state else now,
                                     error=None, pending=True)
                        self.states[slug] = state
                        try:
                            self.jobs.put_nowait((slug, module_path, config, state, duration))
                        except queue.Full:
                            if previous is None:
                                self.states.pop(slug, None)
                            else:
                                self.states[slug] = previous
                            raise
                    expired = state['result'] is None or state['error'] is not None or (state['pending'] and state['deadline'] is not None and now >= state['deadline']) or now - state['completed'] >= interval + duration
                    error = state['error'] or ('service deadline exceeded' if state['deadline'] is not None and now >= state['deadline'] else 'awaiting first service result')
                    output.append(self.check(monitor_name, family, expired,
                                             error if expired else f"fresh; sample age={int(now - state['completed'])}s; interval={interval}s", 3))
                    for row in state['result'] or []:
                        output.append(self.check(row['name'], family, 1 if expired else row['status'],
                                                 (error if expired else row['detail']) + f"; sample age={int(now - state['completed'])}s", row.get('severity', 3)))
                except Exception as exc:
                    output.append(self.check(monitor_name, family, True,
                                             'functional configuration unavailable: ' + type(exc).__name__, 3))
        return output
