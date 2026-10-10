"""Read-only Maintainerr dependency checks; never execute cleanup tasks."""
import json


def _read(ctx, base, path):
    response = ctx.http(base + path, timeout=min(5, ctx.remaining()),
                        max_bytes=131072)
    if response.status != 200:
        raise ValueError("unexpected HTTP status")
    return json.loads(response.body)


def run(ctx, config):
    base = config['url'].rstrip('/')
    results = []
    try:
        health = _read(ctx, base, '/api/health/ready')
        media = _read(ctx, base, '/api/media-server')
        valid = (isinstance(health, dict) and health.get('database') == 'ok'
                 and health.get('status') == 'ok' and isinstance(media, dict)
                 and isinstance(media.get('machineId'), str) and bool(media['machineId'])
                 and isinstance(media.get('version'), str)
                 and media['version'] not in ('', 'unknown'))
        results.append(ctx.check('Maintainerr database and media integration', not valid,
                                 'SQLite query and media-server status valid' if valid
                                 else 'Database or media-server contract unavailable'))
    except Exception as exc:
        results.append(ctx.check('Maintainerr database and media integration', True,
                                 'Read failed: ' + type(exc).__name__))
    for service in ('radarr', 'sonarr'):
        try:
            instance = config[service + '_id']
            if type(instance) is not int or instance < 1:
                raise ValueError('invalid instance ID')
            profiles = _read(ctx, base, f'/api/servarr/{service}/{instance}/profiles')
            # Maintainerr returns [] when upstream retrieval fails. Require a
            # profile because each configured installation has quality profiles.
            valid = (isinstance(profiles, list) and bool(profiles)
                     and all(isinstance(p, dict) and type(p.get('id')) is int
                             and p['id'] > 0 and isinstance(p.get('items'), list)
                             for p in profiles))
            results.append(ctx.check('Maintainerr ' + service + ' integration', not valid,
                                     'Quality-profile query valid' if valid
                                     else 'Quality-profile query empty or invalid'))
        except Exception as exc:
            results.append(ctx.check('Maintainerr ' + service + ' integration', True,
                                     'Read failed: ' + type(exc).__name__))
    return results
