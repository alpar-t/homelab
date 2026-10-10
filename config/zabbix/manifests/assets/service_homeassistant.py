"""Anonymous HA frontend and API-authentication contracts; never carry actuator tokens."""
from html.parser import HTMLParser


class Shell(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = False
        self.title_text = []
        self.app = False
    def handle_starttag(self, tag, attrs):
        self.title = tag == 'title' or self.title
        self.app |= tag == 'home-assistant'
    def handle_endtag(self, tag):
        if tag == 'title':
            self.title = False
    def handle_data(self, value):
        if self.title:
            self.title_text.append(value)


def run(ctx, config):
    rows = []
    base = config['base_url'].rstrip('/')
    try:
        response = ctx.http(base + '/', timeout=min(5, ctx.remaining()), max_bytes=65536)
        content_type = next((v for k, v in response.headers.items() if k.lower() == 'content-type'), '')
        shell = Shell()
        shell.feed(response.body.decode('utf-8'))
        good = (response.status == 200 and 'text/html' in content_type.lower()
                and shell.app and 'home assistant' in ''.join(shell.title_text).casefold())
        rows.append(ctx.check('Home Assistant anonymous frontend', not good,
            'Home Assistant frontend shell served; application internals not authenticated'
            if good else 'frontend shell unavailable or invalid'))
    except Exception:
        rows.append(ctx.check('Home Assistant anonymous frontend', True, 'frontend request unavailable or invalid'))
    try:
        response = ctx.http(base + '/api/', timeout=min(5, ctx.remaining()), max_bytes=4096)
        good = response.status == 401
        rows.append(ctx.check('Home Assistant API authentication guard', not good,
            'API rejects anonymous access; authenticated API functionality unproven'
            if good else 'API anonymous-rejection contract failed'))
    except Exception:
        rows.append(ctx.check('Home Assistant API authentication guard', True, 'API authentication guard unavailable'))
    for name in ('Home Assistant authenticated configuration', 'Home Assistant energy entities'):
        rows.append(dict(ctx.check(name, True,
            'coverage deferred: HA native tokens permit actuator control; no appliance credential is mounted', severity=1), observation='deferred', notification='dashboard'))
    return rows
