import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

PATH = Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets/service_trek.py'
spec = importlib.util.spec_from_file_location('trek', PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Context:
    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self.paths = []

    def remaining(self):
        return 20

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)

    def http(self, url, **kwargs):
        path = url.removeprefix('http://trek')
        self.paths.append(path)
        self.assertions(kwargs)
        data = dict(version='3.4.1', setup_complete=False, has_users=True,
                    oidc_configured=True, oidc_login=True, password_login=False,
                    passkey_login=False, passkey_configured=True)
        defaults = {
            '/api/auth/app-config': (200, {}, json.dumps(data).encode()),
            '/': (200, {}, b'<div id="root"></div><script type="module" src="/assets/index-123.js"></script>'),
            '/assets/index-123.js': (206, {'Content-Type': 'application/javascript', 'Content-Range': 'bytes 0-4095/7000000'}, b'var a=1;' + b' ' * 4088),
        }
        value = self.overrides.get(path, defaults.get(path))
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(status=value[0], headers=value[1], body=value[2])

    def assertions(self, kwargs):
        assert 0 < kwargs['timeout'] <= 5
        assert kwargs['max_bytes'] <= 65536


class Tests(unittest.TestCase):
    def run_check(self, overrides=None):
        ctx = Context(overrides)
        return module.run(ctx, {'base_url': 'http://trek'}), ctx

    def test_healthy_oidc_with_bootstrap_admin_password_pending(self):
        rows, _ = self.run_check()
        self.assertEqual([r['status'] for r in rows], [0, 0])

    def test_unauthorized_malformed_and_timeout(self):
        for response in [(401, {}, b'private'), (200, {}, b'{}'),
                         (200, {}, b'<html>private</html>'), TimeoutError('private')]:
            rows, _ = self.run_check({'/api/auth/app-config': response})
            self.assertEqual(rows[0]['status'], 1)
            self.assertNotIn('private', str(rows))

    def test_no_signin_and_schema_types(self):
        for field, value in [('oidc_configured', False), ('has_users', False), ('version', 42)]:
            data = dict(version='3.4.1', setup_complete=True, has_users=True, oidc_configured=True,
                        oidc_login=True, password_login=False, passkey_login=False, passkey_configured=True)
            data[field] = value
            rows, _ = self.run_check({'/api/auth/app-config': (200, {}, json.dumps(data).encode())})
            self.assertEqual(rows[0]['status'], 1)

    def test_missing_or_html_bundle(self):
        for response in [(404, {}, b'gone'), (200, {'Content-Type': 'text/html'}, b'<html>')]:
            rows, _ = self.run_check({'/assets/index-123.js': response})
            self.assertEqual(rows[1]['status'], 1)

    def test_untrusted_asset_never_requested(self):
        rows, ctx = self.run_check({'/': (200, {}, b'<div id="root"></div><script type="module" src="https://other/private"></script>')})
        self.assertEqual(rows[1]['status'], 1)
        self.assertEqual(len(ctx.paths), 2)
