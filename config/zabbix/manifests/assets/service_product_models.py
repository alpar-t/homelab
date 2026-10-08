"""Passive worker and Blender dependency contract; never submit a render."""
import json
import math


def fetch(ctx, url):
    response = ctx.http(url, timeout=min(5, ctx.remaining()), max_bytes=4096)
    if response.status != 200:
        raise ValueError("unavailable")
    value = json.loads(response.body)
    if not isinstance(value, dict):
        raise ValueError("invalid contract")
    return value


def run(ctx, config):
    records = []
    try:
        health = fetch(ctx, config['api_url'] + '/health')
        boundary = ctx.http(config['api_url'] + '/internal/models/' + '0' * 32,
                            timeout=min(5, ctx.remaining()), max_bytes=4096)
        denied = json.loads(boundary.body)
        good = health.get('ok') is True and boundary.status == 401 and denied == {'error': 'unauthorized'}
        records.append(ctx.check('Product models worker contract', not good,
                                 'worker status and authentication contract valid' if good else 'worker status or authentication contract failed'))
    except Exception:
        records.append(ctx.check('Product models worker contract', True, 'worker contract unavailable or malformed'))
    try:
        info = fetch(ctx, config['renderer_url'] + '/capabilities')
        busy, age = info.get('busy'), info.get('activeSeconds')
        valid_age = (busy is False and age is None) or (busy is True and type(age) in (int, float) and math.isfinite(age) and age >= 0)
        valid = type(info.get('schema')) is int and info['schema'] == 1 and type(info.get('renderTimeoutSeconds')) is int and info['renderTimeoutSeconds'] == 900 and valid_age
        good = valid and info.get('blenderAvailable') is True and info.get('scratchWritable') is True
        records.append(ctx.check('Product models renderer dependencies', not good,
                                 'Blender executable and scratch access available' if good else 'renderer capability contract or dependencies unavailable'))
        stalled = valid and busy and age > 900 + config.get('render_grace_seconds', 300)
        records.append(ctx.check('Product models render deadline', not valid or stalled,
                                 'active render exceeded deadline and grace' if stalled else ('renderer idle or within render deadline' if valid else 'render activity contract malformed')))
    except Exception:
        records.extend([ctx.check(name, True, 'renderer capabilities unavailable or malformed') for name in
                        ('Product models renderer dependencies', 'Product models render deadline')])
    return records
