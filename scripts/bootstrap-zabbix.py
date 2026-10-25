#!/usr/bin/env python3
"""Reconcile HOME-3 monitoring, API roles, and tokens without printing secrets.

Run against a private kubectl port-forward after deploying config/zabbix.
This changes only integration-owned objects, except initial Admin password setup.
"""
import argparse
import base64
import json
from pathlib import Path
import secrets
import subprocess
import time
import urllib.request

READ = ['problem.get', 'event.get', 'host.get', 'trigger.get', 'item.get', 'history.get', 'maintenance.get']
WRITE = ['event.acknowledge', 'maintenance.create', 'maintenance.delete']
REVIEW_READ = ['problem.get', 'event.get', 'host.get', 'trigger.get', 'item.get', 'maintenance.get']
REVIEW_WRITE = ['event.acknowledge', 'maintenance.create', 'maintenance.update', 'maintenance.delete']


def kubectl(*args, value=None):
    result = subprocess.run(['kubectl', *args], input=value, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def read_secret(namespace, name):
    result = subprocess.run(['kubectl', '-n', namespace, 'get', 'secret', name, '-o', 'json'],
                            capture_output=True, text=True)
    if result.returncode:
        if 'NotFound' in result.stderr:
            return None
        raise RuntimeError(result.stderr.strip())
    return {k: base64.b64decode(v).decode() for k, v in json.loads(result.stdout).get('data', {}).items()}


def write_secret(namespace, name, values):
    # Create/replace avoids kubectl apply's last-applied annotation, which would
    # copy plaintext stringData into Secret metadata. Payload stays on stdin.
    result = subprocess.run(['kubectl', '-n', namespace, 'get', 'secret', name, '-o', 'json'],
                            capture_output=True, text=True)
    if result.returncode and 'NotFound' not in result.stderr:
        raise RuntimeError(result.stderr.strip())
    existing = json.loads(result.stdout) if not result.returncode else None
    metadata = {'name': name, 'namespace': namespace}
    if existing:
        prior = existing.get('metadata') or {}
        metadata['resourceVersion'] = prior['resourceVersion']
        if prior.get('labels'):
            metadata['labels'] = prior['labels']
        annotations = {key: value for key, value in (prior.get('annotations') or {}).items()
                       if key != 'kubectl.kubernetes.io/last-applied-configuration'}
        if annotations:
            metadata['annotations'] = annotations
    resource = {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
                'metadata': metadata,
                'stringData': values}
    kubectl('-n', namespace, 'replace' if existing else 'create', '-f', '-',
            value=json.dumps(resource))


class API:
    def __init__(self, url):
        self.url, self.token = url.rstrip('/') + '/api_jsonrpc.php', None

    def call(self, method, params):
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        request = urllib.request.Request(self.url, headers=headers, data=json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode())
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.load(response)
        if 'error' in value:
            # Never echo input parameters, which can contain credentials.
            raise RuntimeError(method + ': ' + str(value['error'].get('data', value['error']['message'])))
        return value['result']

    def ensure(self, kind, key, value, properties, idfield=None, query=None):
        idfield = idfield or kind + 'id'
        found = self.call(kind + '.get', query or {'filter': {key: value}, 'output': [idfield]})
        if len(found) > 1:
            raise RuntimeError('Ambiguous integration object: ' + value)
        if found:
            immutable = {'item': ['hostid'], 'itemprototype': ['hostid', 'ruleid'],
                         'discoveryrule': ['hostid'], 'action': ['eventsource']}.get(kind, [])
            updated = {key: value for key, value in properties.items() if key not in immutable}
            self.call(kind + '.update', {idfield: found[0][idfield], **updated})
            return found[0][idfield]
        result = self.call(kind + '.create', {key: value, **properties})
        return result[idfield + 's'][0]


def sample_gate(key, macro, windows):
    # Zabbix 7.0 accepts an LLD macro in a period parameter at prototype creation
    # but rejects a quoted "#N" after discovery. Use literal sample windows and
    # let the discovery macro select a branch instead.
    return '(' + ' or '.join(
        f'({macro}={n} and count(/HomePBP/{key}[{{#ID}}],#{n})={n}'
        f' and min(/HomePBP/{key}[{{#ID}}],#{n})=1)'
        for n in sorted(set(windows))) + ')'


def configure_checks(api):
    policy = json.loads((Path(__file__).resolve().parents[1] / 'config/zabbix/manifests/assets/policy.json').read_text())
    grace = policy.get('reboot_grace', {'service_samples': 10, 'replica_samples': 30})
    windows = [1, grace['service_samples'], grace['replica_samples']]
    if any(type(n) is not int or n < 1 or n > 120 for n in windows):
        raise ValueError('Reboot grace must be 1–120 samples')
    group = api.ensure('hostgroup', 'name', 'HomePBP', {}, 'groupid')
    host = api.ensure('host', 'host', 'HomePBP', {'name': 'HomePBP', 'groups': [{'groupid': group}],
                      'tags': [{'tag': 'managed_by', 'value': 'HOME-3'}], 'status': 0})
    master = api.ensure('item', 'key_', 'homelab.snapshot', {
        'hostid': host, 'name': 'Homelab snapshot', 'type': 19, 'value_type': 4,
        'url': 'http://collector.zabbix.svc/snapshot', 'delay': '60s', 'timeout': '30s',
        'history': '1d', 'trends': '0', 'status_codes': '200',
    }, query={'hostids': [host], 'filter': {'key_': 'homelab.snapshot'}, 'output': ['itemid']})
    discovery = api.ensure('discoveryrule', 'key_', 'homelab.discovery', {
        'hostid': host, 'name': 'Homelab checks', 'type': 18, 'master_itemid': master, 'delay': '0',
        'lifetime': '1d', 'enabled_lifetime_type': 2,
        'preprocessing': [{'type': 12, 'params': '$.checks', 'error_handler': 0}],
        'lld_macro_paths': [{'lld_macro': '{#' + macro + '}', 'path': '$.' + field} for macro, field in
                            [('ID', 'id'), ('NAME', 'name'), ('FAMILY', 'family'),
                             ('NOTIFY_DELAY', 'notify_delay'), ('GRACE_SAMPLES', 'grace_samples'),
                             ('FAILURE_SAMPLES', 'failure_samples'), ('NOTIFICATION', 'notification')]],
    }, 'itemid', query={'hostids': [host], 'filter': {'key_': 'homelab.discovery'}, 'output': ['itemid']})
    for suffix, field, value_type, history in [('state', 'status', 3, '7d'), ('detail', 'detail', 4, '3d'),
                                              ('severity', 'severity', 3, '1d'),
                                              ('parent_available', 'parent_available', 3, '3d')]:
        key = 'homelab.' + suffix + '[{#ID}]'
        api.ensure('itemprototype', 'key_', key, {
            'hostid': host, 'ruleid': discovery, 'name': '{#NAME}: ' + suffix,
            'type': 18, 'master_itemid': master, 'value_type': value_type, 'delay': '0',
            'history': history, 'trends': '0',
            'tags': [{'tag': 'family', 'value': '{#FAMILY}'}, {'tag': 'check_id', 'value': '{#ID}'}],
            # A retired discovered resource has no matching object. Discard its
            # value while LLD disables it; missing fields on present checks
            # still become unsupported so genuine schema faults remain visible.
            'preprocessing': [
                {'type': 12, 'params': '$.checks[?(@.id == "{#ID}")].first()', 'error_handler': 1},
                {'type': 12, 'params': '$.' + field, 'error_handler': 0},
            ],
        }, 'itemid', query={'discoveryids': [discovery], 'filter': {'key_': key}, 'output': ['itemid']})
    for severity in (1, 2, 3, 4):
        name = '{#NAME}: persistent failure (severity ' + str(severity) + ')'
        api.ensure('triggerprototype', 'description', name, {
            'expression': (sample_gate('homelab.state', '{#FAILURE_SAMPLES}', [1, 3, 5]) + ' and '
                           + sample_gate('homelab.parent_available', '{#GRACE_SAMPLES}', windows)
                           + ' and last(/HomePBP/homelab.severity[{#ID}])=' + str(severity)),
            'priority': severity, 'manual_close': 1,
            'recovery_mode': 1,
            'recovery_expression': 'count(/HomePBP/homelab.state[{#ID}],#5)=5 and max(/HomePBP/homelab.state[{#ID}],#5)=0',
            'opdata': '{?last(/HomePBP/homelab.detail[{#ID}])}',
            'tags': [{'tag': 'family', 'value': '{#FAMILY}'}, {'tag': 'check_id', 'value': '{#ID}'},
                     {'tag': 'managed_by', 'value': 'HOME-3'}, {'tag': 'notify_delay', 'value': '{#NOTIFY_DELAY}'},
                     {'tag': 'notification', 'value': '{#NOTIFICATION}'}],
        }, 'triggerid', query={'discoveryids': [discovery], 'filter': {'description': name}, 'output': ['triggerid']})
    api.ensure('trigger', 'description', 'Monitoring collector has no fresh data', {
        'expression': 'nodata(/HomePBP/homelab.snapshot,3m)=1', 'priority': 4,
        'recovery_mode': 1,
        'recovery_expression': 'count(/HomePBP/homelab.snapshot,5m)>=5 and nodata(/HomePBP/homelab.snapshot,90s)=0',
        'tags': [{'tag': 'family', 'value': 'monitoring'}, {'tag': 'managed_by', 'value': 'HOME-3'}],
    }, query={'hostids': [host], 'filter': {'description': 'Monitoring collector has no fresh data'}, 'output': ['triggerid']})
    # Detect preprocessing/configuration faults even while the master is healthy.
    api.ensure('item', 'key_', 'zabbix[host,,items_unsupported]', {
        'hostid': host, 'name': 'Unsupported monitoring items', 'type': 5, 'value_type': 3,
        'delay': '60s', 'history': '7d', 'trends': '0',
    }, query={'hostids': [host], 'filter': {'key_': 'zabbix[host,,items_unsupported]'}, 'output': ['itemid']})
    api.ensure('trigger', 'description', 'Monitoring has unsupported items', {
        'expression': 'min(/HomePBP/zabbix[host,,items_unsupported],3m)>0', 'priority': 3,
        'recovery_mode': 1,
        'recovery_expression': 'count(/HomePBP/zabbix[host,,items_unsupported],#5)=5 and max(/HomePBP/zabbix[host,,items_unsupported],#5)=0',
        'tags': [{'tag': 'family', 'value': 'monitoring'}, {'tag': 'managed_by', 'value': 'HOME-3'}],
    }, query={'hostids': [host], 'filter': {'description': 'Monitoring has unsupported items'}, 'output': ['triggerid']})
    return group


def configure_identity(api, group, existing):
    tokens = dict(existing or {})
    users = {}
    for mode, user_type, methods, permission in [('read', 1, READ, 2), ('operations', 2, READ + WRITE, 3)]:
        actions = ['add_problem_comments', 'acknowledge_problems', 'suppress_problems', 'change_severity', 'close_problems', 'edit_maintenance'] if mode == 'operations' else []
        role = api.ensure('role', 'name', 'Baloo monitoring ' + mode, {'type': user_type, 'rules': {
            'api.access': 1, 'api.mode': 1, 'api': methods,
            'ui.default_access': 0, 'modules.default_access': 0, 'actions.default_access': 0,
            'actions': [{'name': name, 'status': 1} for name in actions],
            'services.read.mode': 0, 'services.write.mode': 0,
        }})
        usergroup = api.ensure('usergroup', 'name', 'Baloo monitoring ' + mode, {
            'gui_access': 3, 'hostgroup_rights': [{'id': group, 'permission': permission}],
        }, 'usrgrpid')
        # Machine accounts have random unused passwords and disabled UI access.
        username = 'baloo-monitoring-' + mode
        found = api.call('user.get', {'filter': {'username': username}, 'output': ['userid']})
        user_props = {'roleid': role, 'usrgrps': [{'usrgrpid': usergroup}]}
        if not found:
            user_props['passwd'] = secrets.token_urlsafe(48)
        userid = api.ensure('user', 'username', username, user_props)
        users[mode] = userid
        if mode + '-token' not in tokens:
            tokenid = api.call('token.create', {'name': 'Baloo ' + mode, 'userid': userid})['tokenids'][0]
            tokens[mode + '-token'] = api.call('token.generate', [tokenid])[0]['token']
    return tokens, users['read']


def configure_security_review_identity(api, group, existing):
    """Give the deterministic review controller its own Zabbix API identity."""
    role = api.ensure('role', 'name', 'HomePBP security review reconciler', {
        'type': 2,
        'rules': {
            'api.access': 1, 'api.mode': 1, 'api': REVIEW_READ + REVIEW_WRITE,
            'ui.default_access': 0, 'modules.default_access': 0,
            'actions.default_access': 0,
            'actions': [{'name': name, 'status': 1} for name in (
                'add_problem_comments', 'acknowledge_problems',
                'suppress_problems', 'edit_maintenance')],
            'services.read.mode': 0, 'services.write.mode': 0,
        },
    })
    usergroup = api.ensure('usergroup', 'name', 'HomePBP security review reconciler', {
        'gui_access': 3,
        'hostgroup_rights': [{'id': group, 'permission': 3}],
    }, 'usrgrpid')
    username = 'homepbp-security-review-reconciler'
    found = api.call('user.get', {'filter': {'username': username}, 'output': ['userid']})
    if len(found) > 1:
        raise RuntimeError('Ambiguous security review reconciler user')
    properties = {'roleid': role, 'usrgrps': [{'usrgrpid': usergroup}]}
    if not found:
        properties['passwd'] = secrets.token_urlsafe(48)
    userid = api.ensure('user', 'username', username, properties)
    token = (existing or {}).get('api-token')
    if token:
        return token
    tokenid = api.call('token.create', {
        'name': 'HomePBP security review reconciler', 'userid': userid,
    })['tokenids'][0]
    return api.call('token.generate', [tokenid])[0]['token']


def configure_security_review_access(api, group):
    """Provision API and transport tokens without exposing them to agent files."""
    api_secret = read_secret('zabbix', 'security-review-reconciler') or {}
    api_token = configure_security_review_identity(api, group, api_secret)
    if not api_secret.get('api-token'):
        write_secret('zabbix', 'security-review-reconciler', {'api-token': api_token})

    controller = read_secret('zabbix', 'security-review-controller') or {}
    baloo = read_secret('baloo', 'security-review-access') or {}
    baloo_token = controller.get('baloo-token') or baloo.get('token') or secrets.token_urlsafe(48)
    collector_token = controller.get('collector-token') or secrets.token_urlsafe(48)
    if controller.get('baloo-token') != baloo_token or controller.get('collector-token') != collector_token:
        write_secret('zabbix', 'security-review-controller', {
            'baloo-token': baloo_token, 'collector-token': collector_token,
        })
    if baloo.get('token') != baloo_token:
        write_secret('baloo', 'security-review-access', {'token': baloo_token})


def configure_alerts(api, group, user, token):
    script = '''var p = JSON.parse(value), request = new HttpRequest();
request.addHeader('Content-Type: application/json');
request.addHeader('Authorization: Bearer ' + p.token);
request.addHeader('Idempotency-Key: zabbix-' + p.event_id + '-' + p.state);
request.post('http://openclaw.baloo.svc:18789/hooks/zabbix', JSON.stringify({
  event_id: p.event_id, state: p.state, name: p.name
}));
if (request.getStatus() !== 200) { throw 'Baloo alert admission failed: HTTP ' + request.getStatus(); }
return 'accepted';'''
    media = api.ensure('mediatype', 'name', 'Baloo monitoring', {'type': 4, 'status': 0, 'script': script, 'timeout': '30s',
        'maxattempts': 3, 'attempt_interval': '30s', 'parameters': [
            {'name': 'token', 'value': token}, {'name': 'event_id', 'value': '{EVENT.ID}'},
            {'name': 'state', 'value': '{EVENT.VALUE}'}, {'name': 'name', 'value': '{EVENT.NAME}'}],
        'message_templates': [{'eventsource': 0, 'recovery': mode, 'subject': '{EVENT.NAME}', 'message': '{EVENT.ID}'} for mode in (0, 1)],
    })
    api.call('user.update', {'userid': user, 'medias': [{'mediatypeid': media, 'sendto': ['Baloo'], 'active': 0, 'severity': 60, 'period': '1-7,00:00-24:00'}]})
    operation = {'operationtype': 0, 'opmessage': {'default_msg': 1, 'mediatypeid': media}, 'opmessage_usr': [{'userid': user}]}
    configure_notification_actions(api, group, operation)


def configure_notification_actions(api, group, operation):
    for delay in ('immediate', '5m', '10m'):
        conditions = [{'conditiontype': 0, 'operator': 0, 'value': group},
                      {'conditiontype': 26, 'operator': 1, 'value2': 'notification', 'value': 'dashboard'}]
        if delay == 'immediate':
            # Untagged monitoring triggers retain immediate delivery.
            conditions += [{'conditiontype': 26, 'operator': 1, 'value2': 'notify_delay', 'value': value}
                           for value in ('5m', '10m')]
        else:
            conditions.append({'conditiontype': 26, 'operator': 0, 'value2': 'notify_delay', 'value': delay})
        step = 1 if delay == 'immediate' else 2
        name = 'HomePBP problems to Baloo' + ('' if delay == 'immediate' else ' after ' + delay)
        api.ensure('action', 'name', name, {'eventsource': 0, 'status': 0,
            'esc_period': '1m' if delay == 'immediate' else delay,
            'filter': {'evaltype': 1, 'conditions': conditions},
            'operations': [{**operation, 'esc_step_from': step, 'esc_step_to': step}],
            # No recovery-only messages for incidents that ended before notification.
            'recovery_operations': [{'operationtype': 11, 'opmessage': {'default_msg': 1}}], 'pause_suppressed': 1,
            'notify_if_canceled': 0,
        })


def disable_direct_alerts(api):
    """Retire per-event WhatsApp delivery after the digest has been verified."""
    names = ['HomePBP problems to Baloo', 'HomePBP problems to Baloo after 5m',
             'HomePBP problems to Baloo after 10m']
    for name in names:
        found = api.call('action.get', {'filter': {'name': name}, 'output': ['actionid', 'name', 'status']})
        if len(found) > 1:
            raise RuntimeError('Ambiguous direct alert action: ' + name)
        if found and found[0]['status'] != '1':
            api.call('action.update', {'actionid': found[0]['actionid'], 'status': 1})
            print('Disabled direct alert action:', name)


def retire_synthetic_mail_check(api):
    hosts = api.call('host.get', {'filter': {'host': 'HomePBP'}, 'output': ['hostid']})
    if len(hosts) != 1:
        raise RuntimeError('Managed HomePBP host is missing or ambiguous')
    hostid = hosts[0]['hostid']
    replacement = api.call('item.get', {'hostids': [hostid],
        'filter': {'key_': 'homelab.state[28535fcadaa7928644a0]', 'status': 0},
        'output': ['state', 'lastvalue', 'lastclock']})
    if (len(replacement) != 1 or replacement[0]['state'] != '0'
            or replacement[0]['lastvalue'] != '0'
            or time.time() - int(replacement[0]['lastclock']) > 180):
        raise RuntimeError('Replacement mail activity check must be fresh and healthy before retiring the old gate')
    problems = api.call('problem.get', {'hostids': [hostid], 'output': ['eventid', 'name'], 'selectTags': 'extend'})
    for problem in problems:
        tags = {(tag['tag'], tag['value']) for tag in problem['tags']}
        if (problem['name'].startswith('Mail round-trip coverage:')
                and ('managed_by', 'HOME-3') in tags
                and ('check_id', '66d4360851afd8a530ee') in tags):
            api.call('event.acknowledge', {'eventids': [problem['eventid']], 'action': 5,
                'message': 'Retired the synthetic-coverage gate per Alpar: replaced by normal incoming-mail activity monitoring, continuously, initially 24h and adaptive. This policy change does not certify outbound delivery.'})
            print('Requested closure of superseded synthetic mail warning:', problem['eventid'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18080')
    parser.add_argument('--apply', action='store_true', help='Reconcile monitoring configuration and bootstrap credentials')
    parser.add_argument('--enable-alerts', action='store_true', help='Enable delivery after the Baloo hook is configured and verified')
    parser.add_argument('--disable-direct-alerts', action='store_true',
                        help='Disable the three integration-owned per-event actions after the digest is verified')
    parser.add_argument('--retire-synthetic-mail-check', action='store_true',
                        help='Close only the superseded synthetic coverage warning after the replacement check is fresh and healthy')
    parser.add_argument('--security-review-only', action='store_true',
                        help='Provision only the restricted security-review API and transport credentials')
    args = parser.parse_args()
    if args.enable_alerts and args.disable_direct_alerts:
        parser.error('--enable-alerts and --disable-direct-alerts are mutually exclusive')
    if args.security_review_only and (args.enable_alerts or args.disable_direct_alerts or args.retire_synthetic_mail_check):
        parser.error('--security-review-only cannot be combined with alert or retirement actions')
    api = API(args.url)
    print('Zabbix API version:', api.call('apiinfo.version', {}))
    if not args.apply:
        print('Read-only check. Pass --apply to bootstrap and reconcile HOME-3 objects.')
        return
    credentials = read_secret('zabbix', 'zabbix-admin')
    initial = not credentials
    password = credentials['password'] if credentials else 'zabbix'
    api.token = api.call('user.login', {'username': 'Admin', 'password': password})
    if initial:
        old_password = password
        password = secrets.token_urlsafe(48)
        me = api.call('user.get', {'filter': {'username': 'Admin'}, 'output': ['userid']})[0]['userid']
        api.call('user.update', {'userid': me, 'passwd': password, 'current_passwd': old_password})
        write_secret('zabbix', 'zabbix-admin', {'username': 'Admin', 'password': password})
        # Re-authenticate because changing a password can invalidate sessions.
        api.token = None
        api.token = api.call('user.login', {'username': 'Admin', 'password': password})
    if args.disable_direct_alerts:
        disable_direct_alerts(api)
        return
    if args.security_review_only:
        groups = api.call('hostgroup.get', {'filter': {'name': 'HomePBP'}, 'output': ['groupid']})
        if len(groups) != 1:
            raise RuntimeError('Managed HomePBP host group is missing or ambiguous')
        configure_security_review_access(api, groups[0]['groupid'])
        print('Reconciled restricted security-review identity and credentials. No credentials printed.')
        return
    group = configure_checks(api)
    values, user = configure_identity(api, group, read_secret('baloo', 'zabbix-mcp'))
    write_secret('baloo', 'zabbix-mcp', values)
    configure_security_review_access(api, group)
    gateway = read_secret('baloo', 'baloo-secrets') or {}
    token = gateway.get('MONITORING_HOOK_TOKEN')
    if not token:
        token = secrets.token_urlsafe(48)
        kubectl('-n', 'baloo', 'patch', 'secret', 'baloo-secrets', '--type=merge', '--patch-file=/dev/stdin',
                value=json.dumps({'stringData': {'MONITORING_HOOK_TOKEN': token}}))
    if args.enable_alerts:
        configure_alerts(api, group, user, token)
    if args.retire_synthetic_mail_check:
        retire_synthetic_mail_check(api)
    print('Reconciled HOME-3 checks and restricted read/operations identities. No credentials printed.')


if __name__ == '__main__':
    main()
