#!/usr/bin/env python3
"""Verify default-deny service onboarding and the explicit group access policy."""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
GROUPS = json.loads((ROOT / 'config/pocket-id/access-policy.json').read_text())
SERVICES = json.loads((ROOT / 'config/pocket-id/service-access-policy.json').read_text())
# Existing public or independently authenticated endpoints require explicit review.
EXCEPTIONS = {
    'public': {'newjoy.ro', 'www.newjoy.ro', 'auth.newjoy.ro'},
    'separate-account': {'vault.newjoy.ro', 'mail.newjoy.ro'},
    'document-token': {'office.newjoy.ro', 'wopi.newjoy.ro'},
    'redirect': {'dashboard.newjoy.ro'},
}


def validate_proxy(container: dict, expected: set[str]) -> None:
    args = container.get('args', [])
    allowed = {arg.split('=', 1)[1] for arg in args if arg.startswith('--allowed-group=')}
    assert allowed and allowed == expected, f'Proxy has missing or incorrect groups: {allowed} != {expected}'
    assert '--provider=oidc' in args, 'Group-restricted proxies must use the audited OIDC provider'
    assert '--oidc-groups-claim=groups' in args, 'Proxy must read the groups claim'
    scopes = [arg.split('=', 1)[1].split() for arg in args if arg.startswith('--scope=')]
    assert len(scopes) == 1 and 'groups' in scopes[0], 'Proxy must request the groups scope'
    assert not any(arg.startswith('--skip-auth-regex') or arg.startswith('--skip-jwt-bearer-tokens=true')
                   for arg in args), 'Review authentication bypass options explicitly'


def validate_ingress(ingress: dict) -> None:
    annotations = ingress.get('metadata', {}).get('annotations', {})
    namespace = ingress['metadata'].get('namespace', 'default')
    for rule in ingress['spec'].get('rules', []):
        host = rule['host']
        assert host in SERVICES, f'New ingress {host} needs an explicit access policy'
        policy = SERVICES[host]
        mode = policy['mode']
        if mode in EXCEPTIONS:
            assert host in EXCEPTIONS[mode], f'Review a new authentication exception: {host}'
            if mode == 'redirect':
                assert annotations.get('nginx.ingress.kubernetes.io/permanent-redirect') == 'https://portal.newjoy.ro/', 'Legacy dashboard must redirect to the protected portal'
                assert annotations.get('nginx.ingress.kubernetes.io/permanent-redirect-code') == '308'
            continue
        assert policy['client'] in GROUPS and GROUPS[policy['client']], f'{host} needs allowed groups'
        if mode == 'oidc':
            continue  # Native OIDC clients are verified by the live policy audit.
        assert mode == 'proxy', f'Unknown authentication mode for {host}'
        proxy = policy['service']
        proxy_namespace = policy['namespace']
        for path in rule.get('http', {}).get('paths', []):
            backend = path['backend']['service']['name']
            if backend == proxy and namespace == proxy_namespace:
                continue
            expected = f'http://{proxy}.{proxy_namespace}.svc.cluster.local:4180/oauth2/auth'
            assert annotations.get('nginx.ingress.kubernetes.io/auth-url') == expected, f'{host} bypasses its group proxy'
            assert annotations.get('nginx.ingress.kubernetes.io/auth-signin'), f'{host} needs a sign-in redirect'


def validate_helm_values(values: dict) -> None:
    def walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    enabled = [node['ingress'] for node in walk(values)
               if isinstance(node.get('ingress'), dict) and node['ingress'].get('enabled')]
    for ingress in enabled:
        hosts = set()
        for node in walk(ingress):
            for key in ('host', 'hosts', 'hostname', 'domain', 'domains'):
                candidates = node.get(key, [])
                candidates = [candidates] if isinstance(candidates, str) else candidates
                if isinstance(candidates, list):
                    hosts.update(host for host in candidates if isinstance(host, str) and host)
        domains = values.get('global', {}).get('domain', {})
        if isinstance(domains, dict):
            hosts.update(host for host in domains.values() if isinstance(host, str) and host)
        assert hosts, 'Enabled Helm ingress needs explicit audited hosts; review custom chart layouts'
        for host in hosts:
            assert host in SERVICES, f'Helm ingress {host} needs an access policy'


