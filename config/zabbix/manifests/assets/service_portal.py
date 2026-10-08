"""Check shipped portal contracts without credentials or user data output."""
import json
from urllib.parse import urlsplit, parse_qs


def get(ctx, url, headers=None):
    return ctx.http(url, headers=headers, timeout=min(3, ctx.remaining()), max_bytes=262144)


def content(response, kinds):
    value = next((v for k, v in response.headers.items() if k.lower() == 'content-type'), '')
    return response.status == 200 and any(kind in value.lower() for kind in kinds) and bool(response.body.strip())


def catalog(response):
    if not content(response, ['application/json']):
        raise ValueError()
    data = json.loads(response.body)
    if not isinstance(data, dict) or not isinstance(data.get('label'), str) or not isinstance(data.get('sections'), list) or not data['sections']:
        raise ValueError()
    products, icons = set(), set()
    for section in data['sections']:
        if not isinstance(section, dict) or not isinstance(section.get('id'), str) or not isinstance(section.get('services'), list):
            raise ValueError()
        for item in section['services']:
            if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k] for k in ('name', 'product', 'description', 'url', 'icon')):
                raise ValueError()
            url = urlsplit(item['url'])
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or item.get('network') not in ('home', 'anywhere'):
                raise ValueError()
            products.add(item['product'])
            icons.add(item['icon'])
    if not products:
        raise ValueError()
    return products, icons


def run(ctx, config):
    base = config['internal_url'].rstrip('/')
    checks = []
    try:
        shell = get(ctx, base + '/')
        if not content(shell, ['text/html']) or b'<title>Newjoy Portal</title>' not in shell.body:
            raise ValueError()
        for path, types in [('theme.js', ['javascript']), ('app.js', ['javascript']), ('styles.css', ['text/css'])]:
            if ('/' + path).encode() not in shell.body or not content(get(ctx, base + '/' + path), types):
                raise ValueError()
        checks.append(ctx.check('Portal frontend assets', False, 'Portal shell and required scripts/styles are served'))
    except Exception:
        checks.append(ctx.check('Portal frontend assets', True, 'Portal shell or required asset contract unavailable'))
    try:
        policy_response = get(ctx, base + '/capability-policy.json')
        if not content(policy_response, ['application/json']):
            raise ValueError()
        policy = json.loads(policy_response.body)
        icons_response = get(ctx, base + '/icons.svg')
        if not content(icons_response, ['image/svg+xml']) or b'<svg' not in icons_response.body:
            raise ValueError()
        for role, group in [('admin', 'advanced_apps'), ('family', 'family_users'), ('kids', 'kids')]:
            products, icons = catalog(get(ctx, base + '/catalog.json', {'X-Auth-Request-Groups': group}))
            if any(product not in policy or policy[product].get('maturity') not in ('stable', 'experimental') or not isinstance(policy[product].get('baloo', {}).get('available'), bool) for product in products):
                raise ValueError()
            if any(('id="' + icon + '"').encode() not in icons_response.body for icon in icons):
                raise ValueError()
        if get(ctx, base + '/catalog/admin.json').status != 404:
            raise ValueError()
        checks.append(ctx.check('Portal catalog contract', False, 'Role catalogs, capability policy and referenced icons are valid'))
    except Exception:
        checks.append(ctx.check('Portal catalog contract', True, 'Role catalog/schema/asset or internal-file protection contract failed'))
    try:
        response = get(ctx, config['public_url'], {'User-Agent': 'HomePBP-monitor/1'})
        location = next((v for k, v in response.headers.items() if k.lower() == 'location'), '')
        target = urlsplit(location)
        portal = urlsplit(config['public_url'])
        allowed = (target.scheme in ('', 'https') and target.hostname in (None, portal.hostname) and target.path == '/oauth2/start' and parse_qs(target.query).get('rd') in (['/'], [config['public_url'].rstrip('/') + '/']))
        if response.status not in (302, 303, 307, 308) or not allowed:
            raise ValueError()
        checks.append(ctx.check('Portal public sign-in gate', False, 'Anonymous entry redirects to portal sign-in'))
    except Exception:
        checks.append(ctx.check('Portal public sign-in gate', True, 'Anonymous portal sign-in redirect contract failed'))
    return checks
