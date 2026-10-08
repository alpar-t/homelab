import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ASSETS = Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets'
SPEC = importlib.util.spec_from_file_location('platform', ASSETS / 'service_platform_controllers.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ASSETS / 'service_platform_controllers.json').read_text())
        self.nodes = [{'metadata': {'name': name, 'labels': {'kubernetes.io/arch': 'amd64'}},
                       'status': {'conditions': [{'type': 'Ready', 'status': 'True',
                                                  'lastTransitionTime': '2026-01-01T00:00:00Z'}],
                                  'allocatable': {'gpu.intel.com/i915': '10'}}}
                      for name in self.config['expected_nodes']]

    def run_check(self, response=None):
        response = response if response is not None else {'items': self.nodes}
        ctx = SimpleNamespace(now=1767229200,
                              kube=SimpleNamespace(get=lambda path: response),
                              check=lambda name, bad, detail: {'name': name, 'status': int(bad), 'detail': detail})
        return MODULE.run(ctx, self.config)

    def test_healthy_and_partial_capacity_loss(self):
        self.assertEqual([c['status'] for c in self.run_check()], [0, 0, 0])
        self.nodes[0]['status']['allocatable']['gpu.intel.com/i915'] = '9'
        self.assertEqual([c['status'] for c in self.run_check()], [1, 0, 0])

    def test_missing_registration_and_missing_node(self):
        self.nodes[0]['status']['allocatable'] = {}
        self.nodes.pop()
        self.assertEqual([c['status'] for c in self.run_check()], [1, 0, 1])

    def test_not_ready_recovery_and_selector_exclusion(self):
        for node in self.nodes:
            node['status']['allocatable'] = {}
        self.nodes[0]['status']['conditions'][0]['status'] = 'False'
        self.nodes[1]['status']['conditions'][0]['lastTransitionTime'] = '2026-01-01T00:59:00Z'
        self.nodes[2]['metadata']['labels']['kubernetes.io/arch'] = 'arm64'
        self.assertEqual([c['status'] for c in self.run_check()], [0, 0, 0])

    def test_malformed_or_truncated_inventory(self):
        for response in ({'items': {}}, {'items': [], 'metadata': {'continue': 'more'}}):
            with self.assertRaises(ValueError):
                self.run_check(response)
        self.nodes[0]['status']['allocatable']['gpu.intel.com/i915'] = 'invalid'
        with self.assertRaises(ValueError):
            self.run_check()

    def test_api_failure_is_not_healthy(self):
        def denied(path):
            raise TimeoutError('private error text')
        with self.assertRaises(TimeoutError):
            MODULE.run(SimpleNamespace(kube=SimpleNamespace(get=denied)), self.config)


if __name__ == '__main__':
    unittest.main()
