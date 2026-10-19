"""Anonymous Sonarr contract; authenticated admin-key coverage is deferred."""
import json


def run(ctx, config):
    try:
        response = ctx.http(config['base_url'].rstrip('/') + '/ping',
                            timeout=min(5, ctx.remaining()), max_bytes=4096, follow_redirects=False)
        value = json.loads(response.body)
        good = response.status == 200 and isinstance(value, dict) and value.get('status') == 'OK'
        detail = 'anonymous ping contract valid; authenticated health unproven' if good else 'anonymous ping contract failed'
    except Exception:
        good, detail = False, 'anonymous ping unavailable or malformed'
    rows = [ctx.check('Sonarr API contract', not good, detail)]
    for name in ('Sonarr health and download clients', 'Sonarr root folders'):
        rows.append(dict(ctx.check(name, True,
            'coverage deferred: native application API key permits administrative writes; no key is mounted', severity=1), observation='deferred', notification='dashboard'))
    return rows
