import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


PATH = Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets/service_frigate_gpu.py'
SPEC = importlib.util.spec_from_file_location('service_frigate_gpu', PATH)
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)


class Context:
    def __init__(self, stats=None, error=False):
        self.stats, self.error = stats, error

    def remaining(self):
        return 10

    def http(self, url, **kwargs):
        if self.error:
            raise TimeoutError()
        return SimpleNamespace(status=200, body=json.dumps(self.stats).encode())

    def check(self, name, bad, detail, severity=3, observation='known'):
        return dict(name=name, status=int(bool(bad)), detail=detail,
                    severity=severity, observation=observation)


class FrigateDetectorTests(unittest.TestCase):
    def setUp(self):
        self.config = {'stats_url': 'http://frigate.frigate.svc.cluster.local:5000/api/stats'}
        self.stats = {'detectors': {'ov': {'pid': 664}},
                      'gpu_usages': {'intel-vaapi': {'clients': {'664': '0.0%', '895': '0.0%'}}}}

    def check(self, stats=None, error=False):
        return {row['name']: row for row in service.run(
            Context(self.stats if stats is None else stats, error), self.config)}

    def test_gpu_detector_is_healthy_even_when_gpu_utilization_reads_zero(self):
        rows = self.check()
        self.assertEqual(rows['Frigate object detection on GPU']['status'], 0)
        self.assertEqual(rows['Frigate detector telemetry']['status'], 0)

    def test_cpu_fallback_is_detected_even_if_detector_keeps_its_name(self):
        self.stats['gpu_usages']['intel-vaapi']['clients'].pop('664')
        row = self.check()['Frigate object detection on GPU']
        self.assertEqual((row['status'], row['severity']), (1, 4))

    def test_mixed_detectors_alert_if_any_one_uses_cpu(self):
        self.stats['detectors']['cpu'] = {'pid': 777}
        self.assertEqual(self.check()['Frigate object detection on GPU']['status'], 1)

    def test_unavailable_stats_do_not_claim_cpu_fallback_or_recovery(self):
        for rows in (self.check(error=True), self.check({'detectors': {}, 'gpu_usages': {}})):
            self.assertEqual(rows['Frigate detector telemetry']['status'], 1)
            self.assertEqual(rows['Frigate object detection on GPU']['observation'], 'unknown')


if __name__ == '__main__':
    unittest.main()
