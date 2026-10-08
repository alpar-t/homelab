import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('sonarr', ROOT / 'config/zabbix/manifests/assets/service_sonarr.py')
sonarr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sonarr)


class Context:
    def __init__(self):
        self.responses = [{'status': 'OK'}, {'appName': 'Sonarr', 'version': '4.0.17'}, [], []]
        self.calls = []
        self.missing = False
        self.time = 30

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)

    def remaining(self):
        return self.time

    def secret(self, key):
        if self.missing:
            raise RuntimeError('secret-value')
        return 'secret-value'

    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, SimpleNamespace):
            return value
        return SimpleNamespace(status=200, body=json.dumps(value).encode())


class SonarrTests(unittest.TestCase):
    def setUp(self):
        self.ctx = Context()
        self.config = {'base_url': 'http://sonarr:8989', 'credential_key': 'sonarr_read_api_key'}

    def run_check(self):
        rows = sonarr.run(self.ctx, self.config)
        self.assertNotIn('secret-value', json.dumps(rows))
        self.assertNotIn('/private/tv', json.dumps(rows))
        return [r['status'] for r in rows]

    def test_healthy_empty_and_bounded_gets(self):
        self.assertEqual(self.run_check(), [0, 0, 0])
        self.assertEqual(len(self.ctx.calls), 4)
        for url, kwargs in self.ctx.calls:
            self.assertNotIn('secret-value', url)
            self.assertLessEqual(kwargs['timeout'], 5)
            self.assertEqual(kwargs['max_bytes'], 262144)
            self.assertFalse(kwargs['follow_redirects'])

    def test_health_client_failure_and_inaccessible_root_redacted(self):
        self.ctx.responses[2:] = [[{'type': 'warning', 'message': 'secret-value /private/tv'}],
                                  [{'accessible': False, 'path': '/private/tv'}]]
        self.assertEqual(self.run_check(), [0, 1, 1])

    def test_notice_is_not_a_failure(self):
        self.ctx.responses[2] = [{'type': 'notice'}]
        self.assertEqual(self.run_check(), [0, 0, 0])

    def test_missing_credentials_fail_without_authenticated_requests(self):
        self.ctx.missing = True
        self.assertEqual(self.run_check(), [1, 1, 1])
        self.assertEqual(len(self.ctx.calls), 1)

    def test_unauthorized_redirect_html_and_timeout(self):
        for value in [SimpleNamespace(status=401, body=b'secret-value'),
                      SimpleNamespace(status=302, body=b''),
                      SimpleNamespace(status=200, body=b'<html>login</html>'),
                      TimeoutError('secret-value')]:
            with self.subTest(value=type(value).__name__):
                self.ctx = Context()
                self.ctx.responses[1] = value
                self.assertEqual(self.run_check(), [1, 1, 1])

    def test_malformed_semantics_fail_independently(self):
        for health, roots in [({}, {}), ([{'type': 'unknown'}], [{}]),
                              ([None], [{'accessible': 'false'}])]:
            self.ctx = Context()
            self.ctx.responses[2:] = [health, roots]
            self.assertEqual(self.run_check(), [0, 1, 1])

    def test_wrong_application_and_deadline(self):
        self.ctx.responses[1] = {'appName': 'Radarr', 'version': '4'}
        self.assertEqual(self.run_check(), [1, 1, 1])
        self.ctx = Context()
        self.ctx.time = 0
        self.assertEqual(self.run_check(), [1, 1, 1])
        self.assertEqual(self.ctx.calls, [])


if __name__ == '__main__':
    unittest.main()
