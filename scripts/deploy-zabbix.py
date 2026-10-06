#!/usr/bin/env python3
"""Deploy the prepared private Zabbix stack; no Baloo rollout or messages."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(*args, value=None, capture=False):
    result = subprocess.run(['kubectl', *args], input=value, text=True,
                            stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    if result.stderr:
        print(result.stderr.strip())
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        print('Prepared: private Zabbix server/frontend, 2 CNPG instances with 10Gi local SSD each, read-only collector, daily B2 backups.')
        print('Pass --apply to deploy. This does not change Baloo, enable notifications, or send synthetic mail.')
        return
    source = json.loads(run('-n', 'stalwart-mail', 'get', 'secret', 'cnpg-backup-credentials', '-o', 'json', capture=True))
    keys = ['ACCESS_KEY_ID', 'SECRET_ACCESS_KEY']
    if not all(key in source.get('data', {}) for key in keys):
        raise RuntimeError('CNPG backup credential source lacks required keys')
    run('apply', '-f', str(ROOT / 'config/zabbix/manifests/namespace.yaml'))
    target = {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
              'metadata': {'name': 'cnpg-backup-credentials', 'namespace': 'zabbix'},
              'data': {key: source['data'][key] for key in keys}}
    run('apply', '-f', '-', value=json.dumps(target))
    run('apply', '-k', str(ROOT / 'config/zabbix/manifests'))
    print('Private Zabbix resources deployed. Wait for CNPG and pods, then run bootstrap-zabbix.py through a private port-forward.')


if __name__ == '__main__':
    main()
