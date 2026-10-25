#!/usr/bin/env python3
"""Exercise the restricted security review identity without contacting Zabbix."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parent / 'bootstrap-zabbix.py'
spec = importlib.util.spec_from_file_location('bootstrap_zabbix', MODULE)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.existing_user = False

    def ensure(self, kind, key, value, properties, idfield=None, query=None):
        self.calls.append((kind + '.ensure', value, properties))
        return {'role': '501', 'usergroup': '502', 'user': '503'}[kind]

    def call(self, method, params):
        self.calls.append((method, params))
        if method == 'role.get':
            return [{'roleid': '501', 'rules': {'actions': [
                {'name': name, 'status': '1'} for name in
                ('acknowledge_problems', 'add_problem_comments', 'edit_maintenance',
                 'execute_scripts', 'manage_api_tokens', 'close_problems')]}}]
        if method == 'role.update':
            return {'roleids': ['501']}
        if method == 'user.get':
            return [{'userid': '503'}] if self.existing_user else []
        if method == 'token.create':
            return {'tokenids': ['601']}
        if method == 'token.generate':
            return [{'token': 'generated-api-token'}]
        raise AssertionError(method)


class SecurityReviewIdentityTests(unittest.TestCase):
    def test_secret_create_and_replace_never_store_last_applied_plaintext(self):
        calls = []
        def capture(*args, value=None):
            calls.append((args, json.loads(value)))
        missing = SimpleNamespace(returncode=1, stderr='NotFound', stdout='')
        prior = {'metadata': {'resourceVersion': '17', 'labels': {'owner': 'home107'},
                              'annotations': {'kubectl.kubernetes.io/last-applied-configuration':
                                              'plaintext-old-token', 'safe': 'keep'}}}
        present = SimpleNamespace(returncode=0, stderr='', stdout=json.dumps(prior))
        with patch.object(bootstrap.subprocess, 'run', side_effect=[missing, present]), \
             patch.object(bootstrap, 'kubectl', side_effect=capture):
            bootstrap.write_secret('zabbix', 'security-review-controller', {'baloo-token': 'new-secret'})
            bootstrap.write_secret('zabbix', 'security-review-controller', {'baloo-token': 'new-secret'})
        self.assertEqual(calls[0][0], ('-n', 'zabbix', 'create', '-f', '-'))
        self.assertEqual(calls[1][0], ('-n', 'zabbix', 'replace', '-f', '-'))
        self.assertTrue(all('new-secret' not in str(args) for args, _ in calls))
        self.assertEqual(calls[1][1]['metadata']['annotations'], {'safe': 'keep'})
        self.assertEqual(calls[1][1]['metadata']['labels'], {'owner': 'home107'})
        self.assertNotIn('annotations', calls[0][1]['metadata'])

    def test_writer_has_exact_method_and_action_allowlists(self):
        api = FakeAPI()
        token = bootstrap.configure_security_review_identity(api, '17', {})
        self.assertEqual(token, 'generated-api-token')
        role = next(entry[2] for entry in api.calls if entry[0] == 'role.ensure')
        self.assertEqual(role['type'], 2)
        rules = role['rules']
        self.assertEqual(rules['api.mode'], 1)
        self.assertEqual(rules['api'], ['problem.get', 'host.get', 'maintenance.get',
                                        'event.acknowledge', 'maintenance.create',
                                        'maintenance.update'])
        self.assertNotIn('user.update', rules['api'])
        self.assertNotIn('script.execute', rules['api'])
        self.assertNotIn('maintenance.delete', rules['api'])
        self.assertEqual({a['name'] for a in rules['actions']}, {
            'add_problem_comments', 'acknowledge_problems', 'edit_maintenance',
        })
        action_update = next(call[1]['rules'] for call in api.calls if call[0] == 'role.update')
        self.assertEqual(action_update['actions.default_access'], 0)
        self.assertEqual({a['name']: a['status'] for a in action_update['actions']}, {
            'acknowledge_problems': 1, 'add_problem_comments': 1,
            'edit_maintenance': 1, 'execute_scripts': 0,
            'manage_api_tokens': 0, 'close_problems': 0,
        })
        group = next(entry[2] for entry in api.calls if entry[0] == 'usergroup.ensure')
        self.assertEqual(group['hostgroup_rights'], [{'id': '17', 'permission': 3}])

    def test_existing_api_token_and_transport_secrets_are_reused(self):
        api = FakeAPI()
        api.existing_user = True
        values = {
            ('zabbix', 'security-review-reconciler'): {'api-token': 'existing-api'},
            ('zabbix', 'security-review-controller'): {
                'baloo-token': 'existing-baloo', 'collector-token': 'existing-collector',
            },
            ('baloo', 'security-review-access'): {'token': 'existing-baloo'},
        }
        writes = []
        with patch.object(bootstrap, 'read_secret', side_effect=lambda *key: values.get(key)), \
             patch.object(bootstrap, 'write_secret', side_effect=lambda *args: writes.append(args)):
            bootstrap.configure_security_review_access(api, '17')
        self.assertEqual(writes, [])
        self.assertFalse(any(call[0].startswith('token.') for call in api.calls))

    def test_fresh_transport_token_is_mirrored_only_to_baloo_side(self):
        api = FakeAPI()
        values = {}
        writes = []

        def save(namespace, name, data):
            writes.append((namespace, name, data))
            values[(namespace, name)] = data

        with patch.object(bootstrap, 'read_secret', side_effect=lambda *key: values.get(key)), \
             patch.object(bootstrap, 'write_secret', side_effect=save), \
             patch.object(bootstrap.secrets, 'token_urlsafe', side_effect=['password', 'baloo-secret', 'collector-secret']):
            bootstrap.configure_security_review_access(api, '17')
        self.assertEqual(values[('zabbix', 'security-review-reconciler')], {'api-token': 'generated-api-token'})
        self.assertEqual(values[('zabbix', 'security-review-controller')], {
            'baloo-token': 'baloo-secret', 'collector-token': 'collector-secret',
        })
        self.assertEqual(values[('baloo', 'security-review-access')], {'token': 'baloo-secret'})
        self.assertEqual(len(writes), 3)
        self.assertNotIn('generated-api-token', str(values[('baloo', 'security-review-access')]))


if __name__ == '__main__':
    unittest.main()
