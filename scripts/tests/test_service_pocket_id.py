import base64
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('service_pocket_id', ASSETS / 'service_pocket_id.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ASSETS / 'service_pocket_id.json').read_text())


class Context:
    def __init__(self):
        metadata = dict(CONFIG['endpoints'], issuer=CONFIG['issuer'], response_types_supported=['code'],
                        scopes_supported=['openid'], id_token_signing_alg_values_supported=['RS256'])
        modulus = base64.urlsafe_b64encode((1 << 2047).to_bytes(256, 'big')).decode().rstrip('=')
        self.responses = [SimpleNamespace(status=200, headers={}, body=json.dumps(metadata).encode()),
                          SimpleNamespace(status=200, headers={}, body=json.dumps({'keys': [dict(kty='RSA', kid='test', n=modulus, e='AQAB', alg='RS256')]}).encode())]
        for proxy in CONFIG['proxies']:
            query = urlencode(dict(client_id=proxy['client_id'], redirect_uri=proxy['callback'], response_type='code', scope='openid groups', state='x'*32))
            self.responses.append(SimpleNamespace(status=302, body=b'', headers={'Location': CONFIG['endpoints']['authorization_endpoint'] + '?' + query, 'Set-Cookie': '_test_csrf=value; Secure; HttpOnly'}))
        self.calls = []

    def remaining(self):
        return 25

    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail)


class Tests(unittest.TestCase):
    def test_healthy_and_bounded(self):
        ctx = Context()
        self.assertEqual([r['status'] for r in module.run(ctx, CONFIG)], [0, 0, 0])
        self.assertTrue(all(c[1]['timeout'] <= 5 and c[1]['max_bytes'] == 65536 for c in ctx.calls))

    def test_metadata_invalid_or_unauthorized(self):
        for body, status in [(b'{}', 200), (b'not-json', 200), (b'{}', 401)]:
            ctx = Context()
            ctx.responses[0] = SimpleNamespace(status=status, headers={}, body=body)
            ctx.responses.pop(1)
            self.assertEqual([r['status'] for r in module.run(ctx, CONFIG)], [1, 0, 0])

    def test_wrong_issuer(self):
        ctx = Context()
        data = json.loads(ctx.responses[0].body)
        data['issuer'] = 'https://wrong.example'
        ctx.responses[0].body = json.dumps(data).encode()
        ctx.responses.pop(1)
        self.assertEqual(module.run(ctx, CONFIG)[0]['status'], 1)

    def test_bad_signing_keys(self):
        for keys in [[], [dict(kty='oct', kid='test', k='sensitive')], [dict(kty='RSA', kid='test', n='bad!', e='AQAB')]]:
            ctx = Context()
            ctx.responses[1].body = json.dumps({'keys': keys}).encode()
            self.assertEqual(module.run(ctx, CONFIG)[0]['status'], 1)

    def test_redirect_contract_failures(self):
        for replacement in [dict(status=200), dict(headers={'Location': 'https://evil.example/authorize'}),
                            dict(headers={'Location': CONFIG['endpoints']['authorization_endpoint']+'?client_id=wrong'}), dict(headers={})]:
            ctx = Context()
            for key, value in replacement.items():
                setattr(ctx.responses[2], key, value)
            self.assertEqual([r['status'] for r in module.run(ctx, CONFIG)], [0, 1, 0])

    def test_timeout_is_safe_and_other_proxy_continues(self):
        ctx = Context()
        ctx.responses[2] = TimeoutError('private-response-secret')
        rows = module.run(ctx, CONFIG)
        self.assertEqual([r['status'] for r in rows], [0, 1, 0])
        self.assertNotIn('private-response-secret', str(rows))


if __name__ == '__main__':
    unittest.main()
