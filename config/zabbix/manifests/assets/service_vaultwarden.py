"""Anonymous client bootstrap and database-backed prelogin, never vault access."""
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            src = dict(attrs).get('src', '')
            if src:
                self.sources.append(src)


def run(ctx, config):
    base = config['base_url'].rstrip('/')
    public = config['public_url'].rstrip('/')

    def request(path, **kwargs):
        remaining = ctx.remaining()
        if remaining <= 0:
            raise ValueError('deadline')
        return ctx.http(base + path, timeout=min(5, remaining), **kwargs)

    def document(path, **kwargs):
        response = request(path, max_bytes=32768, **kwargs)
        if response.status != 200:
            raise ValueError('status')
        data = json.loads(response.body)
        if not isinstance(data, dict):
            raise ValueError('schema')
        return data

    rows = []
    try:
        data = document('/api/config')
        env = data.get('environment', {})
        good = (data.get('object') == 'config'
                and isinstance(data.get('version'), str)
                and re.fullmatch(r'\d+\.\d+\.\d+(?:[-+].*)?', data['version'])
                and data.get('server', {}).get('name') == 'Vaultwarden'
                and all(env.get(key) == public + suffix for key, suffix in
                        [('vault', ''), ('api', '/api'), ('identity', '/identity')])
                and data.get('settings', {}).get('disableUserRegistration') is True)
        rows.append(ctx.check('Vaultwarden client configuration', not good,
                              'client configuration valid' if good else 'client configuration contract invalid'))
    except Exception:
        rows.append(ctx.check('Vaultwarden client configuration', True, 'client configuration unavailable'))

    try:
        # Reserved invalid domain: no personal username, token request or login.
        data = document('/identity/accounts/prelogin', method='POST',
                        headers={'Content-Type': 'application/json'},
                        data=b'{"email":"functional-monitor@monitor.invalid"}')
        good = (type(data.get('kdf')) is int and data['kdf'] == 0
                and type(data.get('kdfIterations')) is int and data['kdfIterations'] > 0
                and data.get('kdfMemory') is None and data.get('kdfParallelism') is None)
        # New clients use nested settings; keep the legacy and new contracts coherent.
        settings = data.get('kdfSettings')
        good = good and isinstance(settings, dict) and all(
            settings.get(key) == data.get(old) for key, old in
            [('iterations', 'kdfIterations'), ('kdfType', 'kdf'),
             ('memory', 'kdfMemory'), ('parallelism', 'kdfParallelism')])
        rows.append(ctx.check('Vaultwarden database prelogin', not good,
                              'database-backed prelogin contract valid' if good else 'prelogin KDF contract invalid'))
    except Exception:
        rows.append(ctx.check('Vaultwarden database prelogin', True, 'database-backed prelogin unavailable'))

    try:
        home = request('/', max_bytes=262144)
        parser = Scripts()
        parser.feed(home.body.decode('utf-8'))
        candidates = []
        for src in parser.sources:
            target = urlsplit(urljoin(base + '/', src))
            if (target.scheme, target.netloc) == (urlsplit(base).scheme, urlsplit(base).netloc) and target.path.endswith('.js') and not target.query and not target.fragment:
                candidates.append(target.path)
        if home.status != 200 or b'<app-root' not in home.body or not candidates:
            raise ValueError('homepage')
        # Probe a small bootstrap bundle; main/vendor can exceed the response bound.
        path = next((p for p in candidates if '/polyfills.' in p or p.endswith('/polyfills.js')), candidates[-1])
        asset = request(path, max_bytes=1048576)
        content_type = next((v for k, v in asset.headers.items() if k.lower() == 'content-type'), '')
        good = (asset.status == 200 and 'javascript' in content_type.lower()
                and len(asset.body) > 100 and not asset.body.lstrip().startswith(b'<'))
        rows.append(ctx.check('Vaultwarden web vault bundle', not good,
                              'web vault entrypoint and bundle valid' if good else 'web vault bundle contract invalid'))
    except Exception:
        rows.append(ctx.check('Vaultwarden web vault bundle', True, 'web vault entrypoint or bundle unavailable'))
    return rows
