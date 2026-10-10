import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('tunnel', ASSETS / 'service_cloudflare_tunnel.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ASSETS / 'service_cloudflare_tunnel.json').read_text())


class Context:
    def __init__(self, values=(4, 4, 4), public=200, body=b'<html><title>newjoy.ro</title>', inventory=None):
        self.values = list(values)
        self.public, self.body = public, body
        self.calls = []
        self.inventory = inventory
        self.kube = SimpleNamespace(get=self.get)

    def get(self, path):
        if isinstance(self.inventory, Exception):
            raise self.inventory
        return self.inventory or {'items': [{'status': {'podIP': f'10.42.0.{i+1}'}} for i in range(len(self.values))]}

    def remaining(self):
        return 30

    def check(self, name, bad, detail, severity=3, **kwargs):
        return dict(name=name, status=int(bad), detail=detail, severity=severity, **kwargs)

    def http(self, url, **kwargs):
        self.calls.append(kwargs)
        if '/metrics' in url:
            value = self.values.pop(0)
            if isinstance(value, Exception):
                raise value
            body = value if isinstance(value, bytes) else f'cloudflared_tunnel_ha_connections {value}\n'.encode()
            return SimpleNamespace(status=200, headers={}, body=body)
        return SimpleNamespace(status=self.public, headers={'Content-Type': 'text/html'}, body=self.body)


class Tests(unittest.TestCase):
    def test_healthy_and_rollout_surge(self):
        for values in ((4, 4, 4), (4, 4, 4, 0)):
            ctx = Context(values)
            self.assertEqual([r['status'] for r in module.run(ctx, CONFIG)], [0, 0])
            self.assertLessEqual(sum(c['timeout'] for c in ctx.calls) + 15, 30)
            self.assertEqual(ctx.calls[-1]['headers']['User-Agent'], 'HomePBP-monitor/1')

    def test_connection_failures(self):
        for value in (0, b'bad', b'cloudflared_tunnel_ha_connections NaN', b'cloudflared_tunnel_ha_connections -1', TimeoutError('secret')):
            result = module.run(Context((4, 4, value)), CONFIG)
            self.assertEqual(result[0]['status'], 1)
            self.assertNotIn('secret', str(result))

    def test_insufficient_inventory_and_api_error(self):
        self.assertEqual(module.run(Context((4, 4)), CONFIG)[0]['status'], 1)
        with self.assertRaises(ValueError):
            module.run(Context(inventory=TimeoutError('secret')), CONFIG)

    def test_public_semantics_and_unauthorized(self):
        for ctx in (Context(public=403), Context(public=530), Context(body=b'<html>login</html>')):
            self.assertEqual(module.run(ctx, CONFIG)[1]['status'], 1)

    def test_expired_budget(self):
        ctx = Context()
        ctx.remaining = lambda: 0
        with self.assertRaises(ValueError):
            module.run(ctx, CONFIG)

    def test_partial_redundancy_is_dashboard_but_total_loss_pages(self):
        partial = module.run(Context((4, 4, 0)), CONFIG)[0]
        self.assertEqual((partial['status'], partial['severity'], partial['notification']), (1, 2, 'dashboard'))
        total = module.run(Context((0, 0, 0)), CONFIG)[0]
        self.assertEqual((total['status'], total['severity'], total['notification']), (1, 3, 'page'))

    def test_ambiguous_metric(self):
        with self.assertRaises(ValueError):
            module.connections(b'cloudflared_tunnel_ha_connections 4\ncloudflared_tunnel_ha_connections 4\n')


if __name__ == '__main__':
    unittest.main()
