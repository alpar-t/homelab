#!/usr/bin/env python3
"""Check or apply the explicit Pocket ID application group policy."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


POLICY_PATH = Path(__file__).resolve().parents[1] / 'config/pocket-id/access-policy.json'


class PocketID:
    def __init__(self) -> None:
        secret = json.loads(subprocess.check_output([
            'kubectl', '-n', 'pocket-id', 'get', 'secret', 'pocket-id-api-key', '-o', 'json'
        ]))
        self.key = base64.b64decode(secret['data']['api_key']).decode()

    def api(self, path: str, method: str = 'GET', payload: dict | None = None):
        request = Request(
            'https://auth.newjoy.ro/api' + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'X-API-Key': self.key, 'Content-Type': 'application/json',
                     'User-Agent': 'homelab-account-admin/1.0'},
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read()
                return json.loads(body) if body else None
        except HTTPError as error:
            status = error.code
            error.close()
            raise RuntimeError(f'{method} {path}: HTTP {status}') from None
        except URLError:
            raise RuntimeError(f'{method} {path}: network request failed') from None

    def listing(self, path: str) -> list[dict]:
        entries = []
        page = 1
        while True:
            query = urlencode({'pagination[limit]': 100, 'pagination[page]': page})
            result = self.api(path + '?' + query)
            entries.extend(result['data'])
            if page >= result['pagination']['totalPages']:
                return entries
            page += 1


def reconcile(client: PocketID, policy: dict[str, list[str]], apply: bool) -> bool:
    clients = {item['id']: item for item in client.listing('/oidc/clients')}
    groups = {item['name']: item['id'] for item in client.listing('/user-groups')}
    unknown = set(clients) - set(policy)
    missing = set(policy) - set(clients)
    if unknown or missing:
        raise RuntimeError(f'Client inventory differs from policy; unknown={sorted(unknown)}, missing={sorted(missing)}')
    required_groups = {group for allowed in policy.values() for group in allowed}
    if any(not allowed for allowed in policy.values()):
        raise RuntimeError('Every client must have an explicit, nonempty group allowlist')
    if required_groups - groups.keys() - {'kids'}:
        raise RuntimeError(f'Missing access groups: {sorted(required_groups - groups.keys())}')
    if 'kids' not in groups:
        if not apply:
            raise RuntimeError('Missing kids group; run with --apply to create it')
        created = client.api('/user-groups', 'POST', {'name': 'kids', 'friendlyName': 'Kids'})
        groups['kids'] = created['id']
        print('Created kids group')

    compliant = True
    for identifier, allowed_names in policy.items():
        path = '/oidc/clients/' + identifier
        detail = client.api(path)
        desired_ids = {groups[name] for name in allowed_names}
        current_ids = {group['id'] for group in detail['allowedUserGroups']}
        if detail['isGroupRestricted'] and current_ids == desired_ids:
            continue
        compliant = False
        print(f'{"Apply" if apply else "Drift"}: {detail["name"]} ({identifier}) -> {", ".join(allowed_names)}')
        if not apply:
            continue
        if not detail['isGroupRestricted']:
            # Preserve the complete registration and authentication settings.
            # The read DTO includes extra fields ignored by Pocket ID's update DTO.
            updated = dict(detail, isGroupRestricted=True)
            client.api(path, 'PUT', updated)
        client.api(path + '/allowed-user-groups', 'PUT', {'userGroupIds': sorted(desired_ids)})
        verified = client.api(path)
        if not verified['isGroupRestricted'] or {g['id'] for g in verified['allowedUserGroups']} != desired_ids:
            raise RuntimeError(f'Group policy did not persist for {identifier}')
        # Group enforcement must not alter callbacks, secrets, or login behavior.
        for field in ('callbackURLs', 'logoutCallbackURLs', 'credentials', 'isPublic', 'pkceEnabled',
                      'requiresReauthentication', 'requiresPushedAuthorizationRequests', 'skipConsent', 'launchURL'):
            if detail.get(field) != verified.get(field):
                raise RuntimeError(f'Unexpected registration change in {identifier}: {field}')
    return compliant


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Apply and verify the policy; default is a read-only check')
    args = parser.parse_args()
    policy = json.loads(POLICY_PATH.read_text())
    try:
        compliant = reconcile(PocketID(), policy, args.apply)
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f'Access policy check failed: {error}', file=sys.stderr)
        return 1
    if compliant or args.apply:
        print(f'All {len(policy)} Pocket ID clients require their explicit access groups')
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
