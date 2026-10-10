import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('landing', ROOT / 'config/zabbix/manifests/assets/service_landing_page.py')
landing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(landing)
HTML = b'<html><head><title>newjoy.ro</title><style>body {color:red}</style></head><body><h1>newjoy.ro</h1></body></html>'

class Context:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def remaining(self): return 30
    def check(self, name, bad, detail): return dict(name=name, status=int(bad), detail=detail)
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception): raise response
        return response

def response(body=HTML, mime='text/html', status=200):
    return SimpleNamespace(status=status, headers={'Content-Type': mime}, body=body)

class LandingTests(unittest.TestCase):
    def run_check(self, responses):
        ctx = Context(responses)
        result = landing.run(ctx, {'endpoints': [{'name': 'internal', 'url': 'http://site/'}]})[0]
        return result, ctx
    def test_inline_homepage(self):
        row, ctx = self.run_check([response()])
        self.assertEqual(row['status'], 0)
        self.assertEqual(len(ctx.calls), 1)
        self.assertEqual(ctx.calls[0][1]['headers']['User-Agent'], 'HomePBP-monitor/1')
    def test_wrong_site_status_mime_and_timeout(self):
        for res in [response(b'<html>nginx</html>'), response(status=401), response(mime='text/plain'), TimeoutError('private detail')]:
            row, _ = self.run_check([res])
            self.assertEqual(row['status'], 1)
            self.assertNotIn('private detail', row['detail'])
    def test_asset_success_and_fallback(self):
        page = HTML.replace(b'<style>', b'<link rel="stylesheet" href="/app.css"><style>')
        for asset, status in [(response(b'body{}', 'text/css'), 0), (response(HTML), 1), (response(b'', 'text/css'), 1), (response(b'missing', 'text/css', 404), 1)]:
            row, ctx = self.run_check([response(page), asset])
            self.assertEqual(row['status'], status)
            self.assertEqual(ctx.calls[1][0], 'http://site/app.css')
    def test_third_party_never_fetched(self):
        page = HTML.replace(b'<style>', b'<link rel="stylesheet" href="https://external/app.css"><style>')
        row, ctx = self.run_check([response(page)])
        self.assertEqual(row['status'], 0)
        self.assertEqual(len(ctx.calls), 1)
    def test_no_styling_and_invalid_utf8(self):
        for body in [HTML.replace(b'<style>body {color:red}</style>', b''), b'\xff']:
            row, _ = self.run_check([response(body)])
            self.assertEqual(row['status'], 1)

if __name__ == '__main__': unittest.main()
