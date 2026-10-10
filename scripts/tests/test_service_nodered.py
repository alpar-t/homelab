import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('nodered', ROOT / 'config/zabbix/manifests/assets/service_nodered.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Context:
    def __init__(self, body=b'{"state":"start"}', status=200, error=None, remaining=10):
        self.response = SimpleNamespace(body=body, status=status)
        self.error, self.time, self.calls = error, remaining, []

    def remaining(self):
        return self.time

    def secret(self, key):
        if key != 'nodered-runtime-token':
            raise ValueError('private credential')
        return 'private-token'

    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)


class RuntimeTest(unittest.TestCase):
    config = {'url': 'http://nodered:1880/flows/state'}

    def test_running_and_request_bounds(self):
        ctx = Context(remaining=2)
        self.assertEqual(module.run(ctx, self.config)[0]['status'], 0)
        url, args = ctx.calls[0]
        self.assertTrue(url.endswith('/flows/state'))
        self.assertEqual(args['timeout'], 2)
        self.assertEqual(args['max_bytes'], 4096)
        self.assertFalse(args['follow_redirects'])
        self.assertNotIn('data', args)

    def test_stopped_safe_and_malformed(self):
        for body in (b'{"state":"stop"}', b'{"state":"safe"}', b'{"state":"started"}',
                     b'[]', b'null', b'{}', b'<html>login</html>', b'{"state":[]}'):
            with self.subTest(body=body):
                self.assertEqual(module.run(Context(body), self.config)[0]['status'], 1)

    def test_errors_do_not_leak(self):
        for ctx in (Context(status=401), Context(status=403), Context(status=302),
                    Context(status=503), Context(error=TimeoutError('private-token')),
                    Context(b'{"state":"private-token"}')):
            result = module.run(ctx, self.config)[0]
            self.assertEqual(result['status'], 1)
            self.assertNotIn('private-token', result['detail'])

    def test_credentials_are_not_read_or_sent(self):
        ctx = Context()
        def unexpected_secret(key):
            raise AssertionError('must not access credentials')
        ctx.secret = unexpected_secret
        rows = module.run(ctx, dict(self.config, token_key='nodered-runtime-token'))
        self.assertEqual(rows[0]['observation'], 'deferred')
        self.assertEqual(rows[0]['notification'], 'dashboard')
        self.assertFalse(ctx.calls)

    def test_exhausted_deadline_avoids_request(self):
        ctx = Context(remaining=0)
        self.assertEqual(module.run(ctx, self.config)[0]['status'], 1)
        self.assertEqual(ctx.calls, [])


if __name__ == '__main__':
    unittest.main()
