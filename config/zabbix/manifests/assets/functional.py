"""Bounded, credential-conscious functional service checks (standard library only)."""
import hashlib
import math
import os
import importlib.util
import http.client
import io
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


def _stream_socket(stream):
    for _ in range(3):
        raw = getattr(stream, 'raw', None)
        sock = getattr(raw, '_sock', None)
        if sock is not None:
            return sock
        stream = getattr(stream, 'fp', None)
        if stream is None:
            break
    return None


class DeadlineReader(io.RawIOBase):
    """Apply elapsed budgets below HTTP chunk-size/trailer buffered readlines."""
    def __init__(self, source, deadline):
        self.source, self.deadline = source, deadline
        self._sock = _stream_socket(source)

    def readable(self):
        return True

    def readinto(self, target):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise SafeError('response deadline exceeded')
        if self._sock is not None:
            self._sock.settimeout(remaining)
        # The underlying BufferedReader.read1 performs at most one raw read.
        part = self.source.read1(len(target))
        if time.monotonic() >= self.deadline:
            raise SafeError('response deadline exceeded')
        target[:len(part)] = part
        return len(part)

    def close(self):
        try:
            self.source.close()
        finally:
            super().close()


def read_response(response, deadline, max_bytes):
    """Read bounded bytes without buffering through a slow stream indefinitely.

    urllib's timeout is an inactivity timeout. read1 performs at most one raw
    read; resetting its socket timeout to the remaining elapsed budget prevents
    a trickle of bytes from extending a request. DNS resolution is synchronous
    and remains subject to the platform resolver's own timeout.
    """
    # HTTPResponse.read1 may buffer multiple receives for chunk framing. Put
    # elapsed enforcement below those internal readline operations as well.
    message = response
    for _ in range(3):
        if isinstance(message, http.client.HTTPResponse) and message.chunked:
            message.fp = io.BufferedReader(DeadlineReader(message.fp, deadline))
            break
        message = getattr(message, 'fp', None)
        if message is None:
            break
    chunks, size = [], 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SafeError('response deadline exceeded')
        # HTTPError wraps an HTTPResponse; ordinary responses expose fp directly.
        sock = _stream_socket(response)
        if sock is not None:
            sock.settimeout(remaining)
        chunk = response.read1(min(16384, max_bytes + 1 - size))
        if time.monotonic() >= deadline:
            raise SafeError('response deadline exceeded')
        if not chunk:
            return b''.join(chunks)
        size += len(chunk)
        if size > max_bytes:
            raise SafeError('response exceeds byte limit')
        chunks.append(chunk)


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

    def check(self, name, bad, detail, severity=3, observation='known', workloads=None, notification=None):
        row = dict(name=name, status=int(bool(bad)), detail=detail, severity=severity, observation=observation)
        if workloads is not None:
            row['workloads'] = workloads
        if notification is not None:
            row['notification'] = notification
        return row

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
            request_deadline = min(self.deadline, time.monotonic() + timeout)
            try:
                response = opener.open(request, timeout=request_deadline - time.monotonic())
            except urllib.error.HTTPError as error:
                response = error
            with response:
                body = read_response(response, request_deadline, max_bytes)
                return SimpleNamespace(status=response.code, headers=dict(response.headers),
                                       body=body)
        except SafeError:
            raise
        except Exception:
            raise SafeError('HTTP request failed') from None


