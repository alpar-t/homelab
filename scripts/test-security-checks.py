#!/usr/bin/env python3
"""Exercise CVE identity, short-job retention and urgent-only notification."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'config/zabbix/manifests/assets'))
from collector import check
import security_checks as security
import security_review_controller as review

NOW = 1792890000
REF = 'docker.io/example/web@sha256:' + 'a' * 64
OTHER_REF = 'docker.io/example/web@sha256:' + 'a' * 63 + 'b'
SERVICE = 'apps/Deployment/web/web'
OTHER_SERVICE = 'jobs/CronJob/daily/worker'
CVE = 'CVE-2026-12345'
FINDING = {'id': CVE, 'packages': [{'name': 'libx', 'installed': '1', 'fixed': '2'}],
           'url': 'https://example.org/advisory'}


def snapshot(images=None, recent=None):
    images = {REF: [SERVICE]} if images is None else images
    recent = {} if recent is None else recent
    refs = set(images) | set(recent)
    return {'started_at': NOW - 20000, 'inventory_at': NOW - 10,
            'inventory_error': '', 'watch_at': NOW - 5, 'watch_error': '',
            'images': images, 'recent_images': recent, 'unresolved': [],
            'reports': {ref: {'scanned_at': NOW - 30, 'findings': [FINDING]} for ref in refs},
            'errors': {}}


class IdentityTests(unittest.TestCase):
    def test_full_digest_and_service_define_raw_identity(self):
        first = security.raw_check_id(REF, CVE, SERVICE)
        self.assertNotEqual(first, security.raw_check_id(OTHER_REF, CVE, SERVICE))
        self.assertNotEqual(first, security.raw_check_id(REF, CVE, OTHER_SERVICE))
        self.assertNotEqual(first, security.urgent_check_id(REF, CVE, SERVICE))

    def test_running_and_recent_service_checks_are_dashboard_only(self):
        data = snapshot(recent={REF: {OTHER_SERVICE: NOW - 60}})
        rows, complete = security.evaluate(data, NOW, check)
        self.assertTrue(complete)
        raw = [row for row in rows if row['name'].startswith('Critical ')]
        self.assertEqual(len(raw), 2)
        self.assertEqual({row['id'] for row in raw}, {
            security.raw_check_id(REF, CVE, SERVICE),
            security.raw_check_id(REF, CVE, OTHER_SERVICE)})
        self.assertTrue(all(row['notification'] == 'dashboard' for row in raw))
        self.assertIn('exposure=running', next(row['detail'] for row in raw
                                              if row['id'] == security.raw_check_id(REF, CVE, SERVICE)))
        self.assertIn('exposure=recent', next(row['detail'] for row in raw
                                             if row['id'] == security.raw_check_id(REF, CVE, OTHER_SERVICE)))
        self.assertEqual(next(row for row in rows if row['name'] == 'Security image watch')['notification'],
                         'page')

    def test_controller_and_collector_agree_on_exact_current_and_recent_ids(self):
        data = snapshot(recent={REF: {OTHER_SERVICE: NOW - 60}})
        raw = {row['id'] for row in security.evaluate(data, NOW, check)[0]
               if row['name'].startswith('Critical ')}
        controller_rows = review.finding_rows(data, NOW)
        self.assertEqual(raw, {row['check_id'] for row in controller_rows.values()})

    def test_recent_exposure_expires_after_seven_days(self):
        data = snapshot(images={}, recent={REF: {OTHER_SERVICE: NOW - 7 * 86400 - 1}})
        rows, _ = security.evaluate(data, NOW, check)
        self.assertFalse(any(row['name'].startswith('Critical ') for row in rows))

    def test_running_wins_for_same_recent_consumer(self):
        data = snapshot(recent={REF: {SERVICE: NOW - 100}})
        rows, _ = security.evaluate(data, NOW, check)
        raw = [row for row in rows if row['name'].startswith('Critical ')]
        self.assertEqual(len(raw), 1)
        self.assertIn('exposure=running', raw[0]['detail'])

    def test_watch_failure_blocks_recovery_and_pages(self):
        data = snapshot()
        data['watch_error'] = 'TimeoutError'
        rows, complete = security.evaluate(data, NOW, check)
        self.assertFalse(complete)
        self.assertEqual(next(row for row in rows if row['name'] == 'Security image watch')['status'], 1)
        self.assertEqual(next(row for row in rows if row['name'].startswith('Critical '))['status'], 1)


class ReviewTests(unittest.TestCase):
    def controller(self, **overrides):
        value = {'generated_at': NOW - 5, 'healthy': True, 'error': '',
                 'queue_depth': 1, 'overdue_count': 0, 'unmuted_count': 0,
                 'pending_count': 0,
                 'ready_check_ids': [security.raw_check_id(REF, CVE, SERVICE)],
                 'urgent': [{'image': REF, 'cve': CVE, 'service': SERVICE,
                             'check_id': security.raw_check_id(REF, CVE, SERVICE),
                             'finding_id': 'review-1', 'detail': 'reachable parser path',
                             'action_summary': 'Disable image uploads until patched',
                             'reviewed_at': NOW - 30}]}
        value.update(overrides)
        return value

    def monitor(self, directory):
        return security.SecurityMonitor(check, state_path=Path(directory) / 'lifecycle.json',
                                        review_token=Path(directory) / 'token')

    def test_only_exact_active_review_becomes_urgent_page(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor = self.monitor(directory)
            active = {security.raw_check_id(REF, CVE, SERVICE)}
            rows, bad, _, ready, pending = monitor.review_checks(self.controller(), active, NOW)
            self.assertFalse(bad)
            self.assertEqual(ready, active)
            self.assertEqual(pending, 0)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['id'], security.urgent_check_id(REF, CVE, SERVICE))
            self.assertEqual((rows[0]['notification'], rows[0]['notify_delay'],
                              rows[0]['failure_samples']), ('page', 'immediate', 1))
            self.assertIn('Action: Disable image uploads until patched', rows[0]['detail'])
            self.assertEqual(monitor.review_checks(self.controller(), set(), NOW)[0], [])
            wrong = self.controller(urgent=[{**self.controller()['urgent'][0], 'check_id': 'bad'}])
            with self.assertRaises(ValueError):
                monitor.review_checks(wrong, active, NOW)

    def test_controller_backlog_pages_as_review_fault(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor = self.monitor(directory)
            _, bad, detail, _, _ = monitor.review_checks(self.controller(overdue_count=2), set(), NOW)
            self.assertTrue(bad)
            self.assertIn('overdue=2', detail)
            with self.assertRaises(ValueError):
                monitor.review_checks(self.controller(generated_at=NOW - 1000), set(), NOW)

    def test_healthy_controller_holds_raw_event_until_exact_mute_ready(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self, *_):
                return json.dumps(snapshot()).encode()

        with tempfile.TemporaryDirectory() as directory:
            monitor = self.monitor(directory)
            controller = self.controller(ready_check_ids=[], pending_count=1, urgent=[])
            with patch.object(security.time, 'time', return_value=NOW), \
                    patch.object(security.urllib.request, 'urlopen', return_value=Response()), \
                    patch.object(monitor, 'fetch_review', return_value=controller):
                rows = monitor.collect()
            self.assertFalse(any(row['name'].startswith('Critical ') for row in rows))
            pending = next(row for row in rows if row['name'] == 'Security review pending')
            self.assertEqual((pending['status'], pending['notification']), (1, 'dashboard'))
            self.assertEqual(next(row for row in rows if row['name'] == 'Security review automation')['status'], 0)

            controller['ready_check_ids'] = [security.raw_check_id(REF, CVE, SERVICE)]
            controller['pending_count'] = 0
            with patch.object(security.time, 'time', return_value=NOW + 60), \
                    patch.object(security.urllib.request, 'urlopen', return_value=Response()), \
                    patch.object(monitor, 'fetch_review', return_value=controller):
                rows = monitor.collect()
            self.assertEqual(next(row for row in rows if row['name'].startswith('Critical '))['notification'],
                             'dashboard')

            # A prior raw check must not leak back from lifecycle state when
            # its exact maintenance is no longer confirmed active.
            controller['ready_check_ids'] = []
            controller['pending_count'] = 1
            with patch.object(security.time, 'time', return_value=NOW + 90), \
                    patch.object(security.urllib.request, 'urlopen', return_value=Response()), \
                    patch.object(monitor, 'fetch_review', return_value=controller):
                rows = monitor.collect()
            self.assertFalse(any(row['name'].startswith('Critical ') for row in rows))

    def test_controller_outage_keeps_raw_visible_without_whatsapp(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self, *_):
                return json.dumps(snapshot()).encode()

        with tempfile.TemporaryDirectory() as directory:
            monitor = self.monitor(directory)
            with patch.object(security.time, 'time', return_value=NOW), \
                    patch.object(security.urllib.request, 'urlopen', return_value=Response()), \
                    patch.object(monitor, 'fetch_review', side_effect=OSError('down')):
                rows = monitor.collect()
            raw = next(row for row in rows if row['name'].startswith('Critical '))
            fault = next(row for row in rows if row['name'] == 'Security review automation')
            self.assertEqual((raw['status'], raw['notification']), (1, 'dashboard'))
            self.assertEqual((fault['status'], fault['notification']), (1, 'page'))

    def test_old_digest_level_raw_check_lifecycle_is_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lifecycle.json'
            old = check('Critical CVE-2026-12345 web@aaaaaaaaaaaa', 'security', True, 'old')
            path.write_text(json.dumps({old['id']: {'check': old, 'last_seen': NOW - 60}}))
            life = security.SecurityCheckLifecycle(path)
            self.assertEqual(life.records[old['id']]['check']['notification'], 'dashboard')

    def test_review_outage_does_not_recover_prior_urgent_page(self):
        with tempfile.TemporaryDirectory() as directory:
            life = security.SecurityCheckLifecycle(Path(directory) / 'lifecycle.json')
            monitor = self.monitor(directory)
            active = {security.raw_check_id(REF, CVE, SERVICE)}
            urgent, _, _, _, _ = monitor.review_checks(self.controller(), active, NOW)
            life.reconcile(urgent, True, NOW)
            retained = life.reconcile([], False, NOW + 60)
            self.assertEqual(len(retained), 1)
            self.assertEqual((retained[0]['status'], retained[0]['notification']), (1, 'page'))

    def test_unrelated_pending_mute_does_not_keep_cleared_urgent_page(self):
        with tempfile.TemporaryDirectory() as directory:
            life = security.SecurityCheckLifecycle(Path(directory) / 'lifecycle.json')
            monitor = self.monitor(directory)
            active = {security.raw_check_id(REF, CVE, SERVICE)}
            urgent, _, _, _, _ = monitor.review_checks(self.controller(), active, NOW)
            life.reconcile(urgent, True, NOW)
            recovered = life.reconcile([], False, NOW + 60,
                                       allowed_raw_ids=set(), urgent_complete=True)
            self.assertEqual(len(recovered), 1)
            self.assertEqual((recovered[0]['status'], recovered[0]['notification']),
                             (0, 'page'))


if __name__ == '__main__':
    unittest.main()
