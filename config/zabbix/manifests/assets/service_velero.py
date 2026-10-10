"""Passive Velero resource-backup monitoring; never starts backups or restores."""
from datetime import datetime, timezone
from urllib.parse import quote


BASE = '/apis/velero.io/v1/namespaces/velero/'


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamp needs timezone')
    return result.timestamp()


def read(ctx, path, listing=False):
    # Shared Kubernetes transport can consume up to 15 seconds.
    if ctx.remaining() < 6:
        raise TimeoutError('deadline')
    result = ctx.kube.get(BASE + path + ('?limit=500' if listing else ''))
    if not listing:
        if not isinstance(result, dict):
            raise ValueError('invalid resource')
        return result
    if not isinstance(result, dict) or not isinstance(result.get('items'), list):
        raise ValueError('invalid list')
    if result.get('metadata', {}).get('continue') or len(result['items']) > 500:
        raise ValueError('list exceeds monitoring bound')
    return result['items']


def run(ctx, config):
    checks = []
    for location in config['locations']:
        obj = read(ctx, 'backupstoragelocations/' + quote(location, safe=''))
        status = obj.get('status', {})
        validated = timestamp(status['lastValidationTime']) if status.get('lastValidationTime') else 0
        age = ctx.now - validated
        bad = status.get('phase') != 'Available' or age < -300 or age > config['validation_max_age']
        checks.append(ctx.check('Velero storage ' + location, bad,
                                'Storage available with recent validation' if not bad else
                                'Storage unavailable or validation missing/stale'))
    expected = config['daily_schedules']
    if not expected:
        checks.append(ctx.check('Velero scheduled resource backups', False,
                                'No resource-backup schedules configured for monitoring'))
        return checks
    schedules = {obj['metadata']['name']: obj for obj in read(ctx, 'schedules', True)}
    backups = read(ctx, 'backups', True)
    for name, policy in expected.items():
        obj = schedules.get(name)
        detail, bad = evaluate(ctx.now, obj, backups, name, policy)
        paused = obj is not None and obj.get('spec', {}).get('paused') is True
        checks.append(ctx.check('Velero schedule ' + name, bad, detail,
                                observation='unknown' if paused else 'known'))
    return checks


def evaluate(now, schedule, backups, name, policy):
    if schedule is None:
        return 'Expected schedule missing; remove expectation for intentional retirement', True
    spec, status = schedule.get('spec', {}), schedule.get('status', {})
    if spec.get('paused') is True:
        return 'Schedule intentionally paused; completion checks suspended', False
    hour, minute, grace = policy['hour_utc'], policy['minute'], policy['grace_seconds']
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 < grace < 86400):
        raise ValueError('invalid daily policy')
    cron = f'{minute} {hour} * * *'
    if spec.get('schedule') != cron or status.get('phase') != 'Enabled':
        return 'Schedule invalid, disabled, or cadence differs from monitoring policy', True
    day = datetime.fromtimestamp(now, timezone.utc).replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()
    due = day if now >= day + grace else day - 86400
    created = timestamp(schedule['metadata']['creationTimestamp'])
    if created > now + 300:
        return 'Schedule creation timestamp is invalid', True
    if created > due:
        return 'New schedule awaiting first required daily completion', False
    related = [b for b in backups if b.get('metadata', {}).get('labels', {}).get('velero.io/schedule-name') == name]
    related.sort(key=lambda b: timestamp(b['metadata']['creationTimestamp']), reverse=True)
    if related:
        latest = related[0]
        phase = latest.get('status', {}).get('phase')
        if phase in ('Failed', 'PartiallyFailed', 'FailedValidation',
                     'WaitingForPluginOperationsPartiallyFailed', 'FinalizingPartiallyFailed'):
            return 'Latest scheduled backup failed or partially failed', True
        if phase not in ('Completed', 'New', 'InProgress', 'WaitingForPluginOperations', 'Finalizing'):
            return 'Latest scheduled backup has missing or unrecognized phase', True
        if phase != 'Completed':
            age = now - timestamp(latest['metadata']['creationTimestamp'])
            if age < -300 or age > grace:
                return 'Latest scheduled backup stalled or has unrecognized phase', True
    for backup in related:
        bstatus = backup.get('status', {})
        if bstatus.get('phase') != 'Completed':
            continue
        completed = timestamp(bstatus['completionTimestamp'])
        started = timestamp(bstatus.get('startTimestamp') or backup['metadata']['creationTimestamp'])
        if due <= started <= completed <= now + 300:
            if bstatus.get('expiration') and timestamp(bstatus['expiration']) <= now:
                continue
            if bstatus.get('errors', 0):
                return 'Completed backup reports errors', True
            return 'Required daily resource backup completed; within grace for next run', False
    return 'No completed resource backup for latest required daily run', True
