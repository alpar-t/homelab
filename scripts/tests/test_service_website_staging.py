import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('staging', ASSETS / 'service_website_staging.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ASSETS / 'service_website_staging.json').read_text())


def response(status=200, body=b'', **headers):
    return SimpleNamespace(status=status, body=body, headers=headers)


class Context:
    def __init__(self, changes=None):
        public = CONFIG['public_url']
        self.responses = {
            CONFIG['internal_url']: response(body=b'<html>New Joy Interior Design<div data-staging-bar></div><link rel="stylesheet" href="/_astro/main.css"></html>', **{'Content-Type': 'text/html'}),
            CONFIG['internal_url'] + '_astro/main.css': response(body=b'body{color:black}', **{'Content-Type': 'text/css'}),
            CONFIG['internal_url'] + 'environment.json': response(body=b'{"environment":"staging","showStagingBanner":true}', **{'Content-Type': 'application/json'}),
            public: response(302, Location=public + 'oauth2/start?rd=' + public),
            public + 'oauth2/start?rd=' + public: response(302, Location='https://auth.newjoy.ro/authorize?response_type=code&client_id=test&state=random&scope=openid+profile&redirect_uri=https%3A%2F%2Fstaging.newjoy.ro%2Foauth2%2Fcallback'),
        }
        self.responses.update(changes or {})
    def remaining(self):
        return 30
    def http(self, url, **kwargs):
        assert kwargs['headers']['User-Agent'] == 'HomePBP-monitor/1'
        assert kwargs['timeout'] <= 5
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        return value
    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bool(bad)), detail=detail, severity=severity)


class Tests(unittest.TestCase):
    def test_healthy(self):
        self.assertEqual([r['status'] for r in module.run(Context(), CONFIG)], [0, 0, 0])
    def test_missing_asset_and_spa_fallback(self):
        for value in (response(404), response(body=b'<html>fallback</html>', **{'Content-Type': 'text/html'})):
            ctx = Context({CONFIG['internal_url'] + '_astro/main.css': value})
            self.assertEqual(module.run(ctx, CONFIG)[0]['status'], 1)
    def test_missing_marker_external_asset_and_auth_page(self):
        for body in (b'<html>login</html>', b'New Joy Interior Design data-staging-bar<link rel="stylesheet" href="https://other/_astro/a.css">'):
            ctx = Context({CONFIG['internal_url']: response(body=body, **{'Content-Type': 'text/html'})})
            self.assertEqual(module.run(ctx, CONFIG)[0]['status'], 1)
    def test_environment_wrong_or_malformed(self):
        for body in (b'{}', b'null', b'bad', b'{"environment":"production","showStagingBanner":true}'):
            ctx = Context({CONFIG['internal_url'] + 'environment.json': response(body=body, **{'Content-Type': 'application/json'})})
            self.assertEqual(module.run(ctx, CONFIG)[1]['status'], 1)
    def test_public_bypass_or_wrong_issuer(self):
        for value in (response(), response(302, Location='https://evil.example/oauth2/start')):
            self.assertEqual(module.run(Context({CONFIG['public_url']: value}), CONFIG)[2]['status'], 1)
        key = CONFIG['public_url'] + 'oauth2/start?rd=' + CONFIG['public_url']
        self.assertEqual(module.run(Context({key: response(302, Location='https://evil.example/authorize')}), CONFIG)[2]['status'], 1)
    def test_timeout_is_safe_and_independent(self):
        rows = module.run(Context({CONFIG['internal_url']: TimeoutError('SECRET')}), CONFIG)
        self.assertEqual([r['status'] for r in rows], [1, 0, 0])
        self.assertNotIn('SECRET', str(rows))

if __name__ == '__main__':
    unittest.main()
