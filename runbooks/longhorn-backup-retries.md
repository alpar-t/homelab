# Longhorn backup retries and freshness alerts

The scheduled Longhorn backup Kubernetes Job can finish successfully even when
individual volumes fail. Check `Backup` CRs and completed backup timestamps per
volume; the Job condition alone is not proof of a recovery point.

## Retry controller

`config/longhorn/backup_retry.py` is rendered into
`config/longhorn/manifests/backup-retry-configmap.yaml` by
`scripts/render-longhorn-backup-retry.py`. The `longhorn-backup-retry` CronJob runs
every 15 minutes with an isolated ServiceAccount. Its Role can list Longhorn
volumes, snapshots, backups, and namespace Jobs, and can create only snapshots
and backups. It cannot delete resources or read Secrets.

For the latest completed `weekly-backup` and `critical-daily-backup` Job, it
finds eligible volumes by their live Longhorn recurring-job labels. It checks
for a completed per-volume Backup created since the scheduled Job started. A
missing backup gets a first incremental attempt at least 15 minutes after Job
completion and at most one more attempt after a 45-minute backoff. At most two
volumes retry concurrently. Detached, degraded, or excluded volumes are not
retried. The controller stops six hours after Job completion. Deterministic CR
names prevent duplicate attempts on repeated controller runs. Kubernetes API
throttling and transient server errors are retried with bounded backoff.

Zabbix's Longhorn backup freshness checks hold a stale result during this
six-hour window after a scheduled Job, then report it if there is still no
recent completed Backup. The collector reads Jobs only; it cannot create or
alter backups. The 48-hour critical and 10-day weekly freshness limits also
exceed the retry window. A backup that never gets a healthy attached volume, or
a retry controller that fails, becomes alertable when the window closes.

Inspect a run with:

```bash
kubectl -n longhorn-system get cronjob longhorn-backup-retry
kubectl -n longhorn-system get jobs -l batch.kubernetes.io/cronjob-name=longhorn-backup-retry
kubectl -n longhorn-system logs job/<retry-job-name>
kubectl -n longhorn-system get backups.longhorn.io
```

Do not infer success from a retry Job's `Complete` condition. Check the Backup
CR's `status.state=Completed`, `status.volumeName`, and `backupCreatedAt`.
Persistent failures need a volume/engine and B2 connectivity investigation.
Do not reset the Zabbix freshness state to hide them.

## Labels and exclusions

PVC `recurring-job-group.longhorn.io/critical=enabled` does not propagate to
the Longhorn Volume by itself. Set `recurring-job.longhorn.io/source=enabled`
on the PVC and retain `recurring-job-group.longhorn.io/default=enabled` to keep
weekly coverage when enabling critical daily backups. Verify the live Volume
labels and the next scheduled Backup objects. Review B2 capacity before
enabling daily backups for the seven large Immich library PVCs.

Rebuildable Immich ML caches are excluded through
`immich/model-cache-immich-ml-*` in `backup-exclusions.yaml`, which covers new
StatefulSet ordinals when the exclusion hook runs. The
`longhorn-ml-cache-exclusion` CronJob reconciles new ordinals every five minutes
between ArgoCD syncs. It only lists Immich PVCs, reads their PVs, and patches
Longhorn Volume labels. The hook and CronJob add the `excluded` group and remove
the `default` group. After sync, verify that all current cache Volumes lack
`default` and `critical` groups. The next scheduled run is the final proof that
no new cache Backup CR appears.
