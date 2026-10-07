#!/usr/bin/env python3
"""Reconcile HOME-3 monitoring, API roles, and tokens without printing secrets.

Run against a private kubectl port-forward after deploying config/zabbix.
This changes only integration-owned objects, except initial Admin password setup.
"""
import argparse
import base64
import json
import secrets
import subprocess
import urllib.request

READ = ['problem.get', 'event.get', 'host.get', 'trigger.get', 'item.get', 'history.get', 'maintenance.get']
WRITE = ['event.acknowledge', 'maintenance.create', 'maintenance.delete']


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
    # Payload travels through stdin; no credentials in command arguments or logs.
    resource = {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
                'metadata': {'name': name, 'namespace': namespace},
                'stringData': values}
    kubectl('apply', '-f', '-', value=json.dumps(resource))


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


def configure_checks(api):
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
                            [('ID', 'id'), ('NAME', 'name'), ('FAMILY', 'family')]],
    }, 'itemid', query={'hostids': [host], 'filter': {'key_': 'homelab.discovery'}, 'output': ['itemid']})
    for suffix, field, value_type, history in [('state', 'status', 3, '7d'), ('detail', 'detail', 4, '3d'), ('severity', 'severity', 3, '1d')]:
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
    for severity in (2, 3, 4):
        name = '{#NAME}: persistent failure (severity ' + str(severity) + ')'
        api.ensure('triggerprototype', 'description', name, {
            'expression': 'count(/HomePBP/homelab.state[{#ID}],#3)=3 and min(/HomePBP/homelab.state[{#ID}],#3)=1 and last(/HomePBP/homelab.severity[{#ID}])=' + str(severity),
            'priority': severity, 'manual_close': 1,
            'opdata': '{?last(/HomePBP/homelab.detail[{#ID}])}',
            'tags': [{'tag': 'family', 'value': '{#FAMILY}'}, {'tag': 'check_id', 'value': '{#ID}'}, {'tag': 'managed_by', 'value': 'HOME-3'}],
        }, 'triggerid', query={'discoveryids': [discovery], 'filter': {'description': name}, 'output': ['triggerid']})
    api.ensure('trigger', 'description', 'Monitoring collector has no fresh data', {
        'expression': 'nodata(/HomePBP/homelab.snapshot,3m)=1', 'priority': 4,
        'tags': [{'tag': 'family', 'value': 'monitoring'}, {'tag': 'managed_by', 'value': 'HOME-3'}],
    }, query={'hostids': [host], 'filter': {'description': 'Monitoring collector has no fresh data'}, 'output': ['triggerid']})
    # Detect preprocessing/configuration faults even while the master is healthy.
    api.ensure('item', 'key_', 'zabbix[host,,items_unsupported]', {
        'hostid': host, 'name': 'Unsupported monitoring items', 'type': 5, 'value_type': 3,
        'delay': '60s', 'history': '7d', 'trends': '0',
    }, query={'hostids': [host], 'filter': {'key_': 'zabbix[host,,items_unsupported]'}, 'output': ['itemid']})
    api.ensure('trigger', 'description', 'Monitoring has unsupported items', {
        'expression': 'min(/HomePBP/zabbix[host,,items_unsupported],3m)>0', 'priority': 3,
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
    api.ensure('action', 'name', 'HomePBP problems to Baloo', {'eventsource': 0, 'status': 0,
        'filter': {'evaltype': 0, 'conditions': [{'conditiontype': 0, 'operator': 0, 'value': group}]},
        'operations': [{**operation, 'esc_step_from': 1, 'esc_step_to': 1}],
        'recovery_operations': [operation], 'pause_suppressed': 1,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18080')
    parser.add_argument('--apply', action='store_true', help='Reconcile monitoring configuration and bootstrap credentials')
    parser.add_argument('--enable-alerts', action='store_true', help='Enable delivery after the Baloo hook is configured and verified')
    args = parser.parse_args()
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
    group = configure_checks(api)
    values, user = configure_identity(api, group, read_secret('baloo', 'zabbix-mcp'))
    write_secret('baloo', 'zabbix-mcp', values)
    gateway = read_secret('baloo', 'baloo-secrets') or {}
    token = gateway.get('MONITORING_HOOK_TOKEN')
    if not token:
        token = secrets.token_urlsafe(48)
        kubectl('-n', 'baloo', 'patch', 'secret', 'baloo-secrets', '--type=merge', '--patch-file=/dev/stdin',
                value=json.dumps({'stringData': {'MONITORING_HOOK_TOKEN': token}}))
    if args.enable_alerts:
        configure_alerts(api, group, user, token)
    print('Reconciled HOME-3 checks and restricted read/operations identities. No credentials printed.')


if __name__ == '__main__':
    main()
