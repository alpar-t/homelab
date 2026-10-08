import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

PATH = Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets/service_cnpg.py'
spec = importlib.util.spec_from_file_location('service_cnpg', PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def body(role=0, lag=0, receiver=1, streaming=1, start=1):
    return (f'cnpg_pg_replication_in_recovery {role}\ncnpg_pg_replication_lag {lag}\n'
            f'cnpg_pg_replication_is_wal_receiver_up {receiver}\n'
            f'cnpg_pg_replication_streaming_replicas {streaming}\n'
            f'cnpg_pg_postmaster_start_time {start}\n'
            'cnpg_pg_database_size_bytes{datname="private"} 0\n').encode()


class Context:
    now = 2000000000
    def __init__(self):
        self.cluster = {'metadata': {'name': 'db', 'namespace': 'test'}, 'spec': {'instances': 2},
                        'status': {'currentPrimary': 'db-1', 'instancesReportedState': {
                            'db-1': {'ip': '10.0.0.1'}, 'db-2': {'ip': '10.0.0.2'}}}}
        self.kube = SimpleNamespace(get=lambda path: {'items': [self.cluster]})
        self.http_status = 200
        self.responses = {'10.0.0.1': body(), '10.0.0.2': body(role=1, streaming=0)}
    def remaining(self):
        return 30
    def http(self, url, **kwargs):
        assert kwargs['timeout'] <= 3
        value = self.responses[url.split('/')[2].split(':')[0]]
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(status=self.http_status, body=value)
    def check(self, name, bad, detail, severity=3):
        return {'name': name, 'status': int(bool(bad)), 'detail': detail}


class Tests(unittest.TestCase):
    def setUp(self):
        self.ctx = Context()
        self.config = {'clusters': [['test', 'db']], 'grace_seconds': 600, 'lag_seconds': 300}
    def run_check(self):
        return module.run(self.ctx, self.config)[0]
    def test_healthy_idle_zero_database(self):
        self.assertEqual(self.run_check()['status'], 0)
    def test_broken_roles_and_lag(self):
        for payload in (body(role=0), body(role=1, lag=301), body(receiver=0, role=1)):
            with self.subTest(payload=payload):
                self.ctx.responses['10.0.0.2'] = payload
                self.assertEqual(self.run_check()['status'], 1)
    def test_wrong_primary_role(self):
        self.ctx.responses['10.0.0.1'] = body(role=1)
        self.assertEqual(self.run_check()['status'], 1)
    def test_streaming_missing(self):
        self.ctx.responses['10.0.0.1'] = body(streaming=0)
        self.assertEqual(self.run_check()['status'], 1)
    def test_bad_missing_unauthorized_timeout_redacted(self):
        for payload in (b'<html>login</html>', body().replace(b'in_recovery 0', b'in_recovery NaN'),
                        TimeoutError('private secret'), PermissionError('private secret')):
            with self.subTest(payload=payload):
                self.ctx.responses['10.0.0.1'] = payload
                result = self.run_check()
                self.assertEqual(result['status'], 1)
                self.assertNotIn('private', result['detail'])
    def test_maintenance_and_transition_grace(self):
        self.ctx.cluster['spec']['nodeMaintenanceWindow'] = {'inProgress': True}
        self.ctx.responses['10.0.0.1'] = TimeoutError()
        self.assertEqual(self.run_check()['status'], 0)
        del self.ctx.cluster['spec']['nodeMaintenanceWindow']
        self.ctx.cluster['status']['targetPrimaryTimestamp'] = '2033-05-18T03:32:00Z'
        self.assertEqual(self.run_check()['status'], 0)
    def test_postgres_restart_grace(self):
        self.ctx.responses['10.0.0.1'] = body(role=1, start=self.ctx.now - 5)
        self.assertEqual(self.run_check()['status'], 0)
    def test_missing_instance_and_primary(self):
        del self.ctx.cluster['status']['instancesReportedState']['db-1']
        self.assertEqual(self.run_check()['status'], 1)
    def test_http_unauthorized(self):
        self.ctx.http_status = 401
        self.assertEqual(self.run_check()["status"], 1)
    def test_grace_expires(self):
        self.ctx.responses["10.0.0.1"] = body(role=1, start=self.ctx.now - 601)
        self.assertEqual(self.run_check()["status"], 1)
    def test_inventory_limit(self):
        self.ctx.kube.get = lambda path: {'items': [], 'metadata': {'continue': 'secret'}}
        with self.assertRaises(ValueError):
            self.run_check()
    def test_expired_deadline(self):
        self.ctx.remaining = lambda: 0
        with self.assertRaises(TimeoutError):
            self.run_check()

if __name__ == '__main__':
    unittest.main()
