"""Passive Intel GPU registration check; no device allocation or host access."""
from datetime import datetime


def run(ctx, config):
    # One bounded API response; existing infrastructure checks cover missing nodes.
    result = ctx.kube.get('/api/v1/nodes?limit=100')
    if not isinstance(result.get('items'), list) or result.get('metadata', {}).get('continue'):
        raise ValueError('invalid or incomplete node inventory')
    nodes = {n['metadata']['name']: n for n in result['items']}
    records = []
    for name in config['expected_nodes']:
        node = nodes.get(name)
        if node is None:
            records.append(ctx.check('Platform GPU registration ' + name, True,
                                     'Expected GPU node missing'))
            continue
        if any(node['metadata'].get('labels', {}).get(k) != v
               for k, v in config['plugin_node_selector'].items()):
            records.append(ctx.check('Platform GPU registration ' + name, False,
                                     'Outside configured plugin selector'))
            continue
        ready = next((c for c in node['status'].get('conditions', [])
                      if c.get('type') == 'Ready'), None)
        if ready is None:
            raise ValueError('missing node readiness condition')
        observation = 'known'
        if ready.get('status') != 'True':
            observation = 'unknown'
            detail, bad = 'Node not Ready; infrastructure check covers availability', False
        else:
            since = datetime.fromisoformat(ready['lastTransitionTime'].replace('Z', '+00:00')).timestamp()
            if ctx.now - since < config['ready_grace_seconds']:
                observation = 'unknown'
                detail, bad = 'Node recovery grace; GPU registration may be pending', False
            else:
                value = node['status'].get('allocatable', {}).get(config['resource'], '0')
                if not isinstance(value, str) or not value.isdecimal():
                    raise ValueError('invalid GPU allocatable quantity')
                count = int(value)
                bad = count < config['minimum_allocatable']
                detail = 'GPU allocatable=%d; expected at least %d' % (count, config['minimum_allocatable'])
        records.append(ctx.check('Platform GPU registration ' + name, bad, detail, observation=observation))
    return records
