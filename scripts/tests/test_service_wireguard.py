import copy
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets/service_wireguard.py'
spec = importlib.util.spec_from_file_location('wireguard', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Context:
    def __init__(self):
        self.kube = self
        self.service = {'spec': {'type': 'LoadBalancer', 'externalTrafficPolicy': 'Local',
                        'selector': {'app': 'wireguard-home'}, 'ports': [
                            {'protocol': 'UDP', 'port': 41641, 'targetPort': 'wireguard'}]},
                        'status': {'loadBalancer': {'ingress': [{'ip': '192.168.1.208'}]}}}
        self.slices = {'items': [{'ports': [{'name': 'wireguard', 'protocol': 'UDP', 'port': 41641}],
                                 'endpoints': [{'conditions': {'ready': True}, 'nodeName': 'node',
                                                'addresses': ['10.42.0.1'],
                                                'targetRef': {'kind': 'Pod', 'namespace': 'wireguard'}}]}]}
        self.error = None

    def get(self, path):
        if self.error:
            raise self.error
        return self.slices if 'endpointslices?' in path else self.service

    def remaining(self):
        return 30

    def check(self, name, bad, detail):
        return {'name': name, 'status': int(bad), 'detail': detail}


class Tests(unittest.TestCase):
    def run_check(self, ctx):
        return [x['status'] for x in module.run(ctx, {'vip': '192.168.1.208'})]

    def test_healthy_without_peer_handshake(self):
        self.assertEqual(self.run_check(Context()), [0, 0])

    def test_wrong_udp_contract(self):
        for field, value in [('protocol', 'TCP'), ('port', 123), ('targetPort', 'wrong')]:
            ctx = Context()
            ctx.service['spec']['ports'][0][field] = value
            self.assertEqual(self.run_check(ctx), [1, 0])

    def test_wrong_vip_or_policy(self):
        ctx = Context()
        ctx.service['status']['loadBalancer']['ingress'] = []
        self.assertEqual(self.run_check(ctx), [1, 0])
        ctx = Context()
        ctx.service['spec']['externalTrafficPolicy'] = 'Cluster'
        self.assertEqual(self.run_check(ctx), [1, 0])

    def test_no_ready_or_duplicate_endpoint(self):
        ctx = Context()
        ctx.slices['items'][0]['endpoints'][0]['conditions']['ready'] = False
        self.assertEqual(self.run_check(ctx), [0, 1])
        ctx = Context()
        ctx.slices['items'].append(copy.deepcopy(ctx.slices['items'][0]))
        self.assertEqual(self.run_check(ctx), [0, 1])

    def test_endpoint_port_or_incomplete_list(self):
        ctx = Context()
        ctx.slices['items'][0]['ports'][0]['port'] = 123
        self.assertEqual(self.run_check(ctx), [0, 1])
        ctx = Context()
        ctx.slices['metadata'] = {'continue': 'next'}
        self.assertEqual(self.run_check(ctx), [0, 1])

    def test_unavailable_malformed_and_redaction(self):
        for error in [PermissionError('secret'), TimeoutError('secret')]:
            ctx = Context()
            ctx.error = error
            records = module.run(ctx, {'vip': '192.168.1.208'})
            self.assertEqual([x['status'] for x in records], [1, 1])
            self.assertNotIn('secret', str(records))
        ctx = Context()
        ctx.slices = {}
        self.assertEqual(self.run_check(ctx), [1, 1])


if __name__ == '__main__':
    unittest.main()
