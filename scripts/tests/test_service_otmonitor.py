import datetime as dt
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('otmonitor', ROOT / 'config/zabbix/manifests/assets/service_otmonitor.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
NOW = dt.datetime(2026, 10, 8, 8, 20, tzinfo=dt.timezone.utc).timestamp()
CONFIG = {'max_age_seconds': 180, 'timezone': 'Europe/Bucharest'}


def logs(stamp='2026-10-08T08:20:00Z', clock='11:20:00.000000'):
    return '\n'.join(f'{stamp} {clock}  {frame}  {kind}    {text}' for frame, kind, text in (
        ('R00000000', 'Read-Data', 'Status: 00000000 00000000'),
        ('BC0000000', 'Read-Ack', 'Status: 00000000 00000000'),
        ('B40190000', 'Read-Ack', 'Boiler water temperature: 0.00')))


class Checks(unittest.TestCase):
    def evaluate(self, text, now=NOW):
        return module.evaluate(text, now, 180, 'Europe/Bucharest')[0]

    def test_idle_constant_values_are_healthy(self):
        self.assertFalse(self.evaluate(logs()))

    def test_requests_without_boiler_are_bad(self):
        self.assertTrue(self.evaluate(logs().splitlines()[0]))

    def test_stale_and_replayed_source_clock(self):
        self.assertTrue(self.evaluate(logs('2026-10-08T08:10:00Z', '11:10:00.000000')))
        self.assertTrue(self.evaluate(logs(clock='11:10:00.000000')))

    def test_malformed_future_and_commands_not_telemetry(self):
        for text in ('invalid', '2026-10-08T08:20:00Z 11:20:00.000000 Command (via MQTT): CH=0',
                     logs('2026-10-08T09:20:00Z', '12:20:00.000000')):
            self.assertTrue(self.evaluate(text))

    def test_midnight(self):
        now = dt.datetime(2026, 10, 8, 21, 0, 2, tzinfo=dt.timezone.utc).timestamp()
        self.assertFalse(self.evaluate(logs('2026-10-08T21:00:01Z', '23:59:59.000000'), now))

    def test_safe_read_only_calls_and_permission_errors(self):
        calls = []
        def get(path):
            calls.append(path)
            return {'items': [{'metadata': {'name': 'otmonitor-pod'}, 'status': {'phase': 'Running'}}]}
        def read(*args, **kwargs):
            calls.append((args, kwargs))
            return logs()
        ctx = SimpleNamespace(now=NOW, remaining=lambda: 30, kube=SimpleNamespace(get=get, logs=read),
                              check=lambda name, bad, detail: {'name': name, 'status': int(bad), 'detail': detail})
        self.assertEqual(module.run(ctx, CONFIG)[0]['status'], 0)
        self.assertEqual(calls[1][0], ('otmonitor', 'otmonitor-pod', 'log-tailer'))
        def fail(path):
            raise PermissionError('private log content')
        ctx.kube.get = fail
        result = module.run(ctx, CONFIG)[0]
        self.assertEqual(result['status'], 1)
        self.assertNotIn('private', result['detail'])

    def test_missing_source_and_deadline(self):
        ctx = SimpleNamespace(now=NOW, remaining=lambda: 30, kube=SimpleNamespace(get=lambda p: {'items': []}),
                              check=lambda name, bad, detail: {'status': int(bad), 'detail': detail})
        self.assertEqual(module.run(ctx, CONFIG)[0]['status'], 1)
        ctx.remaining = lambda: 1
        self.assertEqual(module.run(ctx, CONFIG)[0]['status'], 1)


if __name__ == '__main__':
    unittest.main()
