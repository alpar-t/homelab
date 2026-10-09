"""Semantic public/static homepage and bounded same-origin asset checks."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = set()
        self.capture = None
        self.identity = []
        self.inline_style = False
        self.assets = []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        attrs = dict(attrs)
        if tag in ('title', 'h1', 'style'):
            self.capture = tag
        if tag == 'script' and attrs.get('src'):
            self.assets.append((attrs['src'], 'js'))
        if tag == 'link' and 'stylesheet' in attrs.get('rel', '').lower().split() and attrs.get('href'):
            self.assets.append((attrs['href'], 'css'))

    def handle_endtag(self, tag):
        if self.capture == tag:
            self.capture = None

    def handle_data(self, data):
        if self.capture in ('title', 'h1'):
            self.identity.append(data)
        if self.capture == 'style' and '{' in data and '}' in data:
            self.inline_style = True


def content_type(response):
    return next((v.lower().split(';')[0].strip() for k, v in response.headers.items()
                 if k.lower() == 'content-type'), '')


def verify(ctx, endpoint):
    url = endpoint['url']
    response = ctx.http(url, headers={'User-Agent': 'HomePBP-monitor/1'}, timeout=min(5, ctx.remaining()), max_bytes=262144)
    if response.status != 200 or content_type(response) != 'text/html':
        return 'homepage HTTP status or content type invalid'
    page = Page()
    page.feed(response.body.decode('utf-8', errors='strict'))
    if not {'html', 'head', 'body', 'title', 'h1'} <= page.tags or 'newjoy.ro' not in ''.join(page.identity).lower():
        return 'homepage structure or site identity missing'
    origin = urlsplit(url)
    assets = []
    for reference, kind in page.assets:
        target = urlsplit(urljoin(url, reference))
        if (target.scheme, target.netloc) == (origin.scheme, origin.netloc) and not target.username and not target.password:
            assets.append((target.geturl(), kind))
    if not assets:
        return None if page.inline_style else 'homepage has no usable inline or first-party styling'
    target, kind = assets[0]
    response = ctx.http(target, headers={'User-Agent': 'HomePBP-monitor/1'}, timeout=min(5, ctx.remaining()), max_bytes=524288)
    types = {'css': {'text/css'}, 'js': {'application/javascript', 'text/javascript', 'application/x-javascript'}}
    body = response.body.strip()
    if response.status != 200 or content_type(response) not in types[kind] or not body or body.lower().startswith((b'<!doctype html', b'<html')):
        return 'declared first-party asset unavailable or SPA fallback returned'
    return None


def run(ctx, config):
    records = []
    for endpoint in config['endpoints']:
        try:
            problem = verify(ctx, endpoint)
        except Exception:
            problem = 'homepage or asset request/parse unavailable'
        records.append(ctx.check('Newjoy website ' + endpoint['name'], bool(problem),
                                 problem or 'homepage identity, structure and styling available'))
    return records
