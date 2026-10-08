import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('ingress_check', ASSETS / 'service_ingress_nginx.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ASSETS / 'service_ingress_nginx.json').read_text())


class Context:
    def __init__(self, status=200, body=b'<html><title>newjoy.ro - Under Construction</title></html>', content_type='text/html', error=False, remaining=30):
        self.response = SimpleNamespace(status=status, body=body, headers={'Content-Type': content_type})
        self.error, self.time, self.calls = error, remaining, []

    def remaining(self):
        return self.time

    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise TimeoutError('sensitive upstream details')
        return self.response

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)


class RoutingTests(unittest.TestCase):
    def test_healthy_bounded_host_request(self):
        ctx = Context(content_type='text/html; charset=utf-8', remaining=2)
        self.assertEqual(module.run(ctx, CONFIG)[0]['status'], 0)
        kwargs = ctx.calls[0][1]
        self.assertEqual(kwargs['headers'], {'Host': 'newjoy.ro'})
        self.assertEqual(kwargs['timeout'], 2)
        self.assertEqual(kwargs['max_bytes'], 65536)
        self.assertFalse(kwargs['follow_redirects'])

    def test_redirect_auth_and_backend_errors_fail(self):
        for status in [301, 302, 401, 403, 404, 502, 503]:
            with self.subTest(status=status):
                self.assertEqual(module.run(Context(status=status), CONFIG)[0]['status'], 1)

    def test_wrong_backend_and_malformed_body_fail(self):
        for body in [b'<html><title>Login</title>newjoy.ro</html>', b'newjoy.ro', b'<html><title>nginx</title></html>', b'\xff']:
            with self.subTest(body=body):
                self.assertEqual(module.run(Context(body=body), CONFIG)[0]['status'], 1)
        self.assertEqual(module.run(Context(content_type='application/json'), CONFIG)[0]['status'], 1)

    def test_timeout_redacts_details(self):
        row = module.run(Context(error=True), CONFIG)[0]
        self.assertEqual(row['status'], 1)
        self.assertNotIn('sensitive', row['detail'])

    def test_expired_deadline_never_requests(self):
        ctx = Context(remaining=0)
        self.assertEqual(module.run(ctx, CONFIG)[0]['status'], 1)
        self.assertEqual(ctx.calls, [])
