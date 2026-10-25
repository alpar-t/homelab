#!/usr/bin/env python3
"""Exercise the HOME-107 review gate without a cluster or Zabbix writes."""
import importlib.util
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'config/zabbix/manifests/assets'
import sys
sys.path.insert(0, str(SOURCE))
spec = importlib.util.spec_from_file_location('security_review_controller', SOURCE / 'security_review_controller.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)

IMAGE = 'example.org/app@sha256:' + 'a' * 64
CVE = 'CVE-2026-12345'
SERVICE = 'example/Deployment/app/web'
IMAGE2 = 'example.org/other@sha256:' + 'b' * 64
SERVICE2 = 'example/CronJob/other/worker'
NOW = 1800000000


def snapshot(now=NOW, fingerprint='template-a', recent=False):
    value = {'started_at': now - 100, 'inventory_at': now - 10, 'watch_at': now - 2,
             'inventory_error': '', 'watch_error': '', 'unresolved': [], 'errors': {},
             'images': {} if recent else {IMAGE: [SERVICE]},
             'recent_images': {IMAGE: {SERVICE: now - 60}} if recent else {},
             'first_seen': {IMAGE: now - 1000},
             'consumer_fingerprints': {IMAGE: {SERVICE: fingerprint}},
             'reports': {IMAGE: {'scanned_at': now - 20, 'findings': [
                 {'id': CVE, 'url': 'https://github.com/vendor/app/security/advisories/GHSA-aaaa-bbbb-cccc',
                  'packages': [{'name': 'example', 'installed': '1.0', 'fixed': '1.1'}]}]}}}
    return value


def two_image_snapshot(now=NOW):
    value = snapshot(now)
    value['images'][IMAGE2] = [SERVICE2]
    value['reports'][IMAGE2] = copy.deepcopy(value['reports'][IMAGE])
    value['first_seen'][IMAGE2] = now - 1000
    value['consumer_fingerprints'][IMAGE2] = {SERVICE2: 'template-other'}
    return value


class FakeZabbix:
    def __init__(self):
        self.rows = {}
        self.calls = []
        self.next_id = 1
        self.events = {}

    def host(self):
        return '10683'

    def maintenances(self, hostid):
        assert hostid == '10683'
        return {check: dict(row) for check, row in self.rows.items()}

    def problems(self, hostid):
        return self.events

    def call(self, method, params):
        self.calls.append((method, params))
        if method == 'maintenance.create':
            check = params['tags'][0]['value']
            row = {**params, 'maintenanceid': str(self.next_id)}
            self.next_id += 1
            self.rows[check] = row
            return {'maintenanceids': [row['maintenanceid']]}
        if method == 'maintenance.update':
            updates = params if isinstance(params, list) else [params]
            ids = []
            for update in updates:
                row = next(row for row in self.rows.values() if row['maintenanceid'] == update['maintenanceid'])
                row.update(update)
                ids.append(row['maintenanceid'])
            return {'maintenanceids': ids}
        if method == 'event.acknowledge':
            event = next(event for events in self.events.values() for event in events
                         if event['eventid'] == params['eventids'][0])
            event['acknowledges'].append({'message': params['message']})
            event['acknowledged'] = '0' if params['action'] == 20 else '1'
            return {'eventids': params['eventids']}
        raise AssertionError(method)


class ReviewControllerTests(unittest.TestCase):
    def controller(self, temp, api, now=lambda: NOW):
        path = Path(temp) / 'state.json'
        review.save_state(path, {'schema': 1, 'initialized_at': NOW - 1000,
                                 'seen_images': {IMAGE: NOW - 1000}})
        return review.Controller(api=api, state_path=path, now=now, apply=True)

    def test_reuse_candidates_offer_only_same_digest_intrinsic_peer_evidence(self):
        other_service = 'example/Deployment/app/worker'
        value = snapshot()
        value['images'][IMAGE].append(other_service)
        value['consumer_fingerprints'][IMAGE][other_service] = 'template-worker'
        with tempfile.TemporaryDirectory() as temp:
            controller = self.controller(temp, FakeZabbix())
            controller.rows = review.finding_rows(value, NOW)
            web = next(row for row in controller.rows.values() if row['service'] == SERVICE)
            worker = next(row for row in controller.rows.values() if row['service'] == other_service)
            controller.records = {
                web['check_id']: {'status': 'not_affected', 'reviewed_at': '2027-01-15T08:00:00Z',
                                  'reason': 'The exact image lacks the affected binary irrespective of service configuration.',
                                  'evidence_urls': ['https://example.org/advisory', 'https://example.org/source'],
                                  'recheck_on': ['image_digest_change']},
                worker['check_id']: {'status': 'needs_evidence', 'reason': 'Binary inventory has not been checked.',
                                     'evidence_urls': ['https://example.org/advisory'],
                                     'expires_at': NOW + 30 * 86400},
            }
            candidates = controller.reuse_candidates()
            self.assertEqual(candidates['total'], 1)
            self.assertEqual(candidates['findings'][0]['service'], other_service)
            self.assertEqual(candidates['findings'][0]['peer_reviews'][0]['service'], SERVICE)
            self.assertEqual(candidates['findings'][0]['expires_at'], NOW + 30 * 86400)
            controller.records[web['check_id']]['status'] = 'config'
            self.assertEqual(controller.reuse_candidates()['total'], 0)

    def test_new_finding_queued_immediately_and_gate_waits_for_readback(self):
        api = FakeZabbix()
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', return_value=snapshot()):
            controller = self.controller(temp, api)
            first = controller.tick()
            self.assertTrue(first['healthy'])
            self.assertEqual(first['pending_count'], 1)
            self.assertEqual(first['overdue_count'], 0)
            self.assertEqual(first['ready_check_ids'], [])
            self.assertLessEqual(next(iter(api.rows.values()))['active_since'], NOW - 48 * 3600)
            queued = controller.queue()
            self.assertEqual(queued['total'], 1)
            self.assertEqual(queued['findings'][0]['image'], IMAGE)
            second = controller.tick()
            self.assertEqual(second['ready_check_ids'], [review.raw_check_id(IMAGE, CVE, SERVICE)])
            self.assertEqual(len([call for call in api.calls if call[0] == 'maintenance.create']), 1)

    def test_existing_daily_maintenance_repairs_start_then_waits_for_readback(self):
        api = FakeZabbix()
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', return_value=snapshot()):
            controller = self.controller(temp, api)
            controller.tick()
            check = review.raw_check_id(IMAGE, CVE, SERVICE)
            api.rows[check]['active_since'] = NOW - 60
            first = controller.tick()
            self.assertNotIn(check, first['ready_check_ids'])
            repairs = [params for method, params in api.calls
                       if method == 'maintenance.update' and isinstance(params, list)]
            self.assertEqual(len(repairs), 1)
            self.assertEqual(repairs[0], [{'maintenanceid': api.rows[check]['maintenanceid'],
                                           'active_since': review.daily_safe_start(NOW)}])
            second = controller.tick()
            self.assertIn(check, second['ready_check_ids'])
            self.assertEqual(len([params for method, params in api.calls
                                  if method == 'maintenance.update' and isinstance(params, list)]), 1)

    def test_pending_becomes_overdue_without_extending_mute(self):
        clock = [NOW]
        api = FakeZabbix()
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', side_effect=lambda *_: snapshot(clock[0])):
            controller = self.controller(temp, api, now=lambda: clock[0])
            controller.tick()
            expiry = next(iter(api.rows.values()))['active_till']
            clock[0] += 3601
            value = controller.tick()
            self.assertEqual(value['overdue_count'], 1)
            self.assertEqual(next(iter(api.rows.values()))['active_till'], expiry)

    def test_stale_scanner_causes_fault_and_no_new_mutation(self):
        api = FakeZabbix()
        bad = snapshot()
        bad['inventory_at'] = NOW - 901
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', return_value=bad):
            controller = self.controller(temp, api)
            value = controller.tick()
            self.assertFalse(value['healthy'])
            self.assertEqual(value['ready_check_ids'], [])
            self.assertEqual(api.calls, [])

    def test_recent_exposure_retained_only_seven_days(self):
        value = snapshot(recent=True)
        self.assertEqual(len(review.finding_rows(value, NOW)), 1)
        value['recent_images'][IMAGE][SERVICE] = NOW - 7 * 86400 - 1
        self.assertEqual(len(review.finding_rows(value, NOW)), 0)

    def test_urgent_requires_action_path_impact_and_sources(self):
        api = FakeZabbix()
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', return_value=snapshot()):
            controller = self.controller(temp, api)
            controller.tick()
            row = next(iter(controller.rows.values()))
            proposal = {key: row[key] for key in ('finding_id', 'image', 'cve', 'service', 'check_id')}
            proposal.update(disposition='urgent', reason='Reachable untrusted input reaches the vulnerable decoder and can corrupt process memory immediately.',
                            evidence_urls=['https://github.com/vendor/app/security/advisories/GHSA-aaaa-bbbb-cccc',
                                           'https://github.com/vendor/app/blob/main/decoder.py'],
                            reviewed_at='2027-01-15T08:00:00Z', recheck_on=['7_days'],
                            action_summary='Disable the affected upload endpoint now.',
                            attack_path='Unauthenticated clients submit crafted data to the exposed upload route.',
                            impact='The process can be compromised by a crafted upload.')
            # Fixed NOW is 2027-01-15T08:00:00Z only approximately; use the exact clock.
            from datetime import datetime, timezone
            proposal['reviewed_at'] = datetime.fromtimestamp(NOW, timezone.utc).isoformat().replace('+00:00', 'Z')
            broken = dict(proposal)
            del broken['attack_path']
            with self.assertRaises(ValueError):
                controller.submit_review(broken)
            accepted = controller.submit_review(proposal)
            self.assertEqual(accepted['status'], 'urgent')
            self.assertEqual(controller.snapshot_data['urgent'][0]['action_summary'], proposal['action_summary'])

    def test_one_degraded_image_does_not_blind_other_urgent_review(self):
        api = FakeZabbix()
        current = [two_image_snapshot()]
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', side_effect=lambda *_: current[0]):
            controller = self.controller(temp, api)
            controller.tick()
            row = next(row for row in controller.rows.values() if row['image'] == IMAGE)
            from datetime import datetime, timezone
            proposal = {key: row[key] for key in ('finding_id', 'image', 'cve', 'service', 'check_id')}
            proposal.update(disposition='urgent',
                            reason='A reachable unauthenticated upload passes crafted input to a vulnerable parser and can compromise the service.',
                            evidence_urls=['https://github.com/vendor/app/security/advisories/GHSA-aaaa-bbbb-cccc',
                                           'https://github.com/vendor/app/blob/main/handler.py'],
                            reviewed_at=datetime.fromtimestamp(NOW, timezone.utc).isoformat().replace('+00:00', 'Z'),
                            recheck_on=['7_days'], action_summary='Disable the exposed upload route immediately.',
                            attack_path='Unauthenticated clients submit crafted data to an exposed upload route.',
                            impact='The service may execute attacker-controlled code after parsing.')
            controller.submit_review(proposal)
            damaged = two_image_snapshot()
            damaged['errors'][IMAGE2] = 'RuntimeError'
            damaged['reports'][IMAGE2]['scanned_at'] = NOW - 9 * 3600
            current[0] = damaged
            value = controller.tick()
            self.assertTrue(value['healthy'])
            self.assertGreater(value['overdue_count'], 0)
            self.assertEqual(len(value['urgent']), 1)
            self.assertEqual(value['urgent'][0]['image'], IMAGE)

    def test_expired_finite_mute_keeps_unrelated_urgent_and_queue(self):
        api = FakeZabbix()
        current = [two_image_snapshot()]
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', side_effect=lambda *_: current[0]):
            controller = self.controller(temp, api)
            controller.tick()
            from datetime import datetime, timezone
            row = next(row for row in controller.rows.values() if row['image'] == IMAGE)
            proposal = {key: row[key] for key in ('finding_id', 'image', 'cve', 'service', 'check_id')}
            proposal.update(disposition='urgent',
                            reason='A reachable unauthenticated upload passes crafted input to a vulnerable parser and can compromise the service.',
                            evidence_urls=['https://github.com/vendor/app/security/advisories/GHSA-aaaa-bbbb-cccc',
                                           'https://github.com/vendor/app/blob/main/handler.py'],
                            reviewed_at=datetime.fromtimestamp(NOW, timezone.utc).isoformat().replace('+00:00', 'Z'),
                            recheck_on=['7_days'], action_summary='Disable the exposed upload route immediately.',
                            attack_path='Unauthenticated clients submit crafted data to an exposed upload route.',
                            impact='The service may execute attacker-controlled code after parsing.')
            controller.submit_review(proposal)
            other_check = review.raw_check_id(IMAGE2, CVE, SERVICE2)
            old = api.rows[other_check]
            meta = review.parse_description(old['description'])
            meta['expires_at'] = NOW - 60
            old['description'] = review.description(meta)
            old['active_till'] = NOW - 60
            value = controller.tick()
            self.assertTrue(value['healthy'])
            self.assertEqual(len(value['urgent']), 1)
            self.assertNotIn(other_check, value['ready_check_ids'])
            self.assertGreater(value['overdue_count'], 0)
            self.assertGreater(controller.queue()['total'], 0)

    def test_requires_fix_requeued_on_template_change_without_mute_reset(self):
        api = FakeZabbix()
        current = [snapshot()]
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', side_effect=lambda *_: current[0]):
            controller = self.controller(temp, api)
            controller.tick()
            row = next(iter(controller.rows.values()))
            from datetime import datetime, timezone
            proposal = {key: row[key] for key in ('finding_id', 'image', 'cve', 'service', 'check_id')}
            proposal.update(disposition='requires_fix',
                            reason='The vulnerable parser is reachable through the configured upload route; no compatible vendor patch exists.',
                            evidence_urls=['https://github.com/vendor/app/security/advisories/GHSA-aaaa-bbbb-cccc'],
                            reviewed_at=datetime.fromtimestamp(NOW, timezone.utc).isoformat().replace('+00:00', 'Z'),
                            recheck_on=['vendor_fix', '30_days'])
            controller.submit_review(proposal)
            expiry = next(iter(api.rows.values()))['active_till']
            current[0] = snapshot(fingerprint='template-b')
            value = controller.tick()
            self.assertTrue(value['healthy'])
            self.assertEqual(value['pending_count'], 1)
            self.assertEqual(controller.queue()['total'], 1)
            self.assertEqual(next(iter(api.rows.values()))['active_till'], expiry)

    def test_revoked_permanent_review_gets_finite_mute(self):
        api = FakeZabbix()
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', return_value=snapshot()):
            controller = self.controller(temp, api)
            controller.tick()
            row = next(iter(controller.rows.values()))
            from datetime import datetime, timezone
            proposal = {key: row[key] for key in ('finding_id', 'image', 'cve', 'service', 'check_id')}
            proposal.update(disposition='not_affected',
                            reason='The exact package does not include the vulnerable source component in this image digest.',
                            evidence_urls=['https://example.org/advisory', 'https://example.org/package'],
                            reviewed_at=datetime.fromtimestamp(NOW, timezone.utc).isoformat().replace('+00:00', 'Z'),
                            recheck_on=['image_digest_change', 'advisory_change'])
            controller.submit_review(proposal)
            self.assertEqual(api.rows[row['check_id']]['active_till'], review.PERMANENT_TILL)
            proposal.update(disposition='needs_evidence',
                            reason='The package tracker now contradicts the earlier conclusion; inspect the exact package and use path.',
                            recheck_on=['advisory_change', '30_days'])
            result = controller.submit_review(proposal)
            self.assertEqual(result['expires_at'], NOW + review.TEMP_SECONDS)
            self.assertEqual(api.rows[row['check_id']]['active_till'], NOW + review.TEMP_SECONDS)
            self.assertEqual(review.parse_description(api.rows[row['check_id']]['description'])['status'], 'needs_evidence')

    def test_expiring_permanent_review_keeps_other_urgent_and_queue(self):
        api = FakeZabbix()
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', return_value=two_image_snapshot()):
            controller = self.controller(temp, api)
            controller.tick()
            first = review.raw_check_id(IMAGE, CVE, SERVICE)
            second = review.raw_check_id(IMAGE2, CVE, SERVICE2)
            urgent_meta = review.parse_description(api.rows[first]['description'])
            urgent_meta.update(status='urgent', reason='A verified reachable parser bug allows unauthenticated compromise.',
                               action_summary='Disable the affected upload route now.',
                               reviewed_at='2027-01-15T08:00:00Z')
            api.rows[first]['description'] = review.description(urgent_meta)
            permanent_meta = review.parse_description(api.rows[second]['description'])
            permanent_meta.update(status='not_affected', expires_at=NOW + 30 * 86400,
                                  reviewed_at='2024-01-01T00:00:00Z', legacy_revalidation=True,
                                  review_by=NOW - 1)
            api.rows[second]['description'] = review.description(permanent_meta)
            api.rows[second]['active_till'] = NOW + 30 * 86400
            value = controller.tick()
            self.assertTrue(value['healthy'])
            self.assertEqual(len(value['urgent']), 1)
            self.assertGreater(value['overdue_count'], 0)
            self.assertEqual(controller.queue()['total'], 1)

    def test_advisory_evidence_drift_requeues_only_affected_finding(self):
        api = FakeZabbix()
        current = [two_image_snapshot()]
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', side_effect=lambda *_: current[0]):
            controller = self.controller(temp, api)
            controller.tick()
            urgent_check = review.raw_check_id(IMAGE, CVE, SERVICE)
            changed_check = review.raw_check_id(IMAGE2, CVE, SERVICE2)
            urgent_meta = review.parse_description(api.rows[urgent_check]['description'])
            urgent_meta.update(status='urgent', reason='The exposed parser is reachable by untrusted clients.',
                               action_summary='Disable the affected upload route now.')
            api.rows[urgent_check]['description'] = review.description(urgent_meta)
            old = api.rows[changed_check]
            old_meta = review.parse_description(old['description'])
            old_meta.update(status='not_affected', expires_at=review.PERMANENT_TILL)
            old['description'] = review.description(old_meta)
            old['active_till'] = review.PERMANENT_TILL
            current[0] = two_image_snapshot()
            current[0]['reports'][IMAGE2]['findings'][0]['packages'][0]['fixed'] = '1.2'
            value = controller.tick()
            self.assertTrue(value['healthy'])
            self.assertEqual(len(value['urgent']), 1)
            self.assertEqual(value['urgent'][0]['check_id'], urgent_check)
            self.assertEqual(controller.records[changed_check]['status'], 'pending')
            self.assertLessEqual(api.rows[changed_check]['active_till'], NOW + review.TEMP_SECONDS)
            self.assertIn(changed_check, [item['check_id'] for item in controller.queue()['findings']])

    def test_malformed_record_isolated_from_other_urgent(self):
        api = FakeZabbix()
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', return_value=two_image_snapshot()):
            controller = self.controller(temp, api)
            controller.tick()
            urgent_check = review.raw_check_id(IMAGE, CVE, SERVICE)
            bad_check = review.raw_check_id(IMAGE2, CVE, SERVICE2)
            urgent_meta = review.parse_description(api.rows[urgent_check]['description'])
            urgent_meta.update(status='urgent', reason='The exposed parser is reachable by untrusted clients.',
                               action_summary='Disable the affected upload route now.')
            api.rows[urgent_check]['description'] = review.description(urgent_meta)
            api.rows[bad_check]['description'] = 'invalid controller record'
            value = controller.tick()
            self.assertTrue(value['healthy'])
            self.assertEqual(len(value['urgent']), 1)
            self.assertGreater(value['overdue_count'], 0)
            self.assertNotIn(bad_check, value['ready_check_ids'])

    def test_same_status_new_evidence_adds_one_new_zabbix_note(self):
        api = FakeZabbix()
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', return_value=snapshot()):
            controller = self.controller(temp, api)
            controller.tick()
            row = next(iter(controller.rows.values()))
            check = row['check_id']
            legacy = review.parse_description(api.rows[check]['description'])
            legacy['legacy_backlog'] = True
            api.rows[check]['description'] = review.description(legacy)
            api.events[check] = [{'eventid': '81', 'suppressed': '1', 'acknowledged': '1',
                                  'acknowledges': []}]
            controller.tick()
            self.assertEqual(len(api.events[check][0]['acknowledges']), 1)
            self.assertEqual(api.events[check][0]['acknowledged'], '1')
            self.assertEqual([params['action'] for method, params in api.calls
                              if method == 'event.acknowledge'], [4])
            from datetime import datetime, timezone
            proposal = {key: row[key] for key in ('finding_id', 'image', 'cve', 'service', 'check_id')}
            proposal.update(disposition='requires_fix',
                            reason='The reachable parser remains vulnerable in this deployment; a vendor fix is pending.',
                            evidence_urls=['https://example.org/advisory'],
                            reviewed_at=datetime.fromtimestamp(NOW, timezone.utc).isoformat().replace('+00:00', 'Z'),
                            recheck_on=['vendor_fix'])
            controller.submit_review(proposal)
            self.assertEqual(len(api.events[check][0]['acknowledges']), 2)
            self.assertFalse(controller.records[check]['legacy_backlog'])
            proposal['reason'] += ' Confirmed again with a new vendor advisory.'
            controller.submit_review(proposal)
            self.assertEqual(len(api.events[check][0]['acknowledges']), 3)
            controller.tick()
            self.assertEqual(len(api.events[check][0]['acknowledges']), 3)

    def test_queue_pagination_reaches_later_findings(self):
        api = FakeZabbix()
        value = snapshot()
        value['reports'][IMAGE]['findings'] = [
            {'id': f'CVE-2026-{12000 + index}', 'url': 'https://example.org/advisory', 'packages': []}
            for index in range(26)]
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', return_value=value):
            controller = self.controller(temp, api)
            controller.tick()
            first = controller.queue(limit=20)
            second = controller.queue(limit=20, offset=first['next_offset'])
            self.assertEqual(first['total'], 26)
            self.assertEqual(len(first['findings']), 20)
            self.assertEqual(len(second['findings']), 6)
            self.assertIsNone(second['next_offset'])

    def test_legacy_permanent_respects_review_deadline(self):
        api = FakeZabbix()
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', return_value=snapshot()):
            controller = self.controller(temp, api)
            controller.tick()
            current = next(iter(api.rows.values()))
            meta = review.parse_description(current['description'])
            meta.update(status='not_affected', legacy_revalidation=True,
                        review_by=NOW + 30 * 86400, expires_at=review.PERMANENT_TILL)
            current['description'] = review.description(meta)
            current['active_till'] = review.PERMANENT_TILL
            controller.tick()
            self.assertEqual(controller.queue()['total'], 0)
            self.assertEqual(controller.snapshot_data['overdue_count'], 0)

    def test_legacy_finite_backlog_queues_without_immediate_fault(self):
        api = FakeZabbix()
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', return_value=snapshot()):
            controller = self.controller(temp, api)
            controller.tick()
            current = next(iter(api.rows.values()))
            meta = review.parse_description(current['description'])
            meta.update(status='requires_fix', legacy_backlog=True, review_by=NOW - 60)
            current['description'] = review.description(meta)
            value = controller.tick()
            self.assertEqual(controller.queue()['total'], 1)
            self.assertEqual(value['overdue_count'], 0)
            self.assertTrue(value['healthy'])
            meta['expires_at'] = NOW - 60
            current['description'] = review.description(meta)
            current['active_till'] = NOW - 60
            value = controller.tick()
            self.assertEqual(value['overdue_count'], 1)

    def test_missing_state_does_not_bootstrap_or_mute(self):
        api = FakeZabbix()
        with tempfile.TemporaryDirectory() as temp, patch.object(review, 'bounded_json', return_value=snapshot()):
            controller = review.Controller(api=api, state_path=Path(temp) / 'missing.json', now=lambda: NOW, apply=True)
            self.assertFalse(controller.tick()['healthy'])
            self.assertEqual(api.calls, [])


if __name__ == '__main__':
    unittest.main()
