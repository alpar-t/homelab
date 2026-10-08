"""Read-only PinchTab control-plane contracts; never start a browser or read tabs."""
import json


def request(ctx, target, path, token):
    remaining = ctx.remaining()
    if remaining <= 0:
        raise ValueError('deadline')
    response = ctx.http(target['url'] + path,
                        headers={'Authorization': 'Bearer ' + token},
                        timeout=min(4, remaining), max_bytes=131072,
                        follow_redirects=False)
    if response.status != 200:
        raise ValueError('API refused')
    return json.loads(response.body)


def run(ctx, config):
    records = []
    for target in config['targets']:
        name = 'PinchTab ' + target['name']
        try:
            token = ctx.secret(target['credential'])
        except Exception:
            records.append(ctx.check(name, True, 'monitoring credential unavailable'))
            continue
        try:
            health = request(ctx, target, '/health', token)
            if (not isinstance(health, dict) or health.get('status') != 'ok'
                    or health.get('mode') != 'dashboard'
                    or health.get('authRequired') is not True
                    or not isinstance(health.get('version'), str)
                    or not health['version']
                    or type(health.get('instances')) is not int
                    or health['instances'] < 0
                    or type(health.get('restartRequired')) is not bool):
                raise ValueError('invalid health contract')
            instances = request(ctx, target, '/instances', token)
            states = {'starting', 'running', 'stopping', 'stopped', 'error'}
            if (not isinstance(instances, list) or any(
                    not isinstance(row, dict)
                    or not isinstance(row.get('id'), str) or not row['id']
                    or row.get('status') not in states for row in instances)):
                raise ValueError('invalid instance contract')
            # Bearer GET listing is a defensive copy, unlike Session auth which
            # touches persisted activity. OLX intentionally has sessions disabled.
            if target.get('sessions'):
                sessions = request(ctx, target, '/sessions', token)
                if not isinstance(sessions, list) or any(
                        not isinstance(row, dict)
                        or not isinstance(row.get('id'), str) or not row['id']
                        or not isinstance(row.get('status'), str)
                        for row in sessions):
                    raise ValueError('invalid session contract')
            failed = any(row['status'] == 'error' for row in instances)
            records.append(ctx.check(name, failed or health['restartRequired'],
                'instance error reported' if failed else
                'configuration restart required' if health['restartRequired'] else
                'authenticated metadata valid; running=%d; idle is allowed' %
                sum(row['status'] == 'running' for row in instances)))
        except Exception:
            records.append(ctx.check(name, True,
                                     'authenticated metadata unavailable or invalid'))
    return records
