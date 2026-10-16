"""Read-only Tandoor configuration and database-backed recipe pagination."""
import json
import re


def fetch(ctx, url, headers=None):
    response = ctx.http(url, headers=headers, timeout=min(5, ctx.remaining()),
                        max_bytes=131072, follow_redirects=False)
    if response.status != 200:
        raise ValueError('unexpected HTTP status')
    return json.loads(response.body)


def run(ctx, config):
    base = config['base_url'].rstrip('/')
    rows = []
    try:
        settings = fetch(ctx, base + '/api/server-settings/current/')
        valid = (isinstance(settings, dict)
                 and isinstance(settings.get('version'), str)
                 and re.fullmatch(r'\d+\.\d+\.\d+(?:[+.-][A-Za-z0-9.-]+)?', settings['version'])
                 and type(settings.get('debug')) is bool
                 and type(settings.get('disable_external_connectors')) is bool)
        rows.append(ctx.check('Tandoor API configuration', not valid,
                              'configuration schema valid' if valid else 'configuration schema invalid'))
    except Exception:
        rows.append(ctx.check('Tandoor API configuration', True, 'configuration request unavailable'))
    try:
        token = ctx.secret(config['token_key'])
    except Exception:
        rows.append(dict(ctx.check('Tandoor recipe backend', True, 'coverage deferred: dedicated read-only credential unavailable', 1), observation='deferred', notification='dashboard'))
        return rows
    try:
        page = fetch(ctx, base + '/api/recipe/?page_size=1',
                     {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
        valid = (isinstance(page, dict) and type(page.get('count')) is int
                 and page['count'] >= 0 and isinstance(page.get('results'), list)
                 and len(page['results']) == min(page['count'], 1)
                 and all(isinstance(item, dict) and type(item.get('id')) is int
                         and item['id'] > 0 and isinstance(item.get('name'), str)
                         for item in page['results'])
                 and 'next' in page and 'previous' in page
                 and page['previous'] is None
                 and (page['next'] is None if page['count'] <= 1 else isinstance(page['next'], str)))
        rows.append(ctx.check('Tandoor recipe backend', not valid,
                              'authenticated recipe pagination valid (empty library allowed)'
                              if valid else 'recipe pagination schema invalid'))
    except Exception:
        rows.append(ctx.check('Tandoor recipe backend', True, 'authenticated recipe query unavailable'))
    return rows
