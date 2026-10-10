import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('vaultwarden', ROOT / 'config/zabbix/manifests/assets/service_vaultwarden.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ROOT / 'config/zabbix/manifests/assets/service_vaultwarden.json').read_text())


class Context:
    def __init__(self, broken=None):
        self.broken = broken or {}
        self.calls = []

    def remaining(self):
        return 12

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bool(bad)), detail=detail)

    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        path = url.removeprefix(CONFIG['base_url'])
        if path in self.broken:
            value = self.broken[path]
            if isinstance(value, Exception):
                raise value
            return value
        bodies = {
            '/api/config': dict(object='config', version='2026.6.0', server={'name': 'Vaultwarden'}, settings={'disableUserRegistration': True}, environment={'vault': CONFIG['public_url'], 'api': CONFIG['public_url'] + '/api', 'identity': CONFIG['public_url'] + '/identity'}),
            '/identity/accounts/prelogin': dict(kdf=0, kdfIterations=600000, kdfMemory=None, kdfParallelism=None, kdfSettings=dict(iterations=600000, kdfType=0, memory=None, parallelism=None)),
            '/': b'<app-root></app-root><script src="https://evil.invalid/a.js"></script><script src="app/polyfills.123.js"></script>',
            '/app/polyfills.123.js': b'const bootstrap = true;' * 20,
        }
        body = bodies[path]
        return SimpleNamespace(status=200, body=json.dumps(body).encode() if isinstance(body, dict) else body, headers={'Content-Type': 'text/javascript'})


class Tests(unittest.TestCase):
    def test_healthy_and_bounded(self):
        ctx = Context()
        self.assertEqual([r['status'] for r in module.run(ctx, CONFIG)], [0, 0, 0])
        self.assertEqual(len(ctx.calls), 4)
        self.assertTrue(all(c[1]['timeout'] <= 5 and c[1]['max_bytes'] <= 1048576 for c in ctx.calls))
        self.assertEqual(ctx.calls[1][1]['method'], 'POST')
        self.assertIn(b'monitor.invalid', ctx.calls[1][1]['data'])
        self.assertTrue(all('evil.invalid' not in c[0] for c in ctx.calls))

    def test_errors_redacted_and_independent(self):
        ctx = Context({'/api/config': TimeoutError('private secret'), '/identity/accounts/prelogin': ValueError('private secret')})
        rows = module.run(ctx, CONFIG)
        self.assertEqual([r['status'] for r in rows], [1, 1, 0])
        self.assertNotIn('private secret', str(rows))

    def test_malformed_unauthorized_and_spa_fallback(self):
        for path in ['/api/config', '/identity/accounts/prelogin', '/app/polyfills.123.js']:
            for response in [SimpleNamespace(status=401, body=b'{}', headers={}), SimpleNamespace(status=200, body=b'<html>login</html>', headers={'Content-Type': 'text/html'})]:
                with self.subTest(path=path, response=response):
                    rows = module.run(Context({path: response}), CONFIG)
                    self.assertEqual(sum(r['status'] for r in rows), 1)

    def test_kdf_mismatch_and_wrong_environment(self):
        for path in ['/api/config', '/identity/accounts/prelogin']:
            response = Context().http(CONFIG['base_url'] + path)
            data = json.loads(response.body)
            if path == '/api/config':
                data['environment']['identity'] = 'https://wrong.invalid/identity'
            else:
                data['kdfSettings']['iterations'] = 1
            response.body = json.dumps(data).encode()
            self.assertEqual(sum(r['status'] for r in module.run(Context({path: response}), CONFIG)), 1)


if __name__ == '__main__':
    unittest.main()
