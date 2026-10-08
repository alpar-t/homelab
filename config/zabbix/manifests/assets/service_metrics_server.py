"""Validate resource metrics freshness without interpreting CPU/memory load."""
from datetime import datetime
import math
import re


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)', value):
        raise ValueError('invalid timestamp')
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def listing(ctx, path, kind):
    # The existing Kubernetes client has a 15-second socket timeout. Reserve
    # that budget before each of our two calls; never loop on pagination.
    if ctx.remaining() < 15:
        raise TimeoutError('insufficient request budget')
    data = ctx.kube.get(path + '?limit=100')
    if (not isinstance(data, dict) or data.get('kind') != kind
            or not isinstance(data.get('items'), list) or not data['items']
            or len(data['items']) > 100 or data.get('metadata', {}).get('continue')):
        raise ValueError('invalid or incomplete list')
    return data['items']


def run(ctx, config):
    try:
        max_age = config['max_age_seconds']
        skew = config['future_skew_seconds']
        grace = config['node_startup_grace_seconds']
        if not (0 < max_age <= 300 and 0 <= skew <= 30 and 0 <= grace <= 600
                and math.isfinite(ctx.now)):
            raise ValueError('invalid policy')
        nodes = listing(ctx, '/api/v1/nodes', 'NodeList')
        metrics = listing(ctx, '/apis/metrics.k8s.io/v1beta1/nodes', 'NodeMetricsList')
        expected, known = set(), set()
        for node in nodes:
            name = node['metadata']['name']
            if not isinstance(name, str) or not name or name in known:
                raise ValueError('invalid node identity')
            known.add(name)
            started = timestamp(node['metadata']['creationTimestamp'])
            ready = [c for c in node['status']['conditions'] if c['type'] == 'Ready']
            if len(ready) != 1:
                raise ValueError('missing node condition')
            transitioned = timestamp(ready[0]['lastTransitionTime'])
            if max(started, transitioned) > ctx.now + skew:
                raise ValueError('node clock skew')
            if ctx.now - max(started, transitioned) >= grace:
                expected.add(name)
        seen, stale = set(), 0
        for sample in metrics:
            name = sample['metadata']['name']
            if name not in known or name in seen:
                raise ValueError('unexpected or duplicate metrics')
            seen.add(name)
            age = ctx.now - timestamp(sample['timestamp'])
            window = sample['window']
            if not isinstance(window, str) or not re.fullmatch(r'\d+(?:\.\d+)?s', window):
                raise ValueError('invalid metrics window')
            if not 0 < float(window[:-1]) <= max_age:
                raise ValueError('invalid metrics window')
            usage = sample['usage']
            if not isinstance(usage, dict) or any(
                    not isinstance(usage.get(k), str) or not re.fullmatch(
                        r'\d+(?:\.\d+)?(?:[numkKMGTPE]|[KMGTPE]i)?', usage[k])
                    for k in ('cpu', 'memory')):
                raise ValueError('invalid usage')
            stale += int(age > max_age or age < -skew)
        missing = len(expected - seen)
        return [ctx.check('Metrics-server fresh node coverage', bool(stale or missing),
                          f'nodes={len(known)}; samples={len(seen)}; missing={missing}; '
                          f'stale_or_future={stale}; startup_grace={len(known - expected)}')]
    except Exception:
        return [ctx.check('Metrics-server fresh node coverage', True,
                          'Resource metrics or node inventory unavailable/invalid')]
