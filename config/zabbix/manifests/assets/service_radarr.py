"""Observe the existing application container without copying its admin API key."""


def run(ctx, config):
    try:
        if ctx.remaining() < 16:
            raise TimeoutError()
        page = ctx.kube.get('/api/v1/namespaces/media/pods?labelSelector=app.kubernetes.io%2Fname%3Darr-stack&limit=10')
        if page.get('metadata', {}).get('continue'):
            raise ValueError('incomplete inventory')
        pods = [p for p in page['items'] if not p.get('metadata', {}).get('deletionTimestamp')]
        if len(pods) != 1:
            raise ValueError('expected one workload')
        states = [s for s in pods[0].get('status', {}).get('containerStatuses', []) if s.get('name') == 'radarr']
        good = (pods[0].get('status', {}).get('phase') == 'Running' and len(states) == 1
                and states[0].get('ready') is True and 'running' in states[0].get('state', {}))
        detail = 'existing Kubernetes container readiness observed; application internals unproven' if good else 'application container not ready'
    except Exception:
        good, detail = False, 'application container inventory unavailable or malformed'
    rows = [ctx.check('Radarr' + ' container readiness', not good, detail)]
    for name in ('Radarr system health', 'Radarr root folders'):
        rows.append(dict(ctx.check(name, True,
            'coverage deferred: native application API key permits administrative writes; no key is mounted', severity=1), observation='deferred', notification='dashboard'))
    return rows
