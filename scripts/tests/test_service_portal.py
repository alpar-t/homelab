import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'config/portal/manifests/assets'
spec = importlib.util.spec_from_file_location('portal', ROOT / 'config/zabbix/manifests/assets/service_portal.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ROOT / 'config/zabbix/manifests/assets/service_portal.json').read_text())

class Context:
    def __init__(self, broken=None):
        self.broken = broken
        self.calls = []
    def remaining(self):
        return 30
    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.broken == 'timeout':
            raise TimeoutError('PRIVATE URL AND DATA')
        if url == CONFIG['public_url']:
            return SimpleNamespace(status=200 if self.broken == 'gate' else 302, headers={'Location': CONFIG['public_url'] + '/oauth2/start?rd=' + ('/' if self.broken == 'relative' else CONFIG['public_url'] + '/')}, body=b'')
        path = url.removeprefix(CONFIG['internal_url'])
        if path == '/catalog/admin.json':
            return SimpleNamespace(status=404, headers={}, body=b'')
        if path == '/catalog.json':
            role = {'advanced_apps':'admin', 'family_users':'family', 'kids':'kids'}[kwargs['headers']['X-Auth-Request-Groups']]
            data = (ASSETS / 'catalog' / (role + '.json')).read_bytes()
            if self.broken == 'catalog':
                data = b'{"sections": []}'
            return SimpleNamespace(status=200, headers={'Content-Type':'application/json'}, body=data)
        filename = 'index.html' if path == '/' else path[1:]
        types = {'html':'text/html', 'js':'application/javascript', 'css':'text/css', 'json':'application/json', 'svg':'image/svg+xml'}
        data = (ASSETS / filename).read_bytes()
        kind = types[filename.rsplit('.', 1)[1]]
        if self.broken == 'asset' and filename == 'app.js':
            data, kind = b'<html>fallback</html>', 'text/html'
        return SimpleNamespace(status=200, headers={'Content-Type':kind}, body=data)

class Tests(unittest.TestCase):
    def test_healthy_shipped_assets(self):
        ctx = Context()
        self.assertEqual([0,0,0], [x['status'] for x in module.run(ctx, CONFIG)])
        self.assertEqual(['Portal frontend assets', 'Portal catalog contract', 'Portal public sign-in gate'], [x['name'] for x in module.run(ctx, CONFIG)])
        self.assertTrue(all(args.get('headers') == {'User-Agent': 'HomePBP-monitor/1'} for url,args in ctx.calls if url == CONFIG['public_url']))
    def test_relative_return_url(self):
        self.assertEqual(0, module.run(Context('relative'), CONFIG)[2]['status'])
    def test_broken_contracts(self):
        for broken, index in [('asset',0), ('catalog',1), ('gate',2)]:
            with self.subTest(broken=broken):
                self.assertEqual(1, module.run(Context(broken), CONFIG)[index]['status'])
    def test_errors_are_safe(self):
        records = module.run(Context('timeout'), CONFIG)
        self.assertEqual([1,1,1], [x['status'] for x in records])
        self.assertNotIn('PRIVATE', str(records))
    def test_unauthorized_and_malformed_catalog(self):
        for status, body in [(401,b'{}'), (200,b'bad'), (200,b'[]')]:
            with self.assertRaises((ValueError, TypeError)):
                module.catalog(SimpleNamespace(status=status, headers={'Content-Type':'application/json'}, body=body))

if __name__ == '__main__':
    unittest.main()
