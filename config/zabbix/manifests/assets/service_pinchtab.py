"""Kubernetes browser workload telemetry only; preserve browser network isolation."""


def deployments(ctx, namespace):
    if ctx.remaining() < 16:
        raise TimeoutError()
    page = ctx.kube.get('/apis/apps/v1/namespaces/' + namespace + '/deployments?limit=100')
    if page.get('metadata', {}).get('continue') or len(page['items']) > 100:
        raise ValueError('incomplete inventory')
    return {d['metadata']['name']: d for d in page['items']}


def observed_ready(obj):
    desired = obj['spec'].get('replicas', 1)
    status = obj.get('status', {})
    return (type(desired) is int and desired > 0
            and not obj['metadata'].get('deletionTimestamp')
            and status.get('observedGeneration', 0) >= obj['metadata']['generation']
            and status.get('availableReplicas', 0) >= desired
            and status.get('readyReplicas', 0) >= desired)


def run(ctx, config):
    rows = []
    try:
        inventory = deployments(ctx, config['namespace'])
    except Exception:
        inventory = None
    for target in config['targets']:
        name = 'PinchTab ' + target['name']
        try:
            good = inventory is not None and observed_ready(inventory[target['deployment']])
            detail = 'existing Kubernetes readiness observed; authenticated browser internals unproven' if good else 'browser workload not ready or inventory unavailable'
        except Exception:
            good, detail = False, 'browser workload inventory missing or malformed'
        rows.append(ctx.check(name, not good, detail))
        rows.append(dict(ctx.check(name + ' authenticated coverage', True,
            'coverage deferred: native PinchTab bearer grants browser/profile control; no token or network grant', severity=1), observation='deferred', notification='dashboard'))
    return rows
