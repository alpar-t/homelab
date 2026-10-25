#!/usr/bin/env python3
"""Check exact identity and expiry preservation in the one-time review migration."""
import importlib.util
import json
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parent / 'migrate-security-reviews.py'
spec = importlib.util.spec_from_file_location('migrate_security_reviews', MODULE)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)

NOW = 1_800_000_000
IMAGE = 'docker.io/example/service@sha256:' + 'a' * 64
CVE = 'CVE-2026-6653'
CONSUMERS = ['alpha/Deployment/one/main', 'beta/CronJob/two/worker']


def fixture(note, expiry, *, permanent=False):
    old = migration.legacy_check_id(IMAGE, CVE)
    snapshot = {
        'inventory_at': NOW - 5, 'inventory_error': '', 'errors': {},
        'images': {IMAGE: CONSUMERS},
        'reports': {IMAGE: {'scanned_at': NOW - 10, 'findings': [{
            'id': CVE, 'url': 'https://example.org/advisory',
            'packages': [{'name': 'libxml2', 'installed': '1', 'fixed': ''}],
        }]}},
        'consumer_fingerprints': {IMAGE: {CONSUMERS[0]: 'fingerprint-one'}},
    }
    event = {'eventid': '77', 'name': 'Critical ' + CVE + ' service@' + 'a' * 12,
             'tags': [{'tag': 'check_id', 'value': old}],
             'acknowledges': [{'clock': str(NOW - 100), 'message': note}],
             'suppression_data': [{'maintenanceid': '0', 'suppress_until': str(expiry)}]}
    maintenance = {'maintenanceid': '19', 'name':
                   ('REVIEWED_NOT_AFFECTED' if permanent else 'REVIEWED_CONFIG_30D'),
                   'description': f'{note}; image={IMAGE}; cve={CVE}',
                   'active_till': str(expiry), 'tags': [{'tag': 'check_id', 'value': old}],
                   'hosts': [{'hostid': '10'}]}
    return snapshot, [event], [maintenance], old


