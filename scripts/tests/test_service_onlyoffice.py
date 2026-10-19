import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ASSETS = Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('onlyoffice', ASSETS / 'service_onlyoffice.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ASSETS / 'service_onlyoffice.json').read_text())


class Context:
    def __init__(self):
        actions = ''.join(f'<action name="edit" ext="{e}" urlsrc="http://opencloud-onlyoffice/hosting/wopi/edit"/>' for e in CONFIG['extensions'])
        self.responses = {
            '/healthcheck': (200, b'true'),
            '/hosting/discovery': (200, ('<wopi-discovery><net-zone><app>'+actions+'</app></net-zone></wopi-discovery>').encode()),
            '/hosting/capabilities': (200, json.dumps({'productVersion': '9.4.0', 'hasMobileSupport': True, 'convert-to': {'available': True, 'endpoint': '/lool/convert-to'}}).encode()),
            '/app/list': (200, json.dumps({'mime-types': [{'ext': e, 'app_providers': [{'product_name': 'OnlyOffice', 'address': 'eu.opencloud.api.collaboration'}]} for e in CONFIG['extensions']]}).encode()),
            '/wopi/files/monitoring-nonexistent': (401, b'Unauthorized\n')}
        self.calls = []

    def remaining(self):
        return 29

    def http(self, url, **kwargs):
        from urllib.parse import urlsplit
        self.calls.append((url, kwargs))
        value = self.responses[urlsplit(url).path]
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(status=value[0], body=value[1], headers={})

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)


class Checks(unittest.TestCase):
    def test_healthy_and_bounded(self):
        ctx = Context()
        self.assertEqual([r['status'] for r in module.run(ctx, CONFIG)], [0, 0, 0])
        self.assertEqual(len(ctx.calls), 5)
        self.assertTrue(all(k['timeout'] <= 5 and k['max_bytes'] <= 262144 for _, k in ctx.calls))

    def test_contract_failures(self):
        cases = [('/healthcheck', (200, b'false'), 0),
                 ('/hosting/discovery', (200, b'<html/>'), 1),
                 ('/hosting/discovery', (200, b'<!DOCTYPE x><wopi-discovery/>'), 1),
                 ('/hosting/capabilities', (200, b'{}'), 1),
                 ('/app/list', (200, b'{"mime-types":[]}'), 2),
                 ('/app/list', (401, b'private response'), 2),
                 ('/wopi/files/monitoring-nonexistent', (200, b'login'), 2),
                 ('/wopi/files/monitoring-nonexistent', (404, b'not found'), 2)]
        for path, value, index in cases:
            with self.subTest(path=path, value=value):
                ctx = Context()
                ctx.responses[path] = value
                self.assertEqual(module.run(ctx, CONFIG)[index]['status'], 1)

    def test_timeout_isolated_and_redacted(self):
        ctx = Context()
        ctx.responses['/healthcheck'] = TimeoutError('sensitive token')
        rows = module.run(ctx, CONFIG)
        self.assertEqual([r['status'] for r in rows], [1, 0, 0])
        self.assertNotIn('sensitive', json.dumps(rows))

    def test_wrong_editor_origin(self):
        ctx = Context()
        status, body = ctx.responses['/hosting/discovery']
        ctx.responses['/hosting/discovery'] = status, body.replace(b'opencloud-onlyoffice', b'wrong-editor')
        self.assertEqual(module.run(ctx, CONFIG)[1]['status'], 1)


if __name__ == '__main__':
    unittest.main()
