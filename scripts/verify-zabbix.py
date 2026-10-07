#!/usr/bin/env python3
"""Read-only live verification of HOME-3 configuration and API boundaries."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('zabbix_bootstrap', Path(__file__).with_name('bootstrap-zabbix.py'))
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def expect_denied(api, method, params):
    try:
        api.call(method, params)
    except RuntimeError as error:
        if 'No permissions to call' in str(error):
            return
        raise RuntimeError('Expected API-role denial for ' + method + '; got ' + str(error))
    raise RuntimeError('Forbidden API method was accepted: ' + method)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18080')
    args = parser.parse_args()
    credentials = bootstrap.read_secret('baloo', 'zabbix-mcp')
    if not credentials:
        raise RuntimeError('Monitoring credentials are missing')
    for mode in ('read', 'operations'):
        api = bootstrap.API(args.url)
        api.token = credentials[mode + '-token']
        hosts = api.call('host.get', {'output': ['hostid', 'host']})
        if len(hosts) != 1 or hosts[0]['host'] != 'HomePBP':
            raise RuntimeError(mode + ': unexpected host scope')
        expect_denied(api, 'user.get', {})
        expect_denied(api, 'script.execute', {'scriptid': '0', 'hostid': '0'})
        expect_denied(api, 'host.create', {})
        if mode == 'read':
            expect_denied(api, 'event.acknowledge', {'eventids': ['0'], 'action': 4, 'message': 'must be rejected'})
            expect_denied(api, 'maintenance.create', {})
        print(mode + ' identity: HomePBP-only access; forbidden methods rejected by Zabbix')
    api.token = credentials['read-token']
    hostid = hosts[0]['hostid']
    items = api.call('item.get', {'hostids': [hostid], 'filter': {'status': 0},
                                'output': ['itemid', 'name', 'key_', 'state', 'error', 'lastclock']})
    unsupported = [i for i in items if i['state'] != '0']
    snapshot = next((i for i in items if i['key_'] == 'homelab.snapshot'), None)
    if not snapshot or time.time() - int(snapshot['lastclock']) > 180:
        raise RuntimeError('Monitoring snapshot is missing or stale')
    if unsupported:
        raise RuntimeError('Unsupported active monitoring items: ' + json.dumps(unsupported[:5])
                           + '; total=' + str(len(unsupported)))
    states = [i for i in items if i['key_'].startswith('homelab.state[')]
    if not states:
        raise RuntimeError('No discovered checks yet')
    stale = [i['name'] for i in items if i['key_'].startswith(
        ('homelab.state[', 'homelab.detail[', 'homelab.severity['))
        and time.time() - int(i['lastclock']) > 180]
    if stale:
        raise RuntimeError('Active check values are missing or stale: ' + json.dumps(stale[:5])
                           + '; total=' + str(len(stale)))
    problems = api.call('problem.get', {'output': ['eventid', 'name', 'severity', 'acknowledged', 'suppressed'], 'selectTags': 'extend'})
    print(json.dumps({'discovered_checks': len(states), 'unsupported_items': len(unsupported),
                      'snapshot_age_seconds': round(time.time() - int(snapshot['lastclock'])), 'problems': problems}, indent=2))


if __name__ == '__main__':
    main()
