"""Read native SQL exporter metrics, without database credentials or writes."""
import concurrent.futures
import datetime
import ipaddress
import math
import re


def metrics(body):
    result = {}
    for line in body.decode('utf-8').splitlines():
        match = re.fullmatch(r'(cnpg_[a-zA-Z0-9_]+)(?:\{[^\n]*\})?\s+([^\s]+)(?:\s+\d+)?', line)
        if match and match[1] in {'cnpg_pg_replication_in_recovery', 'cnpg_pg_replication_lag',
                                   'cnpg_pg_replication_is_wal_receiver_up',
                                   'cnpg_pg_replication_streaming_replicas',
                                   'cnpg_pg_postmaster_start_time', 'cnpg_pg_database_size_bytes'}:
            value = float(match[2])
            if not math.isfinite(value):
                raise ValueError('nonfinite metric')
            result.setdefault(match[1], []).append(value)
    return result


def scalar(values, key):
    found = values.get(key, [])
    if len(found) != 1:
        raise ValueError('required scalar metric missing or ambiguous')
    return found[0]


def recent(value, now, grace):
    if not value:
        return False
    age = now - datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    return 0 <= age < grace


def scrape(ctx, ip):
    address = ipaddress.ip_address(ip)
    host = f'[{address}]' if address.version == 6 else str(address)
    response = ctx.http(f'http://{host}:9187/metrics', timeout=min(3, ctx.remaining()),
                        max_bytes=262144)
    if response.status != 200:
        raise ValueError('metrics HTTP unavailable')
    return metrics(response.body)


def run(ctx, config):
    # Exactly one API request, no pagination loop or per-cluster API fanout.
    if ctx.remaining() < 6:
        raise TimeoutError('inventory deadline')
    page = ctx.kube.get('/apis/postgresql.cnpg.io/v1/clusters?limit=100')
    if page.get('metadata', {}).get('continue') or len(page['items']) > 100:
        raise ValueError('inventory exceeds bounded baseline')
    inventory = {(c['metadata']['namespace'], c['metadata']['name']): c for c in page['items']}
    checks, jobs, clusters = [], [], []
    for namespace, name in config['clusters']:
        label = f'CNPG SQL and replication {namespace}/{name}'
        cluster = inventory.get((namespace, name))
        if not cluster:
            checks.append(ctx.check(label, True, 'Expected cluster inventory unavailable'))
            continue
        spec, status = cluster['spec'], cluster.get('status', {})
        grace = config['grace_seconds']
        ready = next((c for c in status.get('conditions', []) if c['type'] == 'Ready'), {})
        if (spec.get('nodeMaintenanceWindow', {}).get('inProgress') or
                cluster['metadata'].get('annotations', {}).get('cnpg.io/hibernation') == 'on' or
                recent(status.get('targetPrimaryTimestamp'), ctx.now, grace) or
                recent(ready.get('lastTransitionTime'), ctx.now, grace)):
            checks.append(ctx.check(label, False, 'Maintenance or recent transition: SQL/replication observation deferred', observation='unknown'))
            continue
        reported = status.get('instancesReportedState', {})
        expected = spec['instances']
        if not 1 <= expected <= 8 or status.get('currentPrimary') not in reported:
            checks.append(ctx.check(label, True, 'Expected instance SQL coverage unavailable'))
            continue
        entry = {'label': label, 'primary': status.get('currentPrimary'),
                 'replica': spec.get('replica', {}).get('enabled', False), 'samples': [], 'failed_instances': set(), 'coverage_degraded': len(reported) != expected, 'deferred': False, 'expected': expected}
        clusters.append(entry)
        for instance, state in reported.items():
            jobs.append((entry, instance, state['ip']))
    if len(jobs) > 80:
        raise ValueError('instance limit exceeded')
    # Joined workers never survive a poll; foundation bounds each body read.
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
    pending = {pool.submit(scrape, ctx, ip): (entry, instance) for entry, instance, ip in jobs}
    try:
        done, unfinished = concurrent.futures.wait(pending, timeout=ctx.remaining())
        for future in done:
            entry, instance = pending[future]
            try:
                entry['samples'].append((instance, future.result()))
            except Exception:
                entry['failed_instances'].add(instance)
        for future in unfinished:
            entry, instance = pending[future]
            entry['failed_instances'].add(instance)
            future.cancel()
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    for entry in clusters:
        failures = []
        critical = entry['primary'] in entry['failed_instances']
        if entry['failed_instances']:
            failures.append('instance metrics unavailable')
        if entry['coverage_degraded']:
            failures.append('expected replica coverage incomplete')
        for instance, values in entry['samples']:
            try:
                recovery = scalar(values, 'cnpg_pg_replication_in_recovery')
                lag = scalar(values, 'cnpg_pg_replication_lag')
                receiver = scalar(values, 'cnpg_pg_replication_is_wal_receiver_up')
                streaming = scalar(values, 'cnpg_pg_replication_streaming_replicas')
                start = scalar(values, 'cnpg_pg_postmaster_start_time')
                database = values.get('cnpg_pg_database_size_bytes', [])
                if not database or any(v < 0 for v in database) or recovery not in (0, 1) or lag < 0:
                    raise ValueError('SQL metric schema')
                if 0 <= ctx.now - start < config['grace_seconds']:
                    entry['deferred'] = True
                    continue
                expected_role = int(entry['replica'] or instance != entry['primary'])
                if recovery != expected_role:
                    failures.append('SQL recovery role disagrees with designated primary')
                    critical |= instance == entry['primary']
                if recovery and receiver != 1:
                    failures.append('standby WAL receiver disconnected')
                if not recovery and streaming < entry['expected'] - 1:
                    failures.append('primary streaming replica coverage incomplete')
                if recovery and lag > config['lag_seconds']:
                    failures.append('unapplied WAL replay lag exceeds threshold')
            except Exception:
                failures.append('required SQL metrics invalid or missing')
                critical |= instance == entry['primary']
        bad = bool(failures)
        checks.append(ctx.check(entry['label'], bad, '; '.join(sorted(set(failures))) if bad else
                                'SQL database/recovery queries succeeded; roles and replay lag within policy',
                                severity=3 if critical or not bad else 2,
                                notification='page' if critical or not bad else 'dashboard',
                                observation='unknown' if entry['deferred'] and not bad else 'known'))
    return checks