class AccessPolicyTests(unittest.TestCase):
    def test_all_client_policies_have_named_groups(self):
        known = {'family_users', 'advanced_apps', 'kids', 'opencloud_admin', 'opencloud_users_', 'trek-admins'}
        for identifier, groups in GROUPS.items():
            with self.subTest(client=identifier):
                self.assertTrue(groups)
                self.assertEqual(len(groups), len(set(groups)))
                self.assertLessEqual(set(groups), known)
        kids_clients = {identifier for identifier, groups in GROUPS.items() if 'kids' in groups}
        self.assertEqual(kids_clients, {'portal', '30ba5ebe-f059-4c30-b37f-6e97b75c37b9',
                                       'e822cb49-40e6-410e-951a-d28206398a9d',
                                       '33064a51-cb32-4d2f-b5cf-a2d37682c529'})

    def test_all_declared_services_have_a_policy(self):
        for host, policy in SERVICES.items():
            if policy['mode'] in EXCEPTIONS:
                self.assertIn(host, EXCEPTIONS[policy['mode']])
            else:
                self.assertIn(policy['mode'], {'proxy', 'oidc'})
                self.assertIn(policy['client'], GROUPS)

    def test_manifests_require_access_groups(self):
        proxies = {}
        ingresses = []
        paths = (sorted((ROOT / 'config').glob('*/manifests/*.yaml'))
                 + sorted((ROOT / 'config').glob('*/values.yaml')) + sorted((ROOT / 'apps').glob('*.yaml')))
        for path in paths:
            for document in yaml.safe_load_all(path.read_text()):
                if not isinstance(document, dict):
                    continue
                kind = document.get('kind')
                if not kind:
                    validate_helm_values(document)
                if kind == 'Application':
                    sources = document['spec'].get('sources', [document['spec'].get('source', {})])
                    for source in sources:
                        helm = source.get('helm', {})
                        validate_helm_values(helm.get('valuesObject', {}))
                        if helm.get('values'):
                            validate_helm_values(yaml.safe_load(helm['values']))
                if kind == 'Ingress':
                    with self.subTest(path=str(path), ingress=document['metadata']['name']):
                        validate_ingress(document)
                        ingresses.append(document)
                spec = document.get('spec', {})
                if kind == 'CronJob':
                    spec = spec['jobTemplate']['spec']
                pod = spec.get('template', {}).get('spec', {})
                for container in pod.get('containers', []) + pod.get('initContainers', []):
                    if 'oauth2-proxy' in container.get('image', ''):
                        key = (document['metadata'].get('namespace', 'default'), document['metadata']['name'])
                        expected = {frozenset(GROUPS[p['client']]) for p in SERVICES.values()
                                    if p['mode'] == 'proxy' and (p['namespace'], p['service']) == key}
                        self.assertEqual(len(expected), 1, f'{path}: new proxy needs a service/group policy')
                        validate_proxy(container, set(next(iter(expected))))
                        proxies[key] = container
                    if '/scripts/provision.sh' in container.get('command', []):
                        env = {item['name']: item.get('value') for item in container.get('env', [])}
                        self.assertIn(env.get('APP_NAME'), GROUPS, f'{path}: new OIDC service needs an explicit group policy')
        expected_proxies = {(p['namespace'], p['service']) for p in SERVICES.values() if p['mode'] == 'proxy'}
        self.assertEqual(set(proxies), expected_proxies)
        self.assertGreater(len(ingresses), 15)

    def test_provisioner_creates_clients_with_access_denied(self):
        documents = list(yaml.safe_load_all((ROOT / 'config/pocket-id/manifests/oidc-provisioner.yaml').read_text()))
        script = next(doc['data']['provision.sh'] for doc in documents if doc.get('kind') == 'ConfigMap')
        body = re.search(r'-d "(\{.*?\})"\s*\\\s*https://auth\.newjoy\.ro/api/oidc/clients', script, re.S)
        self.assertIsNotNone(body, 'Review changes to the client-creation request format')
        payload = json.loads(body.group(1).replace('\\"', '"'))
        self.assertIs(payload.get('isGroupRestricted'), True)
        self.assertFalse(payload.get('allowedUserGroups'), 'New clients must deny sign-in until deliberately granted access')

    def test_kids_catalog_contains_only_selected_services(self):
        catalog = json.loads((ROOT / 'config/portal/manifests/assets/catalog/kids.json').read_text())
        products = {service['product'] for section in catalog['sections'] for service in section['services']}
        self.assertEqual(products, {'Immich', 'Emby', 'Radarr', 'Sonarr', 'Vaultwarden · Bitwarden apps', 'Pocket ID'})

    def test_future_proxy_without_groups_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'missing or incorrect groups'):
            validate_proxy({'args': ['--provider=oidc', '--scope=openid email profile']}, {'family_users'})

    def test_future_unclassified_ingress_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'needs an explicit access policy'):
            validate_ingress({'metadata': {}, 'spec': {'rules': [{'host': 'future.newjoy.ro'}]}})

    def test_existing_proxy_cannot_be_removed_from_a_route(self):
        ingress = {'metadata': {'namespace': 'media'}, 'spec': {'rules': [{
            'host': 'radarr.newjoy.ro', 'http': {'paths': [{'backend': {'service': {'name': 'arr-stack'}}}]}
        }]}}
        with self.assertRaisesRegex(AssertionError, 'bypasses its group proxy'):
            validate_ingress(ingress)

    def test_future_helm_ingress_needs_a_policy(self):
        with self.assertRaisesRegex(AssertionError, 'needs an access policy'):
            validate_helm_values({'ingress': {'enabled': True, 'hosts': ['future.newjoy.ro']}})

    def test_daily_audit_reads_full_client_details(self):
        documents = list(yaml.safe_load_all((ROOT / 'config/pocket-id/manifests/access-check.yaml').read_text()))
        source = documents[0]['data']['check.js']
        # List responses omit group memberships in the deployed version. The
        # full DTO must govern both successful checks and restriction failures.
        harness = r'''
const vm = require("node:vm");
(async () => {
  for (const restricted of [true, false]) {
    const messages = [];
    const process = {env: {POCKET_ID_API_KEY: "test-fixture"}, exitCode: 0};
    let detailReads = 0;
    const fetch = async url => {
      if (url.includes("?")) return {ok: true, json: async () => ({
        data: [{id: "future-service", name: "Future service"}], pagination: {totalPages: 1}
      })};
      detailReads++;
      return {ok: true, json: async () => ({isGroupRestricted: restricted, allowedUserGroups: [{id: "family"}]})};
    };
    vm.runInNewContext(SOURCE, {fetch, process, URLSearchParams, AbortSignal,
      console: {log: message => messages.push(message), error: message => messages.push(message)}});
    await new Promise(setImmediate);
    if (detailReads !== 1 || process.exitCode !== (restricted ? 0 : 1)) {
      throw new Error(`Unexpected audit behavior: ${detailReads}, ${process.exitCode}, ${messages}`);
    }
  }
})();
'''
        subprocess.run(['node'], input=('const SOURCE = ' + json.dumps(source) + ';\n' + harness).encode(), check=True)

    def test_legacy_dashboard_cannot_lose_its_redirect(self):
        with self.assertRaisesRegex(AssertionError, 'must redirect'):
            validate_ingress({'metadata': {}, 'spec': {'rules': [{'host': 'dashboard.newjoy.ro'}]}})


if __name__ == '__main__':
    unittest.main(verbosity=2)
