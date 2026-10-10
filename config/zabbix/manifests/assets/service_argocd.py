"""Passive, bounded Application reconciliation checks; never copies CR messages."""
from datetime import datetime

_since = {}


def timestamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def run(ctx, config):
    try:
        # One page only: the shared Kubernetes client has a 15-second timeout.
        # Require enough remaining budget; refuse truncated inventories.
        if ctx.remaining() < 6:
            raise ValueError('budget')
        page = ctx.kube.get('/apis/argoproj.io/v1alpha1/namespaces/argocd/applications?limit=500')
        apps = page['items']
        if not isinstance(apps, list) or not apps or len(apps) > 500 or page.get('metadata', {}).get('continue'):
            raise ValueError('inventory')
        errors = stalled = paused = 0
        deferred_errors = deferred_progress = False
        active = set()
        for app in apps:
            meta, spec, status = app['metadata'], app['spec'], app.get('status', {})
            key = meta.get('uid') or meta['name']
            auto = spec.get('syncPolicy', {}).get('automated')
            annotations = meta.get('annotations', {})
            if (meta.get('deletionTimestamp') or auto is None or auto.get('enabled') is False
                    or annotations.get('argocd.argoproj.io/skip-reconcile') == 'true'
                    or annotations.get('monitoring.homepbp.io/maintenance') == 'true'):
                paused += 1
                if not meta.get('deletionTimestamp'):
                    deferred_progress |= status.get('sync', {}).get('status') != 'Synced' or status.get('health', {}).get('status') not in ('Healthy', 'Suspended')
                    deferred_errors |= status.get('sync', {}).get('status') == 'Unknown' or any(
                        c.get('type') in ('ComparisonError', 'InvalidSpecError', 'SyncError', 'UnknownError')
                        for c in status.get('conditions', []))
                continue
            active.add(key)
            sync = status.get('sync', {}).get('status')
            health = status.get('health', {}).get('status')
            operation = status.get('operationState', {})
            phase = operation.get('phase')
            broken = sync == 'Unknown' or any(c.get('type') in (
                'ComparisonError', 'InvalidSpecError', 'SyncError', 'UnknownError')
                for c in status.get('conditions', []))
            reconciled = timestamp(status.get('reconciledAt'))
            stale = reconciled is None or ctx.now - reconciled > config['freshness_seconds']
            failed = phase in ('Failed', 'Error') and sync != 'Synced'
            pending = broken or stale or failed or sync != 'Synced' or health not in ('Healthy', 'Suspended')
            if not pending:
                _since.pop(key, None)
                continue
            first = _since.setdefault(key, ctx.now)
            if ctx.now - first < config['grace_seconds']:
                deferred_errors |= broken
                deferred_progress = True
                continue
            if broken:
                errors += 1
            if stale or failed or sync != 'Synced' or health != 'Healthy':
                stalled += 1
        for key in list(_since):
            if key not in active:
                _since.pop(key, None)
        return [ctx.check('ArgoCD Application inventory', False, f'{len(apps)} applications; {paused} paused'),
                ctx.check('ArgoCD Repository and comparison', errors > 0, f'{errors} applications with persistent comparison/spec/sync errors',
                          observation='unknown' if deferred_errors and not errors else 'known'),
                ctx.check('ArgoCD Reconciliation progress', stalled > 0, f'{stalled} applications persistently unhealthy, unsynced or stale',
                          observation='unknown' if deferred_progress and not stalled else 'known')]
    except Exception:
        return [ctx.check('ArgoCD Application inventory', True, 'Application API unavailable, incomplete or malformed')]