class FunctionalChecks:
    """Schedule real observations and publish latched incident state, not cache samples."""
    def __init__(self, kube, directory, check, credentials=Path('/credentials'), state_path=None):
        self.kube, self.directory, self.check = kube, Path(directory), check
        self.credentials, self.state_path = credentials, Path(state_path) if state_path else None
        self.jobs, self.lock = queue.Queue(maxsize=64), threading.Lock()
        self.states, self.modules, self.persist_error, self.load_error = {}, {}, False, False
        self.saved_telemetry = {}
        self.saved = self._load()
        for _ in range(3):
            threading.Thread(target=self._worker, daemon=True).start()

    def _load(self):
        if self.state_path is None or not self.state_path.exists():
            return {}
        try:
            if self.state_path.stat().st_size > 4194304:
                raise ValueError('state size')
            value = json.loads(self.state_path.read_text())
            self.load_error = self.persist_error = value.get('recovery_required', False)
            if value.get('version') != 1 or not isinstance(value.get('services'), dict) or len(value['services']) > 128:
                raise ValueError('state schema')
            for slug, rows in value['services'].items():
                if not re.fullmatch(r'[a-z0-9_]+', slug) or not isinstance(rows, dict) or len(rows) > 128:
                    raise ValueError('state inventory')
                for name, row in rows.items():
                    if not isinstance(name, str) or not 1 <= len(name) <= 160 or not isinstance(row, dict):
                        raise ValueError('state row')
                    if set(row) != {'status', 'failures', 'recoveries', 'failure_since', 'observed_at', 'sequence', 'severity', 'notification', 'established'}:
                        raise ValueError('state fields')
                    if type(row['established']) is not bool:
                        raise ValueError('state baseline')
                    if row['status'] not in (0, 1) or row['notification'] not in ('page', 'dashboard'):
                        raise ValueError('state values')
                    for field in ('failures', 'recoveries', 'sequence', 'severity'):
                        if type(row[field]) is not int or row[field] < 0 or row[field] > (5 if field == 'severity' else 1000000000):
                            raise ValueError('state counters')
                    for field in ('failure_since', 'observed_at'):
                        if row[field] is not None and (type(row[field]) not in (int, float) or not math.isfinite(row[field]) or row[field] < 0):
                            raise ValueError('state timestamp')
            telemetry = value.get('telemetry', {})
            if not isinstance(telemetry, dict) or len(telemetry) > 128:
                raise ValueError('telemetry state inventory')
            for slug, row in telemetry.items():
                if not re.fullmatch(r'[a-z0-9_]+', slug) or not isinstance(row, dict) or set(row) not in ({'status', 'failures', 'recoveries', 'failure_since'}, {'status', 'failures', 'recoveries', 'failure_since', 'established'}):
                    raise ValueError('telemetry state fields')
                if type(row['status']) is not int or row['status'] not in (0, 1):
                    raise ValueError('telemetry state status')
                if any(type(row[k]) is not int or not 0 <= row[k] <= 1000000000 for k in ('failures', 'recoveries')):
                    raise ValueError('telemetry state counters')
                stamp = row['failure_since']
                if stamp is not None and (type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0):
                    raise ValueError('telemetry state time')
                row['recoveries'] = 0  # Restored healthy history cannot recover.
                row['established'] = row['status'] == 1
            self.saved_telemetry = telemetry
            for rows in value['services'].values():
                for row in rows.values():
                    # Restored healthy state is history, not fresh recovery evidence.
                    # In particular an older successful write cannot close a failure
                    # whose later persistence attempt failed before pod restart.
                    if row['status'] == 0:
                        row.update(established=False, recoveries=0)
            return value['services']
        except Exception:
            # A corrupt state must not silently manufacture healthy recovery.
            self.persist_error = self.load_error = True
            return {}

    def _persist(self):
        if self.state_path is None:
            return
        fields = ('status', 'failures', 'recoveries', 'failure_since', 'observed_at', 'sequence', 'severity', 'notification', 'established')
        baseline_restored = bool(self.states) and all(
            state['rows'] and all(row['established'] for row in state['rows'].values())
            for state in self.states.values())
        recovery_required = self.load_error and not baseline_restored
        value = {'version': 1, 'recovery_required': recovery_required, 'services': {slug: {name: {key: row[key] for key in fields}
                 for name, row in state['rows'].items()} for slug, state in self.states.items()},
                 'telemetry': {slug: state.get('telemetry', dict(status=0, failures=0, recoveries=0, failure_since=None, established=False))
                               for slug, state in self.states.items()}}
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(self.state_path.suffix + '.tmp')
            with temporary.open('w') as stream:
                os.chmod(temporary, 0o600)
                json.dump(value, stream, separators=(',', ':'))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
            self.persist_error = recovery_required
            if not self.persist_error:
                self.load_error = False
        except Exception:
            self.persist_error = True

    @staticmethod
    def _policy(config):
        interval, duration = config.get('interval', 900), config.get('deadline', 30)
        grace = config.get('failure_grace_seconds', 900)
        failed, recovered = config.get('minimum_failure_observations', 2), config.get('minimum_recovery_observations', 2)
        for value, low, high in ((interval, 60, 86400), (duration, 1, 30), (grace, 0, 172800)):
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise SafeError('invalid schedule')
        if any(type(v) is not int or not 1 <= v <= 20 for v in (failed, recovered)):
            raise SafeError('invalid observation policy')
        if type(config.get('severity', 3)) is not int or not 0 <= config.get('severity', 3) <= 5:
            raise SafeError('invalid severity policy')
        if config.get('notification', 'page') not in ('page', 'dashboard'):
            raise SafeError('invalid notification policy')
        FunctionalChecks._workloads(config.get('workloads', []))
        overrides = config.get('check_workloads', {})
        if not isinstance(overrides, dict) or len(overrides) > 128:
            raise SafeError('invalid check workloads')
        for name, identities in overrides.items():
            if not isinstance(name, str) or not name.strip() or len(name) > 160:
                raise SafeError('invalid check identity')
            FunctionalChecks._workloads(identities)
        return interval, duration, grace, failed, recovered

    @staticmethod
    def _workloads(value):
        if not isinstance(value, list) or len(value) > 64:
            raise SafeError('invalid workloads')
        for item in value:
            if (not isinstance(item, dict) or set(item) != {'namespace', 'kind', 'name'}
                    or item['kind'] not in ('Deployment', 'DaemonSet', 'StatefulSet', 'Cluster', 'Node')
                    or any(not isinstance(item[k], str) or len(item[k]) > 253
                           or not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', item[k]) for k in ('namespace', 'name'))):
                raise SafeError('invalid workload identity')
        return value

    @staticmethod
    def _validate(records):
        if not isinstance(records, list) or not 1 <= len(records) <= 128:
            raise SafeError('invalid service results')
        names = set()
        for row in records:
            if (not isinstance(row, dict) or not isinstance(row.get('name'), str)
                    or not row['name'].strip() or len(row['name']) > 160 or row['name'] in names
                    or type(row.get('status')) is not int or row['status'] not in (0, 1)
                    or not isinstance(row.get('detail'), str) or len(row['detail']) > 1800
                    or type(row.get('severity', 3)) is not int or not 0 <= row.get('severity', 3) <= 5
                    or row.get('observation', 'known') not in ('known', 'unknown', 'deferred')
                    or row.get('notification', 'page') not in ('page', 'dashboard')):
                raise SafeError('invalid service result')
            if 'workloads' in row:
                FunctionalChecks._workloads(row['workloads'])
            names.add(row['name'])

    def _observe(self, state, records, config, stamp):
        _, _, grace, minimum_failed, minimum_recovered = self._policy(config)
        if len(set(state['rows']) | {r['name'] for r in records}) > 128:
            raise SafeError('observation inventory bound')
        for incoming in records:
            name = incoming['name']
            severity = min(incoming.get('severity', 3), config.get('severity', 3))
            notification = incoming.get('notification', 'dashboard' if severity <= 2 else config.get('notification', 'page'))
            previous = state['rows'].get(name)
            row = previous or dict(status=0, failures=0, recoveries=0, failure_since=None,
                                   observed_at=None, sequence=0, established=False, severity=severity, notification=notification)
            observation = incoming.get('observation', 'known')
            row.update(detail=incoming['detail'], raw_status='unknown',
                       workloads=incoming.get('workloads', config.get('check_workloads', {}).get(name, config.get('workloads', []))))
            if observation == 'deferred':
                # Keep old incidents latched if coverage is deliberately withdrawn.
                if not row['status']:
                    row.update(status=1, severity=1, notification='dashboard', established=True)
                row['raw_status'] = 'deferred'
            elif observation == 'known':
                bad = incoming['status'] == 1
                if row['raw_status'] == 'unknown' and row['severity'] == 1 and severity > 1:
                    row.update(status=0, established=False)
                if row['status'] and (not bad or severity < row['severity']):
                    # A partial/first healthy observation must not create a new
                    # higher-priority incident while the old one is recovering.
                    severity, notification = row['severity'], row['notification']
                row.update(raw_status='failed' if bad else 'ok', observed_at=stamp,
                           sequence=min(row['sequence'] + 1, 1000000000),
                           severity=severity, notification=notification)
                if bad:
                    row['recoveries'] = 0
                    row['failures'] = min(row['failures'] + 1, 1000000000)
                    if row['failure_since'] is None or row['failure_since'] > stamp:
                        row['failure_since'] = stamp
                    if row['failures'] >= minimum_failed and stamp - row['failure_since'] >= grace:
                        row['status'], row['established'] = 1, True
                else:
                    row['failures'], row['failure_since'] = 0, None
                    row['recoveries'] = min(row['recoveries'] + 1, 1000000000)
                    if row['recoveries'] >= minimum_recovered:
                        row['status'], row['established'] = 0, True
            else:
                # Unknown is not recovery and breaks a run of positive evidence.
                row['recoveries'] = 0
            state['rows'][name] = row
        names = {r['name'] for r in records}
        for name, row in state['rows'].items():
            if name not in names:
                row.update(raw_status='unknown', detail='no new observation for this check', recoveries=0)

    def _observe_telemetry(self, state, bad, config, stamp):
        _, _, grace, minimum_failed, minimum_recovered = self._policy(config)
        row = state.setdefault('telemetry', dict(status=0, failures=0, recoveries=0, failure_since=None, established=False))
        if bad:
            row['recoveries'] = 0
            row['failures'] = min(row['failures'] + 1, 1000000000)
            if row['failure_since'] is None or row['failure_since'] > stamp:
                row['failure_since'] = stamp
            if row['failures'] >= minimum_failed and stamp - row['failure_since'] >= grace:
                row['status'], row['established'] = 1, True
        else:
            row['failures'], row['failure_since'] = 0, None
            row['recoveries'] = min(row['recoveries'] + 1, 1000000000)
            if row['recoveries'] >= minimum_recovered:
                row['status'], row['established'] = 0, True

    def _worker(self):
        while True:
            slug, module_path, config, state, duration = self.jobs.get()
            interval = config.get('interval', 900)
            deadline = time.monotonic() + duration
            with self.lock:
                state['deadline'] = deadline
            try:
                source = module_path.read_bytes()
                cached = self.modules.get(slug)
                if cached is None or cached[0] != source:
                    spec = importlib.util.spec_from_file_location('functional_service_' + slug, module_path)
                    module = importlib.util.module_from_spec(spec)
                    exec(compile(source, str(module_path), 'exec'), module.__dict__)
                    self.modules[slug] = (source, module)
                else:
                    module = cached[1]
                records = module.run(Context(self.kube, deadline, self.credentials), config)
                self._validate(records)
                if time.monotonic() >= deadline:
                    raise SafeError('service deadline exceeded')
                result, error = records, None
            except Exception as exc:
                result, error = None, 'functional observation unavailable: ' + type(exc).__name__
            with self.lock:
                finished = time.monotonic()
                state.update(error=error, pending=False, finished=finished,
                             next_due=finished + interval, deadline=None)
                try:
                    if result is not None:
                        self._observe(state, result, config, time.time())
                        state['completed'] = finished
                    else:
                        for row in state['rows'].values():
                            row.update(raw_status='unknown', recoveries=0)
                    self._observe_telemetry(state, result is None, config, time.time())
                    self._persist()
                except Exception:
                    state['error'] = 'functional state update unavailable'
                    self.persist_error = True
            self.jobs.task_done()

    def _render(self, state, config, expired=False):
        output = []
        for name, row in state['rows'].items():
            # With no trustworthy prior baseline, absence discards the item sample.
            # Do not send cached zeroes that could close a pre-existing Zabbix event.
            if not row.get('established', False) and not row['status']:
                continue
            raw = 'unknown' if expired else row.get('raw_status', 'unknown')
            evidence = 'observation unavailable; confirmed state retained' if expired else row.get('detail', 'restored confirmed state; awaiting real observation')
            evidence += (f"; observation={raw}; independent failures={row['failures']}; "
                         f"independent recoveries={row['recoveries']}; observed_at={row['observed_at']}")
            value = self.check(name, 'functional/' + state['slug'], row['status'], evidence, row['severity'])
            value.update(notification=row['notification'], workloads=row.get('workloads', config.get('check_workloads', {}).get(name, config.get('workloads', []))),
                         raw_status=raw, observed_at=row['observed_at'], observation_sequence=row['sequence'],
                         failure_observations=row['failures'], recovery_observations=row['recoveries'])
            output.append(value)
        return output

    def collect(self):
        paths = {p.stem[len('service_'):]: p for p in self.directory.glob('service_*.json')}
        for p in self.directory.glob('service_*.py'):
            paths.setdefault(p.stem[len('service_'):], self.directory / (p.stem + '.json'))
        output, now, persist_dirty = [], time.monotonic(), False
        queue_allowance = max(60, math.ceil(len(paths) / 3) * 30 + 60)
        with self.lock:
            for slug, config_path in sorted(paths.items()):
                family, monitor_name = 'functional/' + slug, 'Functional monitoring ' + slug
                state, config = self.states.get(slug), {}
                try:
                    if not re.fullmatch(r'[a-z0-9_]+', slug):
                        raise SafeError('invalid slug')
                    config = json.loads(config_path.read_text())
                    if not isinstance(config, dict):
                        raise SafeError('invalid configuration')
                    interval, duration, _, _, _ = self._policy(config)
                    module_path = self.directory / ('service_' + slug + '.py')
                    if not module_path.is_file():
                        raise SafeError('service module missing')
                    if state is None:
                        # Stable phase spreads startup requests over the full cadence.
                        phase = int.from_bytes(hashlib.sha256(slug.encode()).digest()[:8], 'big') % interval
                        state = dict(slug=slug, rows=self.saved.get(slug, {}), next_due=now + phase,
                                     initial_deadline=now + phase + queue_allowance + duration,
                                     deadline=None, pending=False, error=None, completed=None,
                                     telemetry=self.saved_telemetry.get(slug, dict(status=0, failures=0, recoveries=0, failure_since=None, established=False)))
                        self.states[slug] = state
                    if not state['pending'] and now >= state['next_due']:
                        self.jobs.put_nowait((slug, module_path, config, state, duration))
                        state.update(pending=True, queued_at=now)
                    initial = state['completed'] is None and state['error'] is None
                    # A completed exception is an independent error observation,
                    # not permission to count every cached minute as another failure.
                    clock_expired = (state['pending'] and (
                        (state['deadline'] is not None and now >= state['deadline'])
                        or now - state.get('queued_at', state['initial_deadline']) > queue_allowance + duration))
                    clock_expired = clock_expired or (initial and now > state['initial_deadline'] and state['pending'])
                    telemetry = state['telemetry']
                    if clock_expired and not telemetry['status']:
                        telemetry['status'], telemetry['recoveries'], telemetry['established'] = 1, 0, True
                        persist_dirty = True
                    expired = clock_expired or state['error'] is not None
                    unavailable = telemetry['status'] == 1
                    detail = ('observation unavailable' if expired else 'warming; awaiting first real observation' if initial
                              else f"sample age={int(now - state['completed'])}s; interval={interval}s")
                    detail += ('; raw failures=' + str(sum(r.get('raw_status') == 'failed' for r in state['rows'].values()))
                               + '; awaiting independent baseline=' + str(sum(not r['established'] for r in state['rows'].values())))
                    detail += (f"; independent telemetry failures={telemetry['failures']}; "
                               f"independent telemetry recoveries={telemetry['recoveries']}")
                    monitor = self.check(monitor_name, family, unavailable, detail, 3)
                    monitor.update(notification=config.get('notification', 'page'), workloads=config.get('workloads', []),
                                   raw_status='unknown' if expired or initial else 'ok')
                    if telemetry['established'] or unavailable:
                        output.append(monitor)
                    else:
                        pending = self.check('Functional observation pending ' + slug, family, False, detail, 1)
                        pending.update(notification='dashboard', workloads=config.get('workloads', []), raw_status='unknown')
                        output.append(pending)
                    output.extend(self._render(state, config, expired))
                except Exception as exc:
                    monitor = self.check(monitor_name, family, True, 'functional configuration unavailable: ' + type(exc).__name__, 3)
                    monitor.update(notification='page', workloads=[], raw_status='unknown')
                    output.append(monitor)
                    if state:
                        output.extend(self._render(state, {}, True))
            if persist_dirty:
                self._persist()
            if self.persist_error:
                output.append(self.check('Functional observation state persistence', 'monitoring', True,
                                         'state unavailable; inspect local state storage', 3))
        return output
