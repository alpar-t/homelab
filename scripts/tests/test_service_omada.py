import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

PATH = Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets/service_omada.py'
spec = importlib.util.spec_from_file_location('service_omada', PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Context:
    def __init__(self, data, status=200):
        self.data, self.status, self.calls = data, status, []
    def remaining(self):
        return 5
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.data, Exception):
            raise self.data
        return SimpleNamespace(status=self.status, body=self.data if isinstance(self.data, bytes) else json.dumps(self.data).encode())
    def check(self, name, bad, detail):
        return dict(name=name, status=int(bool(bad)), detail=detail)


class OmadaTests(unittest.TestCase):
    def healthy(self):
        return {'errorCode': 0, 'result': {'controllerVer': '6.1.0.19', 'apiVer': '3', 'configured': True, 'registeredRoot': True}}
    def run_check(self, data, status=200):
        return module.run(Context(data, status), {'url': 'http://controller/api/info', 'api_version': '3'})[0]
    def test_configured_bootstrap(self):
        ctx = Context(self.healthy())
        result = module.run(ctx, {'url': 'http://controller/api/info', 'api_version': '3'})[0]
        self.assertEqual(result['status'], 0)
        self.assertEqual(ctx.calls[0][1], {'timeout': 5, 'max_bytes': 16384})
        self.assertIn('connectivity unverified', result['detail'])
    def test_bad_contracts(self):
        for field, value in [('configured', False), ('registeredRoot', False), ('apiVer', '4'), ('controllerVer', 'unknown')]:
            data = self.healthy()
            data['result'][field] = value
            with self.subTest(field=field):
                self.assertEqual(self.run_check(data)['status'], 1)
        for data in [[], {}, {'errorCode': True, 'result': self.healthy()['result']}, {'errorCode': -1}, b'<html>login</html>']:
            self.assertEqual(self.run_check(data)['status'], 1)
    def test_http_auth_redirect_and_errors(self):
        for status in (302, 401, 403, 500):
            self.assertEqual(self.run_check(self.healthy(), status)['status'], 1)
        result = self.run_check(TimeoutError('private token'))
        self.assertEqual(result['status'], 1)
        self.assertNotIn('private token', result['detail'])


if __name__ == '__main__':
    unittest.main()
