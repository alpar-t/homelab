import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

PATH = Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets/service_maintainerr.py'
SPEC = importlib.util.spec_from_file_location('service_maintainerr', PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Context:
    def __init__(self, override=None):
        self.override = override or {}
        self.calls = []

    def remaining(self):
        return 12

    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        path = url.split('http://example')[1]
        defaults = {'/api/health/ready': {'status': 'ok', 'database': 'ok'},
                    '/api/media-server': {'machineId': 'fixed', 'version': '1.0'}}
        value = self.override.get(path, defaults.get(path, [{'id': 1, 'items': []}]))
        if isinstance(value, Exception):
            raise value
        if isinstance(value, SimpleNamespace):
            return value
        return SimpleNamespace(status=200, body=json.dumps(value).encode())

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)


class Tests(unittest.TestCase):
    def run_checks(self, override=None):
        ctx = Context(override)
        result = MODULE.run(ctx, {'url': 'http://example', 'radarr_id': 1, 'sonarr_id': 1})
        return ctx, result

    def test_healthy_idle(self):
        ctx, checks = self.run_checks()
        self.assertEqual([c['status'] for c in checks], [0, 0, 0])
        self.assertEqual(len(ctx.calls), 4)
        for url, options in ctx.calls:
            self.assertNotIn('method', options)  # GET only; never tasks/rules
            self.assertLessEqual(options['timeout'], 5)
            self.assertLessEqual(options['max_bytes'], 131072)

    def test_database_or_media_failure(self):
        for value in (None, {}, {'machineId': 'fixed', 'version': 'unknown'}):
            self.assertEqual(self.run_checks({'/api/media-server': value})[1][0]['status'], 1)
        self.assertEqual(self.run_checks({'/api/health/ready': {'status': 'degraded', 'database': 'unreachable'}})[1][0]['status'], 1)

    def test_upstream_swallowed_failure_or_malformed(self):
        for value in ([], {}, [{'id': '1', 'items': []}], [{'id': 1}]):
            checks = self.run_checks({'/api/servarr/radarr/1/profiles': value})[1]
            self.assertEqual([c['status'] for c in checks], [0, 1, 0])

    def test_http_auth_json_and_timeout_fail_closed_safely(self):
        for value in (SimpleNamespace(status=401, body=b'secret'),
                      SimpleNamespace(status=200, body=b'private not json'),
                      TimeoutError('private token')):
            checks = self.run_checks({'/api/servarr/sonarr/1/profiles': value})[1]
            self.assertEqual(checks[2]['status'], 1)
            self.assertNotIn('private', checks[2]['detail'])
            self.assertNotIn('secret', checks[2]['detail'])


if __name__ == '__main__':
    unittest.main()
