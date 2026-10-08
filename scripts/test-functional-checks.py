#!/usr/bin/env python3
import http.server
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'config/zabbix/manifests/assets'))
from functional import Context, FunctionalChecks, SafeError
from collector import check


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.runner = FunctionalChecks(None, self.directory, check)

    def service(self, code, config=None):
        (self.directory / 'service_test.py').write_text(code)
        (self.directory / 'service_test.json').write_text(json.dumps(config or {}))

    def finish(self):
        self.runner.jobs.join()
        return self.runner.collect()

    def test_discovery_result_and_stable_ids(self):
        self.service("def run(ctx, config): return [ctx.check('Test read', False, 'ok')]")
        self.assertEqual(self.runner.collect()[0]['status'], 1)
        rows = self.finish()
        self.assertEqual([r['status'] for r in rows], [0, 0])
        self.assertEqual(rows[1]['id'], check('Test read', 'x', False, '')['id'])
        self.assertEqual(rows[1]['family'], 'functional/test')
        self.assertIn('sample age=', rows[1]['detail'])

    def test_missing_and_invalid_results_fail_closed(self):
        for code in ("def run(ctx, config): return []", "def run(ctx, config): return [{'name':'x', 'status':False, 'detail':'x'}]", "def run(ctx, config): raise ValueError('secret-token')"):
            self.service(code)
            self.runner.states.clear()
            self.runner.collect()
            rows = self.finish()
            self.assertEqual(rows[0]['status'], 1)
            self.assertNotIn('secret-token', str(rows))
        (self.directory / 'service_test.py').unlink()
        self.assertEqual(self.runner.collect()[0]['status'], 1)

    def test_cached_checks_fail_on_missed_deadline(self):
        self.service("def run(ctx, config): return [ctx.check('Test read', False, 'ok')]")
        self.runner.collect()
        self.finish()
        state = self.runner.states['test']
        state.update(pending=True, deadline=time.monotonic() - 1)
        rows = self.runner.collect()
        self.assertEqual([r['status'] for r in rows], [1, 1])

    def test_late_result_cannot_recover_deadline(self):
        self.service("import time\ndef run(ctx, config):\n time.sleep(1.05)\n return [ctx.check('Test read', False, 'ok')]", {'deadline': 1})
        self.runner.collect()
        rows = self.finish()
        self.assertEqual(rows[0]['status'], 1)
        self.assertIsNone(self.runner.states['test']['result'])
        self.assertIn('deadline exceeded', rows[0]['detail'])

    def test_large_inventory_does_not_expire_queued_jobs(self):
        # A synthetic clock advances faster than the old enqueue deadline.
        # All 49 services still get a fresh execution budget in FIFO order.
        for index in range(49):
            (self.directory / f'service_s{index:02}.py').write_text(
                "import time\ndef run(ctx, config):\n time.sleep(.01)\n return [ctx.check(config['name'], False, 'ok')]"
            )
            (self.directory / f'service_s{index:02}.json').write_text(
                json.dumps({'name': f'Check {index}', 'deadline': 1}))
        real = time.monotonic
        anchor = real()
        with patch('functional.time.monotonic', side_effect=lambda: anchor + (real() - anchor) * 20):
            self.runner.collect()
            rows = self.finish()
        self.assertEqual(len(rows), 98)
        self.assertTrue(all(row['status'] == 0 for row in rows))

    def test_queue_full_does_not_leave_unqueued_pending_state(self):
        import queue
        self.service("def run(ctx, config): return [ctx.check('Test read', False, 'ok')]")
        with patch.object(self.runner.jobs, 'put_nowait', side_effect=queue.Full):
            self.assertEqual(self.runner.collect()[0]['status'], 1)
        self.assertNotIn('test', self.runner.states)
        self.runner.collect()
        self.assertTrue(all(row['status'] == 0 for row in self.finish()))

    def test_failed_checks_retry_after_one_minute_healthy_keep_cadence(self):
        for failure in ("return [ctx.check('Test read', True, 'unavailable')]",
                        "raise ValueError('unavailable')"):
            self.service('def run(ctx, config): ' + failure)
            self.runner.states.clear()
            with patch('functional.time.monotonic', return_value=1000):
                self.runner.collect()
                self.finish()
            original = self.runner.states['test']
            with patch('functional.time.monotonic', return_value=1059):
                self.runner.collect()
            self.assertIs(self.runner.states['test'], original)
            # A healthy second attempt replaces the cached failure at minute one.
            self.service("def run(ctx, config): return [ctx.check('Test read', False, 'ok')]")
            with patch('functional.time.monotonic', return_value=1060):
                self.runner.collect()
                rows = self.finish()
            self.assertIsNot(self.runner.states['test'], original)
            self.assertTrue(all(row['status'] == 0 for row in rows))
            healthy = self.runner.states['test']
            with patch('functional.time.monotonic', return_value=1120):
                self.runner.collect()
            self.assertIs(self.runner.states['test'], healthy)
            with patch('functional.time.monotonic', return_value=1360):
                self.runner.collect()
                self.finish()
            self.assertIsNot(self.runner.states['test'], healthy)

    def test_secret_keys_and_missing_secret(self):
        ctx = Context(None, time.monotonic() + 5, self.directory)
        (self.directory / 'token').write_text(' private\n')
        self.assertEqual(ctx.secret('token'), 'private')
        for key in ('../token', 'absent'):
            with self.assertRaises(SafeError): ctx.secret(key)

    def test_http_error_bounds_and_redirect_credentials(self):
        captured = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                captured.append(self.headers.get('Authorization'))
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', 'http://localhost:' + str(self.server.server_port) + '/ok')
                    self.end_headers()
                else:
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'12345')
            def log_message(self, *args): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        ctx = Context(None, time.monotonic() + 10)
        url = f'http://127.0.0.1:{server.server_port}'
        self.assertEqual(ctx.http(url).status, 401)
        with self.assertRaises(SafeError): ctx.http(url, max_bytes=4)
        self.assertEqual(ctx.http(url + '/redirect').status, 302)
        with self.assertRaises(SafeError):
            ctx.http(url + '/redirect', headers={'Authorization':'private'}, follow_redirects=True)
        self.assertEqual(captured.count('private'), 1)

if __name__ == '__main__': unittest.main()
