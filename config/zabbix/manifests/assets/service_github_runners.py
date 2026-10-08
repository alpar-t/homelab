"""Passive ARC reconciliation; never reads jobs, logs or GitHub credentials."""
from datetime import datetime

_since = {}  # At most one timestamp per configured scale set; reset on recovery.


def items(ctx, namespace, resource):
    # Kubernetes.get has a fixed 15-second transport timeout.
    if ctx.remaining() < 16:
        raise ValueError('deadline')
    page = ctx.kube.get('/apis/actions.github.com/v1alpha1/namespaces/' +
                        namespace + '/' + resource + '?limit=500')
    if not isinstance(page.get('items'), list) or page.get('metadata', {}).get('continue'):
        raise ValueError('invalid or oversized inventory')
    return page['items']


def age(ctx, obj):
    stamp = datetime.fromisoformat(obj['metadata']['creationTimestamp'].replace('Z', '+00:00'))
    return max(0, ctx.now - stamp.timestamp())


def count(status, key):
    value = status.get(key, 0)
    if type(value) is not int or value < 0:
        raise ValueError('invalid counter')
    return value


def owned(obj, kind, name):
    return any(r.get('kind') == kind and r.get('name') == name
               for r in obj.get('metadata', {}).get('ownerReferences', []))


def run(ctx, config):
    for name in list(_since):
        if name not in config['sets']:
            _since.pop(name, None)
    sets = items(ctx, config['runner_namespace'], 'autoscalingrunnersets')
    ephemeral = items(ctx, config['runner_namespace'], 'ephemeralrunnersets')
    runners = items(ctx, config['runner_namespace'], 'ephemeralrunners')
    listeners = items(ctx, config['controller_namespace'], 'autoscalinglisteners')
    results = []
    for name in config['sets']:
        broken, failed, pending = False, 0, 0
        matched = [s for s in sets if s.get('metadata', {}).get('name') == name]
        linked = [s for s in ephemeral if owned(s, 'AutoscalingRunnerSet', name)
                  and not s.get('metadata', {}).get('deletionTimestamp')]
        listening = [s for s in listeners if s.get('spec', {}).get('autoscalingRunnerSetName') == name
                     and s.get('spec', {}).get('autoscalingRunnerSetNamespace') == config['runner_namespace']
                     and not s.get('metadata', {}).get('deletionTimestamp')]
        graph = len(matched) == 1 and bool(linked) and len(listening) == 1
        if graph:
            ars = matched[0]
            graph = (ars.get('status', {}).get('phase') == 'Running'
                     and not ars.get('metadata', {}).get('deletionTimestamp')
                     and listening[0]['spec'].get('ephemeralRunnerSetName') in
                     {s['metadata']['name'] for s in linked})
            for ers in linked:
                status = ers.get('status', {})
                broken |= status.get('phase') != 'Running'
                desired = count(ers.get('spec', {}), 'replicas')
                running = count(status, 'runningEphemeralRunners')
                failed += count(status, 'failedEphemeralRunners')
                current = count(status, 'currentReplicas')
                broken |= desired > current and running == 0
                for runner in runners:
                    if not owned(runner, 'EphemeralRunnerSet', ers['metadata']['name']):
                        continue
                    rs = runner.get('status', {})
                    phase = rs.get('phase', '')
                    failed += int(phase == 'Failed')
                    if phase not in ('Succeeded', 'Failed') and rs.get('ready') is not True:
                        pending += 1
                        broken |= age(ctx, runner) > config['grace_seconds']
        # Missing reconciliation objects and desired-capacity deficits need a
        # continuous observation grace; native runner creation times catch older
        # registration stalls immediately after collector restart.
        unhealthy = not graph or broken
        if unhealthy:
            _since.setdefault(name, ctx.now)
        else:
            _since.pop(name, None)
        delayed = unhealthy and ctx.now - _since[name] >= config['grace_seconds']
        stale_registration = graph and broken and any(
            owned(r, 'EphemeralRunnerSet', e['metadata']['name'])
            and r.get('status', {}).get('phase') not in ('Succeeded', 'Failed')
            and r.get('status', {}).get('ready') is not True
            and age(ctx, r) > config['grace_seconds']
            for e in linked for r in runners)
        results.append(ctx.check('ARC functional ' + name,
                                 delayed or stale_registration or failed > 0,
                                 f'reconciled={int(graph)}; failed={failed}; registering={pending}; '
                                 f'grace={config["grace_seconds"]}s; passive status'))
    return results
