#!/usr/bin/env python3
"""Exercise live OIDC authorization with temporary ordinary test identities."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('pocket_id_access', ROOT / 'scripts/reconcile-pocket-id-access.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
POLICY = json.loads(module.POLICY_PATH.read_text())


class LiveAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = module.PocketID()
        if not module.reconcile(cls.api, POLICY, False):
            raise RuntimeError('Reconcile policy drift before running authorization tests')
        cls.groups = {group['name']: group['id'] for group in cls.api.listing('/user-groups')}

    def setUp(self):
        username = 'accessaudit' + uuid.uuid4().hex[:12]
        self.user = self.api.api('/users', 'POST', {
            'username': username, 'email': username + '@example.invalid',
            'displayName': 'Temporary access audit', 'firstName': 'Access', 'lastName': 'Audit',
            'isAdmin': False, 'userGroupIds': [],
        })
        self.assertFalse(self.user['isAdmin'])
        self.assertFalse(self.user.get('userGroups'))

    def tearDown(self):
        # Delete only the identity this test created; it has no application data.
        self.api.api('/users/' + self.user['id'], 'DELETE')

    def assert_access(self, groups: set[str]):
        allowed_count = 0
        for identifier, allowed in POLICY.items():
            with self.subTest(client=identifier):
                path = f'/oidc/clients/{identifier}/preview/{self.user["id"]}?scopes=openid%20profile%20email%20groups'
                expected = bool(groups.intersection(allowed))
                try:
                    self.api.api(path)
                except RuntimeError as error:
                    self.assertFalse(expected, f'Expected access to {identifier}: {error}')
                    self.assertIn('HTTP 403', str(error), 'Only explicit access denial counts as a successful negative test')
                else:
                    self.assertTrue(expected, f'Unexpected access to {identifier} with groups {sorted(groups)}')
                    allowed_count += 1
        return allowed_count

    def test_no_groups_denied_by_every_client(self):
        self.assertEqual(self.assert_access(set()), 0)

    def test_kids_allowed_only_photos_portal_media_and_search(self):
        self.api.api('/users/' + self.user['id'] + '/user-groups', 'PUT', {'userGroupIds': [self.groups['kids']]})
        self.assertEqual(self.assert_access({'kids'}), 5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
