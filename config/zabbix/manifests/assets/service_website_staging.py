"""Read-only staging content and signed-out access contract."""
import json
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, parse_qs


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and 'stylesheet' in attrs.get('rel', '').split():
            self.paths.append(attrs.get('href', ''))


def header(response, name):
    return next((v for k, v in response.headers.items() if k.lower() == name.lower()), '')


def run(ctx, config):
    base, public = config['internal_url'], config['public_url']
    def get(url):
        return ctx.http(url, headers={'User-Agent': 'HomePBP-monitor/1'},
                        timeout=min(5, ctx.remaining()), max_bytes=262144)
    results = []
    try:
        page = get(base)
        text = page.body.decode('utf-8')
        parser = Assets()
        parser.feed(text)
        candidates = [p for p in parser.paths if p.startswith('/_astro/')
                      and not urlsplit(p).netloc and urlsplit(p).path.endswith('.css')]
        valid = (page.status == 200 and 'text/html' in header(page, 'Content-Type')
                 and config['marker'] in text and 'data-staging-bar' in text and candidates)
        if valid:
            asset = get(urljoin(base, candidates[0]))
            valid = (asset.status == 200 and 'text/css' in header(asset, 'Content-Type')
                     and bool(asset.body.strip()) and b'<' not in asset.body[:100])
        results.append(ctx.check('Staging homepage and asset', not valid,
                                 'homepage and declared CSS usable' if valid else 'homepage or declared CSS contract failed'))
    except Exception:
        results.append(ctx.check('Staging homepage and asset', True, 'content request unavailable'))
    try:
        env = get(urljoin(base, '/environment.json'))
        data = json.loads(env.body)
        valid = (env.status == 200 and 'application/json' in header(env, 'Content-Type')
                 and isinstance(data, dict) and data.get('environment') == 'staging'
                 and data.get('showStagingBanner') is True)
        results.append(ctx.check('Staging environment', not valid,
                                 'staging metadata usable' if valid else 'staging metadata contract failed'))
    except Exception:
        results.append(ctx.check('Staging environment', True, 'staging metadata unavailable'))
    try:
        root = get(public)
        location = urlsplit(urljoin(public, header(root, 'Location')))
        expected = urlsplit(public)
        valid = (root.status in (302, 303, 307) and location.scheme == 'https'
                 and location.netloc == expected.netloc and location.path == '/oauth2/start'
                 and parse_qs(location.query).get('rd') == [public])
        if valid:
            start = get(urljoin(public, header(root, 'Location')))
            auth = urlsplit(header(start, 'Location'))
            params = parse_qs(auth.query)
            valid = (start.status in (302, 303, 307)
                     and auth.scheme == 'https' and auth.netloc == config['issuer_host']
                     and auth.path == '/authorize' and params.get('response_type') == ['code']
                     and params.get('redirect_uri') == [public.rstrip('/') + '/oauth2/callback']
                     and bool(params.get('client_id', [''])[0]) and bool(params.get('state', [''])[0])
                     and 'openid' in params.get('scope', [''])[0].split())
        results.append(ctx.check('Staging public sign-in gate', not valid,
                                 'signed-out gate reaches expected OIDC authorization' if valid else 'signed-out gate contract failed'))
    except Exception:
        results.append(ctx.check('Staging public sign-in gate', True, 'signed-out gate unavailable'))
    return results