class MigrationTests(unittest.TestCase):
    def test_per_service_ids_and_finite_expiry_are_preserved(self):
        expires = NOW + 8 * 86400
        note = ('REVIEWED_CONFIG_30D | CVE-2026-6653; reason=XML feature enabled; '
                'evidence=https://example.org/review; review_trigger=config changes')
        snapshot, events, maintenances, old = fixture(note, expires)
        result = migration.plan(snapshot, events, maintenances, '10', NOW, set())
        self.assertEqual(len(result['entries']), 2)
        self.assertEqual(result['unmatched'], [])
        self.assertEqual({entry['active_till'] for entry in result['entries']}, {expires})
        self.assertEqual({entry['status'] for entry in result['entries']}, {'config'})
        self.assertEqual({entry['new_check_id'] for entry in result['entries']}, {
            migration.new_check_id(IMAGE, CVE, service) for service in CONSUMERS
        })
        self.assertEqual({entry['legacy_check_id'] for entry in result['entries']}, {old})
        first = json.loads(result['entries'][0]['description'].split('HOME107V2:', 1)[1])
        self.assertEqual(first['schema'], 2)
        self.assertEqual(first['finding_id'], migration.finding_id(IMAGE, CVE, CONSUMERS[0]))
        self.assertEqual(first['fingerprint'], 'fingerprint-one')
        self.assertEqual(first['review_by'], NOW)
        self.assertTrue(first['legacy_backlog'])
        self.assertEqual(first['recheck_on'], ['image_digest_change', 'service_config_change', '30_days'])

    def test_permanent_requires_explicit_approval_and_exact_evidence(self):
        expires = NOW + 400 * 86400
        note = ('REVIEWED_NOT_AFFECTED | CVE-2026-6653; reason=affected binary absent; '
                'evidence=https://example.org/source; review_trigger=image changes')
        snapshot, events, maintenances, old = fixture(note, expires, permanent=True)
        blocked = migration.plan(snapshot, events, maintenances, '10', NOW, set())
        self.assertEqual(blocked['entries'], [])
        self.assertEqual(blocked['unmatched'][0]['reason'], 'permanent evidence needs explicit approval')
        approved = migration.plan(snapshot, events, maintenances, '10', NOW, {old})
        self.assertEqual(len(approved['entries']), 2)
        self.assertEqual({e['status'] for e in approved['entries']}, {'not_affected'})
        self.assertEqual({e['active_till'] for e in approved['entries']}, {expires})
        first = json.loads(approved['entries'][0]['description'].split('HOME107V2:', 1)[1])
        self.assertEqual(first['recheck_on'], ['image_digest_change', 'advisory_change'])
        self.assertEqual(first['review_by'], NOW + 30 * 86400)
        self.assertTrue(first['legacy_revalidation'])
        self.assertNotIn('legacy_backlog', first)
        self.assertNotIn('reviewed_at', first)
        self.assertEqual(first['packages'], snapshot['reports'][IMAGE]['findings'][0]['packages'])
        self.assertEqual(first['scanner_url'], 'https://example.org/advisory')

    def test_expired_or_unrelated_suppression_cannot_extend_finite_review(self):
        note = 'REVIEWED_REQUIRES_FIX | CVE-2026-6653; reason=reachable XML path'
        snapshot, events, maintenances, _ = fixture(note, NOW - 1)
        events[0]['suppression_data'].append({'maintenanceid': '999', 'suppress_until': str(NOW + 20 * 86400)})
        result = migration.plan(snapshot, events, maintenances, '10', NOW, set())
        self.assertEqual(result['entries'], [])
        self.assertEqual(result['unmatched'][0]['reason'], 'no live finite expiry to preserve')

    def test_intrinsic_note_without_permanent_record_preserves_finite_mute(self):
        note = ('REVIEWED_NOT_AFFECTED | CVE-2026-6653; reason=affected binary absent; '
                'evidence=https://example.org/source')
        expires = NOW + 12 * 86400
        snapshot, events, maintenances, _ = fixture(note, expires)
        maintenances[0]['name'] = 'PENDING_REVIEW_30D'
        result = migration.plan(snapshot, events, maintenances, '10', NOW, set())
        self.assertEqual(len(result['entries']), 2)
        self.assertEqual({entry['status'] for entry in result['entries']}, {'needs_evidence'})
        self.assertEqual({entry['active_till'] for entry in result['entries']}, {expires})
        meta = json.loads(result['entries'][0]['description'].split('HOME107V2:', 1)[1])
        self.assertTrue(meta['legacy_reviewed'])
        self.assertEqual(meta['legacy_disposition'], 'not_affected')
        self.assertEqual(meta['review_by'], NOW)
        self.assertTrue(meta['legacy_backlog'])
        self.assertFalse(result['permanent_candidates'][0]['legacy_maintenance_ids'])

    def test_stale_scanner_report_blocks_migration(self):
        snapshot, events, maintenances, _ = fixture('REVIEWED_CONFIG_30D', NOW + 86400)
        snapshot['reports'][IMAGE]['scanned_at'] = NOW - 9 * 3600
        with self.assertRaisesRegex(ValueError, 'stale report'):
            migration.plan(snapshot, events, maintenances, '10', NOW, set())

    def test_cutover_audit_requires_exact_suppression_maintenance(self):
        snapshot, events, maintenances, _ = fixture('REVIEWED_CONFIG_30D', NOW + 86407)
        result = migration.plan(snapshot, events, maintenances, '10', NOW, set())
        entry = result['entries'][0]
        check = entry['new_check_id']
        mid = '91'
        exact = {'maintenanceid': mid,
                 'name': f'HOME107v2 CONFIG {CVE} {check}',
                 'description': entry['description'],
                 'active_till': entry['active_till'] // 60 * 60,
                 'active_since': NOW - 48 * 3600, 'maintenance_type': '0',
                 'timeperiods': [{'timeperiod_type': '2', 'every': '1',
                                  'start_time': '0', 'period': '86400'}],
                 'tags': [{'tag': 'check_id', 'operator': '0', 'value': check}],
                 'hosts': [{'hostid': '10'}]}
        self.assertEqual(migration.exact_existing([exact], '10', entry, NOW), mid)
        new_event = {'eventid': '99', 'suppressed': '1',
                     'tags': [{'tag': 'check_id', 'value': check}],
                     'suppression_data': [{'maintenanceid': mid,
                                           'suppress_until': NOW + 3600}]}
        partial = migration.audit_cutover(result, [new_event], [exact], NOW)
        self.assertEqual(partial['verified'], 1)
        self.assertEqual(len(partial['wrong_or_missing_maintenance']), 1)
        new_event['suppression_data'][0]['maintenanceid'] = '999'
        bad = migration.audit_cutover(result, [new_event], [exact], NOW)
        self.assertEqual(bad['verified'], 0)
        self.assertIn(check, bad['wrong_or_missing_maintenance'])

    def test_cutover_accepts_fresh_review_of_same_exact_finding(self):
        snapshot, events, maintenances, _ = fixture('REVIEWED_CONFIG_30D', NOW + 86407)
        result = migration.plan(snapshot, events, maintenances, '10', NOW, set())
        entry = result['entries'][0]
        meta = json.loads(entry['description'].split('HOME107V2:', 1)[1])
        meta['status'] = 'not_affected'
        meta['reason'] = 'Fresh direct evidence confirms the path is absent.'
        meta['reviewed_at'] = '2027-01-15T08:00:00Z'
        check = entry['new_check_id']
        row = {'maintenanceid': '91', 'name': f'HOME107v2 NOT_AFFECTED {CVE} {check}',
               'description': 'New review\nHOME107V2:' + json.dumps(meta),
               'active_till': entry['active_till'] // 60 * 60,
               'active_since': NOW - 48 * 3600, 'maintenance_type': '0',
               'timeperiods': [{'timeperiod_type': '2', 'every': '1',
                                'start_time': '0', 'period': '86400'}],
               'tags': [{'tag': 'check_id', 'operator': '0', 'value': check}],
               'hosts': [{'hostid': '10'}]}
        with self.assertRaisesRegex(ValueError, 'differs from approved plan'):
            migration.exact_existing([row], '10', entry, NOW)
        self.assertEqual(migration.reviewed_existing([row], '10', entry, NOW), '91')
        meta['service'] = 'other/Deployment/name/container'
        row['description'] = 'Tampered\nHOME107V2:' + json.dumps(meta)
        self.assertIsNone(migration.reviewed_existing([row], '10', entry, NOW))

    def test_daily_midnight_period_needs_backdated_active_since(self):
        snapshot, events, maintenances, _ = fixture('REVIEWED_CONFIG_30D', NOW + 86400)
        entry = migration.plan(snapshot, events, maintenances, '10', NOW, set())['entries'][0]
        class FakeAPI:
            def call(self, method, params):
                self.method, self.params = method, params
                return {'maintenanceids': ['91']}
        api = FakeAPI()
        self.assertEqual(migration.create_maintenance(api, '10', entry, NOW + 3600), '91')
        self.assertEqual(api.params['active_since'], NOW + 3600 - 48 * 3600)
        row = {**api.params, 'maintenanceid': '91'}
        self.assertTrue(migration.safe_daily_period(row, NOW + 3600))
        row['active_since'] = NOW + 3600
        self.assertFalse(migration.safe_daily_period(row, NOW + 3600))


if __name__ == '__main__':
    unittest.main()
