import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ASSETS = Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('immich', ASSETS / 'service_immich.py')
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)
CONFIG = json.loads((ASSETS / 'service_immich.json').read_text())


class Context:
    def __init__(self):
        self.responses = [{'major': 3, 'minor': 1, 'patch': 0},
                          {'isInitialized': True, 'isOnboarded': True, 'maintenanceMode': False},
                          {'images': 0, 'videos': 0, 'total': 0}]
        self.missing = False
        self.calls = []

    def remaining(self):
        return 20

    def secret(self, key):
        if self.missing:
            raise ValueError('PRIVATE SECRET ERROR')
        return 'PRIVATE TOKEN'

    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, SimpleNamespace):
            return value
        return SimpleNamespace(status=200, body=json.dumps(value).encode())

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)


class Connection:
    def __init__(self, body):
        self.chunks = [body[i:i+7] for i in range(0, len(body), 7)]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def settimeout(self, value):
        assert 0 < value <= 4
    def sendall(self, data):
        assert b'INFO' in data and b'persistence' in data
    def recv(self, size):
        return self.chunks.pop(0) if self.chunks else b''


def redis_response(loading='0', save='ok', aof='ok'):
    body = f'# Persistence\r\nloading:{loading}\r\nrdb_last_bgsave_status:{save}\r\naof_last_write_status:{aof}\r\n'.encode()
    return b'$' + str(len(body)).encode() + b'\r\n' + body + b'\r\n'


class Tests(unittest.TestCase):
    def run_check(self, ctx=None, redis=None):
        with patch.object(service.socket, 'create_connection', return_value=Connection(redis or redis_response())):
            return service.run(ctx or Context(), CONFIG)

    def test_healthy_empty_library_and_request_bounds(self):
        ctx = Context()
        rows = self.run_check(ctx)
        self.assertEqual([r['status'] for r in rows], [0, 0, 0])
        self.assertEqual(len(ctx.calls), 3)
        for url, options in ctx.calls:
            self.assertLessEqual(options['timeout'], 5)
            self.assertEqual(options['max_bytes'], 16384)
        self.assertIn('/api/assets/statistics', ctx.calls[-1][0])
        self.assertEqual(ctx.calls[-1][1]['headers'], {'x-api-key': 'PRIVATE TOKEN'})
        self.assertNotIn('PRIVATE', json.dumps(rows))

    def test_rejected_missing_or_malformed_statistics(self):
        for value in (SimpleNamespace(status=401, body=b'PRIVATE'), {},
                      {'images': True, 'videos': 0, 'total': 1},
                      {'images': 1, 'videos': 2, 'total': 4},
                      TimeoutError('PRIVATE'), SimpleNamespace(status=200, body=b'not json')):
            ctx = Context()
            ctx.responses[2] = value
            rows = self.run_check(ctx)
            self.assertEqual(rows[1]['status'], 1)
            self.assertEqual(rows[2]['status'], 0)
            self.assertNotIn('PRIVATE', json.dumps(rows))
        ctx = Context()
        ctx.missing = True
        self.assertEqual(self.run_check(ctx)[1]['status'], 1)

    def test_public_api_malformed_and_unavailable(self):
        for value in ({'major': True, 'minor': 1, 'patch': 0},
                      {'major': -1, 'minor': 1, 'patch': 0},
                      SimpleNamespace(status=503, body=b'PRIVATE'),
                      SimpleNamespace(status=200, body=b'[]'), TimeoutError('PRIVATE')):
            ctx = Context()
            ctx.responses[0] = value
            # On failed first request config is not fetched, so supply stats next.
            if not isinstance(value, dict):
                ctx.responses.pop(1)
            rows = self.run_check(ctx)
            self.assertEqual(rows[0]['status'], 1)
            self.assertNotIn('PRIVATE', json.dumps(rows))

    def test_config_broken_upgrade_and_maintenance(self):
        for settings in ({}, {'isInitialized': True, 'isOnboarded': True, 'maintenanceMode': True}):
            ctx = Context()
            ctx.responses[1] = settings
            self.assertEqual(self.run_check(ctx)[0]['status'], 1)

    def test_redis_fragmentation_failures_and_timeout(self):
        for response in (redis_response('1'), redis_response(save='err'), redis_response(aof='err'),
                         b'-NOAUTH PRIVATE\r\n', b'$999999\r\n', b'$5\r\nabc', b'$3\r\nabcXX'):
            self.assertEqual(self.run_check(redis=response)[2]['status'], 1)
        with patch.object(service.socket, 'create_connection', side_effect=TimeoutError('PRIVATE')):
            rows = service.run(Context(), CONFIG)
            self.assertEqual(rows[2]['status'], 1)
            self.assertNotIn('PRIVATE', json.dumps(rows))


if __name__ == '__main__':
    unittest.main()
