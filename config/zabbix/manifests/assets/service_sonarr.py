"""Read-only Sonarr v3 API checks; never publish API response content."""
import json


def _get(ctx, base, path, headers):
    remaining = ctx.remaining()
    if remaining <= 0:
        raise ValueError('deadline')
    response = ctx.http(base + path, headers=headers, timeout=min(5, remaining),
                        max_bytes=262144, follow_redirects=False)
    if response.status != 200:
        raise ValueError('response')
    return json.loads(response.body)


def run(ctx, config):
    base = config['base_url'].rstrip('/')
    names = ['Sonarr API contract', 'Sonarr health and download clients',
             'Sonarr root folders']
    try:
        ping = _get(ctx, base, '/ping', {})
        if not isinstance(ping, dict) or ping.get('status') != 'OK':
            raise ValueError('schema')
    except Exception:
        return [ctx.check(name, True, 'Sonarr application response unavailable or invalid')
                for name in names]
    try:
        key = ctx.secret(config['credential_key'])
    except Exception:
        return [ctx.check(name, True, 'ping valid; authenticated coverage unavailable: credential missing')
                for name in names]
    headers = {'X-Api-Key': key, 'Accept': 'application/json'}
    rows = []
    try:
        system = _get(ctx, base, '/api/v3/system/status', headers)
        if (not isinstance(system, dict) or system.get('appName') != 'Sonarr'
                or not isinstance(system.get('version'), str) or not system['version']):
            raise ValueError('schema')
        rows.append(ctx.check(names[0], False, 'ping and authenticated system contract valid'))
    except Exception:
        return [ctx.check(name, True, 'authenticated system API unavailable or invalid')
                for name in names]
    try:
        health = _get(ctx, base, '/api/v3/health', headers)
        if not isinstance(health, list) or any(
                not isinstance(row, dict) or row.get('type') not in
                ('ok', 'notice', 'warning', 'error') for row in health):
            raise ValueError('schema')
        warnings = sum(row['type'] == 'warning' for row in health)
        errors = sum(row['type'] == 'error' for row in health)
        rows.append(ctx.check(names[1], warnings + errors > 0,
                              f'cached native health: warnings={warnings}; errors={errors}'))
    except Exception:
        rows.append(ctx.check(names[1], True, 'health API unavailable or invalid'))
    try:
        roots = _get(ctx, base, '/api/v3/rootfolder', headers)
        if not isinstance(roots, list) or any(
                not isinstance(row, dict) or type(row.get('accessible')) is not bool
                for row in roots):
            raise ValueError('schema')
        inaccessible = sum(not row['accessible'] for row in roots)
        rows.append(ctx.check(names[2], inaccessible > 0,
                              f'configured roots={len(roots)}; inaccessible={inaccessible}'))
    except Exception:
        rows.append(ctx.check(names[2], True, 'root-folder API unavailable or invalid'))
    return rows
