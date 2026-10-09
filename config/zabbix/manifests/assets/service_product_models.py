"""Existing Kubernetes worker telemetry; never reach the arbitrary-script renderer."""


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
    for workload in ('product-model-api', 'product-model-renderer'):
        try:
            good = inventory is not None and observed_ready(inventory[workload])
            detail = 'existing Kubernetes readiness observed; internal API/render functionality unproven' if good else 'workload not ready or inventory unavailable'
        except Exception:
            good, detail = False, 'workload inventory missing or malformed'
        rows.append(ctx.check('Product models workload ' + workload, not good, detail))
    for name in ('Product models worker contract', 'Product models renderer dependencies', 'Product models render deadline'):
        rows.append(dict(ctx.check(name, True,
            'coverage deferred: preserve private worker/renderer listeners; no API token, render or collector ingress', severity=1), observation='deferred', notification='dashboard'))
    return rows
