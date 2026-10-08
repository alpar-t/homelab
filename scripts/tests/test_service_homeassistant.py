import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets'))
import service_homeassistant as service

CONFIG = json.loads((Path(service.__file__).with_suffix('.json')).read_text())

class Context:
    def __init__(self, fault=None):
        self.fault = fault
        self.calls = []
    def secret(self, key):
        if self.fault == 'secret':
            raise OSError('private-token')
        return 'private-token'
    def remaining(self):
        return 25
    def check(self, name, bad, detail):
        return dict(name=name, status=int(bad), detail=detail)
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.fault == 'timeout':
            raise TimeoutError('private-token')
        value = {'version': '2026.10.0', 'components': ['api', 'recorder', 'automation']}
        if '/states/' in url:
            value = {'entity_id': url.rsplit('/', 1)[1], 'state': '0', 'last_updated': '2000-01-01T00:00:00Z'}
            if self.fault in ('unknown', 'unavailable', 'NaN'):
                value['state'] = self.fault
            if self.fault == 'identity':
                value['entity_id'] = 'sensor.other'
        if self.fault == 'missing-integration':
            value['components'] = []
        return SimpleNamespace(status=401 if self.fault == 'auth' else 200,
                               body=b'private-token' if self.fault == 'malformed' else json.dumps(value).encode())

class Tests(unittest.TestCase):
    def test_healthy_zero_and_unchanged_states(self):
        ctx = Context()
        self.assertEqual([r['status'] for r in service.run(ctx, CONFIG)], [0, 0])
        self.assertEqual(len(ctx.calls), 4)
        for url, kwargs in ctx.calls:
            self.assertNotIn('method', kwargs)  # GET only
            self.assertLessEqual(kwargs['timeout'], 5)
    def test_unavailable_numeric_entities(self):
        for fault in ('unknown', 'unavailable', 'NaN', 'identity'):
            self.assertEqual(service.run(Context(fault), CONFIG)[1]['status'], 1)
    def test_missing_integration(self):
        self.assertEqual(service.run(Context('missing-integration'), CONFIG)[0]['status'], 1)
    def test_fail_closed_and_redacted(self):
        for fault in ('secret', 'timeout', 'auth', 'malformed'):
            ctx = Context(fault)
            rows = service.run(ctx, CONFIG)
            self.assertEqual([r['status'] for r in rows], [1, 1])
            self.assertNotIn('private-token', str(rows))
            if fault == 'secret':
                self.assertEqual(ctx.calls, [])
