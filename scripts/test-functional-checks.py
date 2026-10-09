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

    def execute(self):
        self.runner.collect()
        self.runner.states['test']['next_due'] = 0
        self.runner.collect()
        self.runner.jobs.join()
        return self.runner.collect()

    def state(self):
        return dict(slug='test', rows={}, next_due=0, initial_deadline=1000,
                    completed=None, error=None, pending=False, deadline=None)

    def observe(self, state, bad, stamp, **kwargs):
        self.runner._observe(state, [dict(name='Test read', status=int(bad), detail='safe', **kwargs)],
                             dict(failure_grace_seconds=900), stamp)

    def test_cached_samples_cannot_confirm_failure_or_recovery(self):
        state = self.state()
        self.observe(state, True, 1000)
        for _ in range(20):
            self.assertEqual(self.runner._render(state, {}), [])
        self.assertEqual(state['rows']['Test read']['failures'], 1)
        self.observe(state, True, 1001)
        self.assertEqual(state['rows']['Test read']['status'], 0)
        self.observe(state, True, 1900)
        self.assertEqual(state['rows']['Test read']['status'], 1)
        self.observe(state, False, 2000)
        for _ in range(20):
            self.assertEqual(self.runner._render(state, {})[0]['status'], 1)
        self.assertEqual(state['rows']['Test read']['recoveries'], 1)
        self.observe(state, False, 2900)
        self.assertEqual(state['rows']['Test read']['status'], 0)

    def test_unknown_does_not_close_confirmed_problem(self):
        state = self.state()
        self.observe(state, True, 1000)
        self.observe(state, True, 1900)
        self.observe(state, False, 2000)
        self.observe(state, False, 2100, observation='unknown')
        row = state['rows']['Test read']
        self.assertEqual((row['status'], row['sequence'], row['observed_at']), (1, 3, 2000))
        self.assertEqual(row['recoveries'], 0)
        self.observe(state, False, 2900)
        self.assertEqual(row['status'], 1)
        self.observe(state, False, 3800)
        self.assertEqual(row['status'], 0)

    def test_deferred_coverage_is_dashboard_information(self):
        state = self.state()
        self.observe(state, True, 1000, observation='deferred')
        row = self.runner._render(state, {})[0]
        self.assertEqual((row['status'], row['severity'], row['notification'], row['raw_status']),
                         (1, 1, 'dashboard', 'deferred'))
        self.assertEqual(row['observation_sequence'], 0)

    def test_state_persists_safe_latch_over_restart(self):
        path = self.directory / 'state.json'
        runner = FunctionalChecks(None, self.directory, check, state_path=path)
        state = self.state()
        runner.states['test'] = state
        self.observe(state, True, 1000)
        self.observe(state, True, 1900)
        state['rows']['Test read']['detail'] = 'do-not-persist-response-body'
        runner._persist()
        self.assertNotIn('do-not-persist', path.read_text())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        restored = FunctionalChecks(None, self.directory, check, state_path=path)
        state = self.state()
        state['rows'] = restored.saved['test']
        self.assertEqual(restored._render(state, {})[0]['status'], 1)
        restored._observe(state, [dict(name='Test read', status=0, detail='maintenance', observation='unknown')], {}, 3000)
        self.assertEqual(restored._render(state, {})[0]['status'], 1)

    def test_telemetry_outage_does_not_fan_out_service_failures(self):
        self.service("def run(ctx, config): return [ctx.check('Test read', False, 'ok')]")
        self.execute()
        rows = self.execute()
        state = self.runner.states['test']
        state.update(error='functional observation unavailable', pending=False, next_due=time.monotonic() + 1000)
        self.runner._observe_telemetry(state, True, dict(failure_grace_seconds=0, minimum_failure_observations=1), 1000)
        rows = self.runner.collect()
        self.assertEqual([r['status'] for r in rows], [1, 0])
        self.assertEqual(rows[1]['raw_status'], 'unknown')
        self.assertIn('confirmed state retained', rows[1]['detail'])

    def test_failure_cadence_stays_slow_and_uses_completion(self):
        self.service("def run(ctx, config): return [ctx.check('Test read', True, 'failed')]", {'interval': 1800})
        self.execute()
        state = self.runner.states['test']
        self.assertEqual(state['next_due'] - state['finished'], 1800)
        with patch('functional.time.monotonic', return_value=state['finished'] + 120):
            self.runner.collect()
        self.assertFalse(state['pending'])
        self.assertEqual(state['rows']['Test read']['failures'], 1)

    def test_staggered_start_has_bounded_warmup(self):
        self.service("def run(ctx, config): return [ctx.check('Test read', False, 'ok')]")
        for i in range(5):
            (self.directory / ('service_s%d.py' % i)).write_text('')
            (self.directory / ('service_s%d.json' % i)).write_text('{}')
        with patch('functional.time.monotonic', return_value=1000):
            rows = self.runner.collect()
        due = [s['next_due'] for s in self.runner.states.values()]
        self.assertGreater(len(set(due)), 1)
        self.assertTrue(all(1000 <= d < 1900 for d in due))
        self.assertTrue(all(r['status'] == 0 for r in rows))
        state = self.runner.states['test']
        state.update(pending=True, deadline=None)
        with patch('functional.time.monotonic', return_value=state['initial_deadline'] + 1):
            row = next(r for r in self.runner.collect() if r['name'] == 'Functional monitoring test')
        self.assertEqual(row['status'], 1)

    def test_warning_and_config_severity_cap_are_dashboard_only(self):
        state = self.state()
        self.runner._observe(state, [dict(name='Warning', status=1, detail='partial', severity=2)], dict(failure_grace_seconds=0, minimum_failure_observations=1), 1000)
        row = self.runner._render(state, {})[0]
        self.assertEqual((row['severity'], row['notification']), (2, 'dashboard'))
        state = self.state()
        self.runner._observe(state, [dict(name='Staging', status=1, detail='preview', severity=3)],
                             dict(severity=2, notification='dashboard', failure_grace_seconds=0, minimum_failure_observations=1), 1000)
        self.assertEqual(self.runner._render(state, {})[0]['severity'], 2)

    def test_invalid_state_and_config_fail_visibly(self):
        path = self.directory / 'state.json'
        path.write_text('{invalid')
        runner = FunctionalChecks(None, self.directory, check, state_path=path)
        self.assertEqual(runner.collect()[0]['status'], 1)
        self.service('def run(ctx, config): return []', {'workloads': ['invalid']})
        self.assertEqual(self.runner.collect()[0]['status'], 1)
        with self.assertRaises(SafeError):
            self.runner._validate([dict(name='x', status=0, detail='safe', observation='bogus')])

    def test_missing_or_corrupt_baseline_cannot_publish_premature_recovery(self):
        state = self.state()
        self.observe(state, False, 1000)
        self.assertEqual(self.runner._render(state, {}), [])
        for _ in range(20):
            self.assertEqual(self.runner._render(state, {}), [])
        self.observe(state, False, 1900)
        self.assertEqual(self.runner._render(state, {})[0]['status'], 0)
        path = self.directory / 'corrupt.json'
        path.write_text('{broken')
        runner = FunctionalChecks(None, self.directory, check, state_path=path)
        state = self.state()
        runner.states['test'] = state
        runner._observe(state, [dict(name='Test read', status=0, detail='ok')], {}, 1000)
        runner._persist()
        self.assertTrue(runner.persist_error)
        self.assertEqual(runner._render(state, {}), [])
        runner._observe(state, [dict(name='Test read', status=0, detail='ok')], {}, 1900)
        runner._persist()
        self.assertFalse(runner.persist_error)

    def test_per_check_workload_overrides_and_restored_fallback(self):
        state = self.state()
        default = [{'namespace': 'test', 'kind': 'Deployment', 'name': 'default'}]
        specific = [{'namespace': 'test', 'kind': 'Deployment', 'name': 'specific'}]
        config = dict(workloads=default, check_workloads={'Test read': specific})
        self.runner._observe(state, [dict(name='Test read', status=0, detail='ok')], config, 1000)
        self.runner._observe(state, [dict(name='Test read', status=0, detail='ok')], config, 1900)
        self.assertEqual(self.runner._render(state, config)[0]['workloads'], specific)
        del state['rows']['Test read']['workloads']
        self.assertEqual(self.runner._render(state, config)[0]['workloads'], specific)
        self.runner._observe(state, [dict(name='Test read', status=0, detail='ok', workloads=[])], config, 2000)
        self.assertEqual(self.runner._render(state, config)[0]['workloads'], [])
        with self.assertRaises(SafeError):
            self.runner._policy(dict(check_workloads={'Test read': ['not an identity']}))

    def test_recovery_does_not_escalate_dashboard_advisory(self):
        state = self.state()
        policy = dict(failure_grace_seconds=0, minimum_failure_observations=1)
        self.runner._observe(state, [dict(name='Capacity', status=1, detail='partial', severity=2)], policy, 1000)
        self.runner._observe(state, [dict(name='Capacity', status=0, detail='restored', severity=3)], policy, 1900)
        row = self.runner._render(state, policy)[0]
        self.assertEqual((row['status'], row['severity'], row['notification']), (1, 2, 'dashboard'))
        self.runner._observe(state, [dict(name='Capacity', status=0, detail='restored', severity=3)], policy, 2800)
        self.assertEqual(self.runner._render(state, policy)[0]['status'], 0)

    def test_restored_healthy_cache_is_not_new_recovery_evidence(self):
        path = self.directory / 'healthy-state.json'
        runner = FunctionalChecks(None, self.directory, check, state_path=path)
        state = self.state()
        runner.states['test'] = state
        self.observe(state, False, 1000)
        self.observe(state, False, 1900)
        runner._persist()
        restored = FunctionalChecks(None, self.directory, check, state_path=path)
        state = self.state()
        state['rows'] = restored.saved['test']
        self.assertEqual(restored._render(state, {}), [])
        restored._observe(state, [dict(name='Test read', status=0, detail='ok')], {}, 2800)
        self.assertEqual(restored._render(state, {}), [])
        restored._observe(state, [dict(name='Test read', status=0, detail='ok')], {}, 3700)
        self.assertEqual(restored._render(state, {})[0]['status'], 0)

    def test_completed_telemetry_errors_require_independent_observations(self):
        self.service("def run(ctx, config): raise ValueError('unavailable')", dict(interval=900, failure_grace_seconds=1800))
        self.execute()
        state = self.runner.states['test']
        for _ in range(20):
            self.assertEqual(self.runner.collect()[0]['status'], 0)
        self.assertEqual(state['telemetry']['failures'], 1)
        first = state['telemetry']['failure_since']
        self.runner._observe_telemetry(state, True, dict(failure_grace_seconds=1800), first + 1800)
        rows = self.runner.collect()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 1)
        self.runner._observe_telemetry(state, False, {}, first + 2700)
        self.assertEqual(self.runner.collect()[0]['status'], 1)
        self.runner._observe_telemetry(state, False, {}, first + 3600)
        self.assertEqual(self.runner.collect()[0]['status'], 0)

    def test_hung_worker_latches_one_telemetry_problem_without_two_errors(self):
        self.service("def run(ctx, config): return [ctx.check('Test read', False, 'ok')]")
        self.execute()
        state = self.runner.states['test']
        state.update(pending=True, deadline=time.monotonic() - 1, queued_at=time.monotonic())
        rows = self.runner.collect()
        self.assertEqual(rows[0]['status'], 1)
        self.assertEqual(state['telemetry']['failures'], 0)
        self.assertTrue(all(r['status'] == 0 for r in rows[1:]))
        state.update(pending=False, deadline=None, error='late execution unavailable', next_due=time.monotonic() + 900)
        self.runner._observe_telemetry(state, True, {}, time.time())
        self.assertEqual(self.runner.collect()[0]['status'], 1)

    def test_telemetry_latch_persists_without_cached_recovery(self):
        path = self.directory / 'telemetry-state.json'
        runner = FunctionalChecks(None, self.directory, check, state_path=path)
        state = self.state()
        runner.states['test'] = state
        runner._observe_telemetry(state, True, dict(failure_grace_seconds=0, minimum_failure_observations=1), 1000)
        runner._persist()
        restored = FunctionalChecks(None, self.directory, check, state_path=path)
        self.assertEqual(restored.saved_telemetry['test']['status'], 1)
        self.assertEqual(restored.saved_telemetry['test']['recoveries'], 0)

    def test_source_reload_preserves_confirmed_incident(self):
        self.service("def run(ctx, config): return [ctx.check('Test read', True, 'failed')]",
                     dict(failure_grace_seconds=0))
        self.execute()
        self.execute()
        self.assertEqual(self.runner.states['test']['rows']['Test read']['status'], 1)
        self.service("def run(ctx, config): return [ctx.check('Test read', False, 'healthy')]",
                     dict(failure_grace_seconds=0))
        self.assertEqual(self.execute()[1]['status'], 1)
        self.assertEqual(self.execute()[1]['status'], 0)

    def test_secret_keys_and_missing_secret(self):
        ctx = Context(None, time.monotonic() + 5, self.directory)
        (self.directory / 'token').write_text(' private\n')
        self.assertEqual(ctx.secret('token'), 'private')
        for key in ('../token', 'absent'):
            with self.assertRaises(SafeError): ctx.secret(key)

    def test_http_monitor_user_agent_default_and_case_insensitive_override(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value = response
        response.code, response.headers = 200, {}
        response.read1.return_value = b''
        opener = SimpleNamespace(open=MagicMock(return_value=response))
        ctx = Context(None, time.monotonic() + 10)
        with patch('functional.urllib.request.build_opener', return_value=opener):
            ctx.http('http://example.test')
            request = opener.open.call_args.args[0]
            self.assertEqual(request.get_header('User-agent'), 'HomePBP-monitor/1')
            for key in ('User-Agent', 'user-agent', 'USER-AGENT'):
                ctx.http('http://example.test', headers={key: 'Service-specific/2'})
                request = opener.open.call_args.args[0]
                self.assertEqual(request.get_header('User-agent'), 'Service-specific/2')
                self.assertEqual(sum(k.lower() == 'user-agent' for k in request.headers), 1)

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
