"""Exercise a public backend through the private ingress controller service."""
from html.parser import HTMLParser


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = []
        self.html = False

    def handle_starttag(self, tag, attrs):
        if tag == 'html':
            self.html = True
        if tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)


def run(ctx, config):
    name = 'Ingress nginx public backend routing'
    try:
        remaining = ctx.remaining()
        if remaining <= 0:
            raise TimeoutError()
        response = ctx.http(config['url'], headers={'Host': config['host']},
                            timeout=min(5, remaining), max_bytes=65536,
                            follow_redirects=False)
        if response.status != 200:
            return [ctx.check(name, True, f'backend route HTTP {response.status}')]
        headers = {key.lower(): value for key, value in response.headers.items()}
        if headers.get('content-type', '').split(';')[0].strip().lower() != 'text/html':
            return [ctx.check(name, True, 'backend route content type mismatch')]
        page = Page()
        page.feed(response.body.decode('utf-8', errors='strict'))
        title = ''.join(page.title).strip().casefold()
        if not page.html or config['title_marker'].casefold() not in title:
            return [ctx.check(name, True, 'backend route HTML identity mismatch')]
        return [ctx.check(name, False, 'internal Host route serves expected public backend HTML')]
    except Exception:
        return [ctx.check(name, True, 'backend route unavailable or malformed')]
