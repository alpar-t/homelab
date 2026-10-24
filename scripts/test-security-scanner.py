#!/usr/bin/env python3
"""Scanner inventory, failure retention, and alert semantics."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'config/zabbix/manifests/assets'))
import security_scanner as scanner
import security_checks as checks
from collector import check

NOW = 1792730000
REF = 'docker.io/example/web@sha256:' + 'a' * 64
OTHER = 'ghcr.io/example/job@sha256:' + 'b' * 64
FINDING = {'id': 'CVE-2026-12345', 'packages': [
    {'name': 'library', 'installed': '1.0', 'fixed': '1.1'}],
    'url': 'https://example.org/advisory'}


class InventoryTests(unittest.TestCase):
    def test_runtime_digest_and_owner_not_tag_or_replicaset_hash(self):
        pod = {'metadata': {'namespace': 'apps', 'name': 'web-hash-pod',
                            'ownerReferences': [{'kind': 'ReplicaSet', 'name': 'web-hash',
                                                 'controller': True}]},
               'status': {'phase': 'Running',
                          'containerStatuses': [{'name': 'web', 'imageID': REF}],
                          'initContainerStatuses': [{'name': 'setup',
                                                     'imageID': 'docker-pullable://' + OTHER}]}}
        rs = {('apps', 'web-hash'): {'metadata': {'ownerReferences': [
            {'kind': 'Deployment', 'name': 'web', 'controller': True}]}}}
        images, unresolved = scanner.image_inventory([pod], rs, {})
        self.assertEqual(images[REF], ['apps/Deployment/web/web'])
        self.assertEqual(images[OTHER], ['apps/Deployment/web/setup'])
        self.assertEqual(unresolved, [])
        self.assertIsNone(scanner.canonical_ref('example/web:latest'))

    def test_missing_digest_is_coverage_gap(self):
        pod = {'metadata': {'namespace': 'apps', 'name': 'pending'},
               'status': {'phase': 'Running',
                          'containerStatuses': [{'name': 'web', 'imageID': ''},
                                                {'name': 'other', 'imageID': REF}]}}
        images, unresolved = scanner.image_inventory([pod], {}, {})
        self.assertEqual(len(images), 1)
        self.assertEqual(unresolved, ['apps/Pod/pending/web'])

    def test_only_affected_critical_advisories_are_kept(self):
        report = {'Results': [{'Vulnerabilities': [
            {'VulnerabilityID': 'CVE-2026-12345', 'Severity': 'CRITICAL', 'PkgName': 'lib',
             'InstalledVersion': '1', 'FixedVersion': '2', 'PrimaryURL': 'https://example.org/a'},
            {'VulnerabilityID': 'CVE-2026-12345', 'Severity': 'CRITICAL', 'PkgName': 'lib2',
             'InstalledVersion': '1', 'FixedVersion': ''},
            {'VulnerabilityID': 'CVE-2026-22222', 'Severity': 'CRITICAL',
             'Status': 'not_affected'},
            {'VulnerabilityID': 'CVE-2026-33333', 'Severity': 'HIGH'}]}]}
        found = scanner.critical_findings(report)
        self.assertEqual([f['id'] for f in found], ['CVE-2026-12345'])
        self.assertEqual(len(found[0]['packages']), 2)

    def test_trivy_image_without_packages_is_a_successful_empty_scan(self):
        report = {'SchemaVersion': 2, 'ArtifactName': REF,
                  'Metadata': {'ImageID': 'sha256:' + 'a' * 64}}
        self.assertEqual(scanner.critical_findings(report), [])
        with self.assertRaises(ValueError):
            scanner.critical_findings({})


class CycleTests(unittest.TestCase):
    def test_failed_rescan_retains_findings_and_records_error(self):
        class Kube:
            def inventory(self):
                return {REF: ['apps/Deployment/web/web']}, []

        calls = []

        def scan(ref):
            calls.append(ref)
            if len(calls) == 2:
                raise RuntimeError('registry unavailable')
            return [FINDING]

        with tempfile.TemporaryDirectory() as directory:
            now = [NOW]
            worker = scanner.Scanner(Kube(), scan, Path(directory) / 'state.json', lambda: now[0])
            worker.cycle()
            self.assertEqual(worker.snapshot()['reports'][REF]['findings'], [FINDING])
            now[0] += scanner.SCAN_INTERVAL + 1
            worker.cycle()
            state = worker.snapshot()
            self.assertEqual(state['reports'][REF]['findings'], [FINDING])
            self.assertEqual(state['errors'][REF], 'RuntimeError')
            restored = scanner.Scanner(Kube(), scan, Path(directory) / 'state.json', lambda: now[0])
            self.assertEqual(restored.snapshot()['reports'][REF]['findings'], [FINDING])
            now[0] += scanner.ERROR_RETRY_INTERVAL - 1
            restored.cycle()
            self.assertEqual(len(calls), 2)
            now[0] += 1
            restored.cycle()
            self.assertEqual(len(calls), 3)
            self.assertNotIn(REF, restored.snapshot()['errors'])


class AlertTests(unittest.TestCase):
    def snapshot(self):
        return {'started_at': NOW - 10000, 'inventory_at': NOW - 30,
                'inventory_error': '', 'unresolved': [],
                'images': {REF: ['apps/Deployment/web/web']},
                'reports': {REF: {'scanned_at': NOW - 60, 'findings': [FINDING]}},
                'errors': {}}

    def test_critical_alert_and_coverage_are_independent(self):
        snapshot = self.snapshot()
        rows, complete = checks.evaluate(snapshot, NOW, check)
        by_name = {row['name']: row for row in rows}
        self.assertTrue(complete)
        self.assertEqual(by_name['Critical CVE-2026-12345 web@aaaaaaaaaaaa']['status'], 1)
        snapshot['errors'][REF] = 'RuntimeError'
        rows, complete = checks.evaluate(snapshot, NOW, check)
        self.assertFalse(complete)
        self.assertEqual(next(row for row in rows if row['name'].startswith('Security scan '))['status'], 1)
        self.assertEqual(next(row for row in rows if row['name'].startswith('Critical '))['status'], 1)

    def test_recovery_waits_for_complete_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            life = checks.SecurityCheckLifecycle(Path(directory) / 'checks.json')
            snapshot = self.snapshot()
            rows, complete = checks.evaluate(snapshot, NOW, check)
            life.reconcile(rows, complete, NOW)
            snapshot['images'] = {OTHER: ['apps/Deployment/web/web']}
            snapshot['reports'] = {}
            rows, complete = checks.evaluate(snapshot, NOW + 60, check)
            rows = life.reconcile(rows, complete, NOW + 60)
            self.assertEqual(next(row for row in rows if row['name'].startswith('Critical '))['status'], 1)
            snapshot['reports'][OTHER] = {'scanned_at': NOW + 90, 'findings': []}
            snapshot['inventory_at'] = NOW + 90
            rows, complete = checks.evaluate(snapshot, NOW + 100, check)
            rows = life.reconcile(rows, complete, NOW + 100)
            self.assertEqual(next(row for row in rows if row['name'].startswith('Critical '))['status'], 0)


if __name__ == '__main__':
    unittest.main()
