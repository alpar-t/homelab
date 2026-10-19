import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('frigate', ROOT / 'config/zabbix/manifests/assets/service_frigate.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Context:
    now = 10000

    def __init__(self):
        self.stats = {'service': {'last_updated': 9999, 'uptime': 500},
                      'cameras': {'test': {'camera_fps': 12, 'process_fps': 12,
                                           'pid': 1, 'capture_pid': 2, 'ffmpeg_pid': 3,
                                           'detection_fps': 0}},
                      'processes': {'recording': {'pid': 4}}}
        self.settings = {'cameras': {'test': {'enabled': True, 'record': {'enabled': True},
                                              'detect': {'enabled': False}}}}
        self.status = 200
        self.error = False

    def remaining(self):
        return 10

    def http(self, url, **kwargs):
        assert kwargs['timeout'] <= self.remaining()
        assert kwargs['max_bytes'] == 262144
        if self.error:
            raise TimeoutError('private response or secret')
        value = self.stats if url.endswith('/stats') else self.settings
        return SimpleNamespace(status=self.status, body=json.dumps(value).encode())

    def check(self, name, bad, detail, **kwargs):
        return {'name': name, 'status': int(bool(bad)), 'detail': detail, **kwargs}


class FrigateTests(unittest.TestCase):
    def run_check(self, ctx):
        return module.run(ctx, {'url': 'http://test'})

    def test_healthy_disabled_detection_and_idle_scene(self):
        self.assertEqual([r['status'] for r in self.run_check(Context())], [0, 0, 0])

    def test_stuck_capture_despite_existing_pid(self):
        ctx = Context()
        ctx.stats['cameras']['test']['camera_fps'] = 0
        self.assertEqual(self.run_check(ctx)[1]['status'], 1)

    def test_disabled_camera_does_not_need_stats_or_record_worker(self):
        ctx = Context()
        ctx.settings['cameras']['test']['enabled'] = False
        ctx.stats['cameras'] = {}
        ctx.stats['processes'] = {}
        self.assertEqual([r['status'] for r in self.run_check(ctx)], [0, 0, 0])

    def test_missing_enabled_camera_and_record_worker(self):
        ctx = Context()
        ctx.stats['cameras'] = {}
        ctx.stats['processes'] = {}
        self.assertEqual([r['status'] for r in self.run_check(ctx)], [0, 1, 1])

    def test_startup_grace_and_stale_stats(self):
        ctx = Context()
        ctx.stats['service']['uptime'] = 60
        ctx.stats['cameras'] = {}
        self.assertEqual(self.run_check(ctx)[1]['status'], 0)
        ctx.stats['service']['last_updated'] = 9000
        rows = self.run_check(ctx)
        self.assertEqual(rows[0]['status'], 1)
        self.assertTrue(all(row['observation'] == 'unknown' for row in rows[1:]))

    def test_invalid_unauthorized_timeout_are_redacted(self):
        for kind in ('status', 'error', 'schema', 'nan'):
            ctx = Context()
            if kind == 'status': ctx.status = 401
            if kind == 'error': ctx.error = True
            if kind == 'schema': ctx.stats = {'secret': 'private'}
            if kind == 'nan': ctx.stats['service']['last_updated'] = float('nan')
            rows = self.run_check(ctx)
            self.assertEqual(rows[0]['status'], 1)
            self.assertTrue(all(row['observation'] == 'unknown' for row in rows[1:]))
            self.assertNotIn('private', json.dumps(rows))


if __name__ == '__main__':
    unittest.main()
