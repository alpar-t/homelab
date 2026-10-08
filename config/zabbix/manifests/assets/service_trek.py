"""Read-only TREK SQLite-backed sign-in bootstrap and shipped frontend checks."""
import json
import re
from html.parser import HTMLParser


class Entry(HTMLParser):
    def __init__(self):
        super().__init__()
        self.modules = []
        self.root = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div' and attrs.get('id') == 'root':
            self.root = True
        if tag == 'script' and attrs.get('type') == 'module':
            self.modules.append(attrs.get('src', ''))


def run(ctx, config):
    base = config['base_url'].rstrip('/')

    def get(path, limit=65536):
        response = ctx.http(base + path, timeout=min(5, ctx.remaining()), max_bytes=limit)
        if response.status != 200:
            raise ValueError('unexpected status')
        return response

    results = []
    try:
        response = get('/api/auth/app-config')
        data = json.loads(response.body)
        fields = ('setup_complete', 'has_users', 'oidc_configured', 'oidc_login',
                  'password_login', 'passkey_login', 'passkey_configured')
        valid = (isinstance(data, dict)
                 and all(type(data.get(key)) is bool for key in fields)
                 and isinstance(data.get('version'), str)
                 and bool(re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?', data['version'])))
        usable = valid and data['has_users'] and (
            data['password_login'] or (data['oidc_login'] and data['oidc_configured'])
            or (data['passkey_login'] and data['passkey_configured']))
        results.append(ctx.check('TREK database and sign-in bootstrap', not usable,
                                 'SQLite-backed bootstrap and sign-in configuration valid' if usable
                                 else 'Bootstrap schema, users or available sign-in method invalid'))
    except Exception:
        results.append(ctx.check('TREK database and sign-in bootstrap', True,
                                 'Bootstrap request unavailable or malformed'))
    try:
        entry = Entry()
        entry.feed(get('/').body.decode('utf-8'))
        if not entry.root or len(entry.modules) != 1:
            raise ValueError('invalid entry')
        path = entry.modules[0]
        # Refuse arbitrary URLs, query credentials and path traversal from HTML.
        if not re.fullmatch(r'/assets/[A-Za-z0-9_-]+\.js', path):
            raise ValueError('invalid asset')
        asset = ctx.http(base + path, headers={'Range': 'bytes=0-4095'},
                         timeout=min(5, ctx.remaining()), max_bytes=4096)
        content_type = next((v for k, v in asset.headers.items() if k.lower() == 'content-type'), '')
        content_range = next((v for k, v in asset.headers.items() if k.lower() == 'content-range'), '')
        if (asset.status != 206 or not re.fullmatch(r'bytes 0-4095/\d+', content_range)
                or 'javascript' not in content_type.lower() or len(asset.body) != 4096
                or asset.body.lstrip().startswith(b'<')):
            raise ValueError('invalid JavaScript')
        results.append(ctx.check('TREK frontend bundle', False, 'React entrypoint and referenced JavaScript available'))
    except Exception:
        results.append(ctx.check('TREK frontend bundle', True, 'Frontend entrypoint or JavaScript unavailable or malformed'))
    return results
