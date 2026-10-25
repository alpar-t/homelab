#!/usr/bin/env python3
"""Verify fixed-deadline, exact-scope and idempotent finite review extension."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parent / 'extend-migrated-security-reviews.py'
spec = importlib.util.spec_from_file_location('extend_migrated_security_reviews', MODULE)
extension = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extension)
migration = extension.migration
NOW = int(time.time()) // 60 * 60
IMAGE = 'docker.io/example/app@sha256:' + 'a' * 64
SERVICES = ['apps/Deployment/one/main', 'apps/Deployment/two/main']


def fixture():
    source = {'schema': 1, 'generated_at': NOW - 3600, 'hostid': '10', 'entries': []}
    rows = []
    for index, service in enumerate(SERVICES):
        cve = f'CVE-2026-{10000 + index}'
        check = migration.new_check_id(IMAGE, cve, service)
        expiry = NOW + (index + 1) * 86400 + 7
        source['entries'].append({'new_check_id': check, 'image': IMAGE,
                                  'cve': cve, 'service': service,
                                  'active_till': expiry, 'status': 'config'})
        meta = {'schema': 2, 'image': IMAGE, 'cve': cve, 'service': service,
                'check_id': check, 'finding_id': migration.finding_id(IMAGE, cve, service),
                'status': 'config', 'reason': 'Legacy evidence still under review',
                'review_by': NOW, 'expires_at': expiry,
                'legacy_eventid': str(index + 10)}
        rows.append({'maintenanceid': str(index + 90),
                     'name': f'HOME107v2 CONFIG {cve} {check}',
                     'description': 'CONFIG review\nHOME107V2:' + json.dumps(meta),
                     'active_since': NOW - 48 * 3600,
                     'active_till': expiry // 60 * 60,
                     'maintenance_type': '0',
                     'tags': [{'tag': 'check_id', 'operator': '0', 'value': check}],
                     'hosts': [{'hostid': '10'}],
                     'timeperiods': [{'timeperiod_type': '2', 'every': '1',
                                      'start_time': '0', 'period': '86400'}]})
    source['entries'].append({'new_check_id': migration.new_check_id(IMAGE, 'CVE-2026-19999',
                                                                     SERVICES[0]),
                              'image': IMAGE, 'cve': 'CVE-2026-19999',
                              'service': SERVICES[0], 'active_till': NOW + 365 * 86400,
                              'status': 'not_affected'})
    return source, rows


class ExtensionTests(unittest.TestCase):
    def test_fixed_deadline_preserves_original_expiry_and_review_fields(self):
        source, rows = fixture()
        original_meta = extension.metadata(rows[0])
        original_meta['reviewed_at'] = '2026-10-25T08:00:00Z'
        original_meta['reason'] = 'Fresh finite review evidence'
        rows[0]['description'] = 'CONFIG review\nHOME107V2:' + json.dumps(original_meta)
        result = extension.plan(source, 'source-hash', rows, '10', NOW)
        self.assertEqual(len(result['targets']), 2)
        self.assertEqual(result['fixed_deadline'], source['generated_at'] + 30 * 86400)
        self.assertEqual(result['skipped'], [])
        target = result['targets'][0]
        meta = json.loads(target['target_description'].split('HOME107V2:', 1)[1])
        self.assertEqual(meta['legacy_original_expiry'], source['entries'][0]['active_till'])
        self.assertEqual(meta['expires_at'], result['fixed_deadline'])
        self.assertEqual(meta['review_by'], NOW)
        self.assertEqual(meta['reason'], 'Fresh finite review evidence')
        self.assertEqual(meta['reviewed_at'], '2026-10-25T08:00:00Z')
        self.assertIn('Legacy original mute expiry:', target['target_description'])

    def test_never_updates_current_permanent_or_wrong_host(self):
        source, rows = fixture()
        meta = extension.metadata(rows[0])
        meta['status'] = 'not_affected'
        rows[0]['name'] = rows[0]['name'].replace('CONFIG', 'NOT_AFFECTED')
        rows[0]['description'] = 'Permanent review\nHOME107V2:' + json.dumps(meta)
        result = extension.plan(source, 'source-hash', rows, '10', NOW)
        self.assertEqual(len(result['targets']), 1)
        self.assertEqual(result['skipped'][0]['reason'], 'non_finite_current_status')
        rows[1]['hosts'] = [{'hostid': '11'}]
        with self.assertRaisesRegex(ValueError, 'missing or invalid'):
            extension.plan(source, 'source-hash', rows, '10', NOW)

    def test_bounded_apply_is_idempotent_and_reads_back(self):
        source, rows = fixture()
        source_bytes = json.dumps(source).encode()
        saved = extension.plan(source, hashlib.sha256(source_bytes).hexdigest(), rows, '10', NOW)
        class FakeAPI:
            def __init__(self):
                self.writes = []
            def call(self, method, params):
                if method == 'maintenance.get':
                    return [row.copy() for row in rows
                            if row['maintenanceid'] in params['maintenanceids']]
                if method == 'maintenance.update':
                    self.writes.append(params['maintenanceid'])
                    row = next(x for x in rows if x['maintenanceid'] == params['maintenanceid'])
                    row['active_till'] = params['active_till'] // 60 * 60
                    row['description'] = params['description']
                    return {'maintenanceids': [params['maintenanceid']]}
                raise AssertionError(method)
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(extension, 'live', return_value=('10', [], rows)):
            path = Path(directory) / 'extension-plan.json'
            first = extension.apply(saved, source_bytes, api, path, 1)
            self.assertEqual(first['updated_this_run'], 1)
            self.assertEqual(first['remaining'], 1)
            second = extension.apply(saved, source_bytes, api, path, 1)
            self.assertEqual(second['updated_this_run'], 1)
            self.assertEqual(second['remaining'], 0)
            third = extension.apply(saved, source_bytes, api, path, 1)
            self.assertEqual(third['updated_this_run'], 0)
            self.assertEqual(len(api.writes), 2)
            self.assertEqual(len(json.loads(path.with_suffix('.progress.json').read_text())['updated']), 2)


if __name__ == '__main__':
    unittest.main()
