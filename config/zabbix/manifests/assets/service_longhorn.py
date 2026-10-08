"""Passive backup-store controller reconciliation; never initiates storage work."""
from datetime import datetime


def run(ctx, config):
    name = 'Longhorn backup-store reconciliation'
    try:
        if ctx.remaining() < 16:
            raise ValueError('insufficient request budget')
        # One named CR GET, using the collector's existing 15-second API timeout.
        target = ctx.kube.get('/apis/longhorn.io/v1beta2/namespaces/'
                              'longhorn-system/backuptargets/default')
        if target.get('kind') != 'BackupTarget':
            raise ValueError('invalid resource')
        status = target['status']
        stamp = datetime.fromisoformat(status['lastSyncedAt'].replace('Z', '+00:00'))
        if stamp.tzinfo is None or not isinstance(status.get('ownerID'), str) or not status['ownerID']:
            raise ValueError('invalid reconciliation metadata')
        age = ctx.now - stamp.timestamp()
        limit = config['max_sync_age_seconds']
        if type(limit) is not int or not 3600 <= limit <= 86400:
            raise ValueError('invalid freshness policy')
        bad = age < -300 or age > limit
        detail = f'backup-store synchronization age={age / 60:.0f}m; limit={limit / 60:.0f}m'
        return [ctx.check(name, bad, detail)]
    except Exception:
        # Never include exception messages: API responses may contain storage URLs.
        return [ctx.check(name, True, 'backup-store reconciliation metadata unavailable or invalid')]
