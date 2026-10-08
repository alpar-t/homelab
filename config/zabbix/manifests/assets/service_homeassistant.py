"""Read-only HA appliance configuration and always-on energy integration baseline."""
import json
import math


def run(ctx, config):
    names = ('Home Assistant authenticated configuration', 'Home Assistant energy entities')
    try:
        token = ctx.secret(config['credential_key'])
    except Exception:
        return [ctx.check(name, True, 'dedicated monitoring credential unavailable') for name in names]
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}

    def get(path):
        response = ctx.http(config['base_url'].rstrip('/') + path, headers=headers,
                            timeout=min(5, ctx.remaining()), max_bytes=131072)
        if response.status != 200:
            raise ValueError('API request rejected')
        value = json.loads(response.body)
        if not isinstance(value, dict):
            raise ValueError('invalid API shape')
        return value

    rows = []
    try:
        value = get('/api/config')
        components = value.get('components')
        healthy = (isinstance(value.get('version'), str) and bool(value['version'])
                   and isinstance(components, list)
                   and all(item in components for item in config['required_components']))
        rows.append(ctx.check(names[0], not healthy,
                              'authenticated configuration and required integrations available' if healthy
                              else 'configuration schema or required integrations unavailable'))
    except Exception:
        rows.append(ctx.check(names[0], True, 'authenticated configuration request unavailable'))
    failures = 0
    for entity in config['numeric_entities']:
        try:
            value = get('/api/states/' + entity)
            if value.get('entity_id') != entity or not isinstance(value.get('state'), str):
                raise ValueError('invalid entity shape')
            if not math.isfinite(float(value['state'])):
                raise ValueError('invalid numeric state')
        except Exception:
            failures += 1
    rows.append(ctx.check(names[1], failures > 0,
                          f'expected always-on numeric entities: {len(config["numeric_entities"])}; unavailable: {failures}'))
    return rows
